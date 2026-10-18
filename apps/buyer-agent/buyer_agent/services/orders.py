"""Order service (7.1-7.4): PO over A2A, Payment Mandate (payee from the registry, never from the model),
upi:// link + QR, cooling-off, idempotency (R11), payment proof."""
from __future__ import annotations

import base64
import io
import logging
import re
import uuid
from datetime import timedelta
from urllib.parse import quote as urlquote

from sauda_trust.registry import mask_vpa, payee_ref

from .. import store, trust
from ..deps import settings
from ..negotiation.a2a import SupplierClient

log = logging.getLogger("buyer_agent.orders")


def cart_hash(cart: dict) -> str:
    """Stable hash of the cart draft's allocations (the Cart Mandate body carries the same allocations)."""
    return store.sha256_json([{"supplier_id": a["supplier_id"], "lines": [{"gtin": l["gtin"], "qty": l["qty"], "unit_price_paise": l["unit_price_paise"]} for l in a["lines"]]}
                              for a in cart["allocations"]])


def idempotency_key(cart: dict) -> str:
    return store.sha256_json(cart_hash(cart))


def cart_action(nid: str, cart: dict) -> dict:
    return {"kind": "place_order", "negotiation_id": nid, "idempotency_key": idempotency_key(cart), "allocations": [
        {"supplier_id": a["supplier_id"], "lines": [{"gtin": l["gtin"], "qty": l["qty"], "unit_price_paise": l["unit_price_paise"]} for l in a["lines"]],
         "subtotal_paise": a["subtotal_paise"], "delivery_days": a["delivery_days"], "advance_pct": a["advance_pct"],
         "payout_vpa": a["payout_vpa"]} for a in cart["allocations"]]}


def seen_keys(nid: str) -> set[str]:
    return {o.get("cart_idempotency_key") for o in store.orders_for(nid) if o.get("cart_idempotency_key")}


def latest_guard_verdicts(nid: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for o in store.offers_for(nid):
        if o.get("direction") in ("quote", "revised", "final"):
            out[o["supplier_id"]] = {"blocked": o.get("guard_verdict") != "clean"}
    return out


def place(nid: str, cart_draft_id: str) -> dict:
    """Executes after the broker's all-rule gate passed (owner confirmed). Idempotent per negotiation."""
    existing = store.orders_for(nid)
    if existing:
        return {"status": "placed", "order_ids": sorted(o["order_id"] for o in existing), "already_placed": True}
    n = store.negotiation(nid)
    cart = store.cart_draft(cart_draft_id)
    if not cart or not n.get("cart_mandate_id"):
        return {"status": "denied", "reasons": ["CART_MANDATE_MISSING"]}
    cmand = trust.get_mandate(n["cart_mandate_id"])
    if cmand is None or not cmand.signature_valid() or cart_hash(cart) != cart_hash(cmand.body):
        # the cart draft must be exactly what the owner's signed Cart Mandate covers
        return {"status": "denied", "reasons": ["CART_CHANGED"]}
    chash = cmand.body_hash
    ikey = idempotency_key(cart)
    cool_until = store.iso(store.now() + timedelta(minutes=settings().cooling_off_min))
    order_ids = []
    for a in cart["allocations"]:
        sid = a["supplier_id"]
        oid = f"ord_{nid[-12:]}_{sid}"
        po = {"type": "PO", "order_id": oid, "cart_hash": chash,
              "lines": [{"gtin": l["gtin"], "qty": l["qty"], "unit_price_paise": l["unit_price_paise"]} for l in a["lines"]],
              "delivery_days": a.get("delivery_days"), "payment_terms": f"{a.get('advance_pct', 0)}% advance, UPI to registered payee"}
        o = {
            "order_id": oid, "negotiation_id": nid, "shop_id": n["shop_id"], "owner_uid": n.get("owner_uid"),
            "cart_mandate_id": n["cart_mandate_id"],
            "cart_draft_id": cart_draft_id, "payment_mandate_id": None, "supplier_id": sid, "supplier_name": a.get("supplier_name"),
            "lines": a["lines"], "total_paise": a["subtotal_paise"], "status": "cooling_off", "cooling_off_until": cool_until,
            "idempotency_key": store.sha256_json(f"{chash}:{sid}"), "cart_idempotency_key": ikey, "cart_hash": chash,
            "utr": None, "po": po, "po_ack": None, "po_error": None, "po_status": "sending", "created_at": store.iso(),
        }
        # Create the order record on its deterministic id BEFORE the PO goes out: a concurrent or repeated
        # approval loses the create and never sends a second PO.
        if not store.create_order(o):
            log.warning("order %s already exists; PO not resent", oid)
            order_ids.append(oid)
            continue
        ack, ack_err = None, None
        try:
            client = SupplierClient.load(sid)
            nonce = uuid.uuid4().hex
            trust.ledger_append(nid, "po.sent", "buyer", {"supplier_id": sid, "order_id": oid, "nonce": nonce, "message": po})
            ack = client.send(nid, po, f"Purchase order {oid} from Sauda for {len(po['lines'])} lines.", nonce).data
        except Exception as e:  # PO recorded either way; supplier ack status is shown
            ack_err = type(e).__name__
            log.warning("PO to %s failed: %s", sid, e)
        po_status = "error" if ack_err else str((ack or {}).get("status") or "unknown")
        store.update_order(oid, po_ack=ack, po_error=ack_err, po_status=po_status)
        o.update(po_ack=ack, po_error=ack_err, po_status=po_status)
        trust.ledger_append(nid, "order.placed", "buyer", {
            "order_id": oid, "supplier_id": sid, "total_paise": a["subtotal_paise"], "cart_hash": chash,
            "idempotency_key": o["idempotency_key"], "po_ack_status": (ack or {}).get("status"), "cooling_off_until": cool_until})
        order_ids.append(oid)
    try:
        trust.mark_mandate(n["intent_mandate_id"], "consumed")
    except Exception:
        log.exception("mark consumed failed")
    store.update_negotiation(nid, status="ordered", ended_at=store.iso(), order_ids=order_ids)
    store.update_shop(n["shop_id"], active_negotiation_id=None)
    return {"status": "placed", "order_ids": order_ids}


# ---------------------------------------------------------------- payment
def payment_action(o: dict) -> dict:
    rec = trust.supplier(o["supplier_id"])
    payee = rec.payout_vpa if rec else None
    return {"kind": "issue_payment_mandate", "negotiation_id": o["negotiation_id"], "supplier_id": o["supplier_id"],
            "payee_vpa": payee, "amount_paise": int(o["total_paise"]),
            "idempotency_key": store.sha256_json(f"pay:{o['order_id']}")}


def upi_link(payee_vpa: str, payee_name: str, amount_paise: int, order_id: str, ref: str) -> str:
    am = f"{int(amount_paise) // 100}.{int(amount_paise) % 100:02d}"  # integer paise -> rupees, no float
    return (f"upi://pay?pa={urlquote(payee_vpa, safe='@.')}&pn={urlquote(payee_name)}&am={am}&cu=INR"
            f"&tn={urlquote(order_id)}&tr={urlquote(ref)}")


def qr_data_url(text: str) -> str:
    import qrcode

    try:
        from qrcode.image.pure import PyPNGImage

        img = qrcode.make(text, image_factory=PyPNGImage, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        from qrcode.image.svg import SvgPathImage

        img = qrcode.make(text, image_factory=SvgPathImage, box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf)
        return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def issue_payment(order_id: str, owner_uid: str) -> dict:
    """Executes after the broker's gate (R1, R8, R11, R12). Payee comes from the registry only."""
    o = store.order(order_id)
    if o is None:
        return {"status": "denied", "reasons": ["ORDER_NOT_FOUND"]}
    if o.get("payment_mandate_id"):
        return payment_view(o)
    if o.get("status") == "cancelled":
        return {"status": "denied", "reasons": ["ORDER_CANCELLED"]}
    if o.get("po_error") or (o.get("po_ack") or {}).get("status") != "accepted":
        # no money is requested for a PO the supplier did not fully accept
        return {"status": "denied", "reasons": ["PO_NOT_ACCEPTED"], "po_status": o.get("po_status")}
    rec = trust.supplier(o["supplier_id"])
    payee = rec.payout_vpa
    n = store.negotiation(o["negotiation_id"])
    amount = int(o["total_paise"])
    demo_amt = settings().demo_pay_amount_paise
    body = {
        "kind": "payment", "shop_id": o["shop_id"], "cart_mandate_id": o["cart_mandate_id"], "cart_hash": o["cart_hash"],
        "intent_mandate_id": n.get("intent_mandate_id"), "order_id": order_id, "supplier_id": o["supplier_id"],
        "payee_name": rec.name, "amount_paise": demo_amt or amount, "order_total_paise": amount,
        "demo_amount": bool(demo_amt), "payee_vpa": payee, "method": "upi", "cooling_off_until": o["cooling_off_until"],
    }
    pm = trust.create_mandate("payment", body, owner_uid)
    link = upi_link(payee, rec.name, body["amount_paise"], order_id, pm.mandate_id[-20:])
    store.update_order(order_id, payment_mandate_id=pm.mandate_id, payment_status="issued", upi_link=link,
                       demo_amount=bool(demo_amt), payment_amount_paise=body["amount_paise"])
    trust.ledger_append(o["negotiation_id"], "payment_mandate.issued", "buyer", {
        "order_id": order_id, "payment_mandate_id": pm.mandate_id, "amount_paise": body["amount_paise"],
        "payee_vpa": payee, "body_hash": pm.body_hash, "cooling_off_until": o["cooling_off_until"]})
    return payment_view(store.order(order_id))


def payment_view(o: dict) -> dict:
    """Shape for the owner app's Order type: flat order + payment_mandate summary + QR."""
    pm = trust.get_mandate(o["payment_mandate_id"]) if o.get("payment_mandate_id") else None
    o = {**o, "status": order_status(o), "payment_status": payment_status(o)}
    out = {**o, "order": o, "fulfilment_tracked": False, "demo_amount": bool(o.get("demo_amount")),
           "order_total_paise": o.get("total_paise")}
    if pm:
        b = pm.body
        link = o.get("upi_link") or upi_link(b["payee_vpa"], b.get("payee_name", ""), b["amount_paise"], o["order_id"], pm.mandate_id[-20:])
        out.update({
            "payment_mandate_id": pm.mandate_id,
            "payment_mandate": {"mandate_id": pm.mandate_id, "amount_paise": b["amount_paise"], "payee_vpa": b["payee_vpa"],
                                "payout_vpa_masked": mask_vpa(b["payee_vpa"]), "payee_ref": payee_ref(b["payee_vpa"]),
                                "payee_name": b.get("payee_name"), "upi_link": link, "cooling_off_until": b.get("cooling_off_until"),
                                "status": o.get("payment_status") or "issued", "bank_verified": False, "body": b, "body_hash": pm.body_hash,
                                "signature": pm.signature, "kms_key_version": pm.kms_key_version,
                                "order_total_paise": b.get("order_total_paise"), "demo_amount": b.get("demo_amount")},
            "upi_link": link, "qr_data_url": qr_data_url(link), "payout_vpa_masked": mask_vpa(b["payee_vpa"]),
            "caption": "Payment via your UPI app; Sauda never holds funds.",
        })
    return out


UTR_RE = re.compile(r"^\d{12}$")
CLAIM_NOTE = "UTR entered by the owner; amount and payee match the Payment Mandate. Not verified with the bank."


def payment_status(o: dict) -> str | None:
    """Honest payment state: issued | claimed | mismatch (| cancelled). Legacy stored 'settled' reads as 'claimed'."""
    st = o.get("payment_status")
    return "claimed" if st == "settled" else st


def order_status(o: dict) -> str | None:
    return "payment_claimed" if o.get("status") == "settled" else o.get("status")


def submit_proof(order_id: str, utr: str, amount_paise: int, payee_vpa: str | None = None) -> dict:
    o = store.order(order_id)
    if o is None or not o.get("payment_mandate_id"):
        return {"status": "not_found"}
    if payment_status(o) == "claimed":
        return {"status": "claimed", "order_id": order_id, "utr": o.get("utr"), "bank_verified": False, "note": CLAIM_NOTE}
    if o.get("status") == "cancelled":
        return {"status": "invalid", "order_id": order_id, "problems": ["order_cancelled"],
                "reason": "this order was cancelled; no payment is due"}
    if payment_status(o) == "mismatch":
        return {"status": "mismatch", "order_id": order_id, "problems": ["previous_mismatch"],
                "reason": "a mismatched payment proof is already recorded for this order; check with the supplier"}
    pm = trust.get_mandate(o["payment_mandate_id"])
    utr = (utr or "").strip()
    # A typo in the UTR is a form error: nothing is persisted or written to the ledger.
    if not UTR_RE.match(utr):
        return {"status": "invalid", "order_id": order_id, "problems": ["utr_format"],
                "reason": "UTR must be the 12-digit UPI reference number from your payment app"}
    problems = []
    if int(amount_paise) != int(pm.body["amount_paise"]):
        problems.append("amount_mismatch")
    if payee_vpa and payee_vpa.strip().lower() != pm.body["payee_vpa"].lower():
        problems.append("payee_mismatch")
    if any(x.get("order_id") != order_id for x in store.orders_with_utr(utr)):
        problems.append("utr_reused")  # one UPI reference pays one order
    nid = o["negotiation_id"]
    if problems:
        store.update_order(order_id, payment_status="mismatch")
        trust.ledger_append(nid, "payment.mismatch", "owner", {"order_id": order_id, "utr": utr, "amount_paise": int(amount_paise),
                                                                "payee_vpa": payee_vpa, "problems": problems})
        return {"status": "mismatch", "order_id": order_id, "problems": problems, "reason": ", ".join(problems)}
    store.update_order(order_id, status="payment_claimed", payment_status="claimed", utr=utr, claimed_at=store.iso())
    try:
        trust.mark_mandate(pm.mandate_id, "consumed")
    except Exception:
        log.exception("mark payment mandate failed")
    trust.ledger_append(nid, "payment.claimed", "owner", {"order_id": order_id, "utr": utr, "amount_paise": int(amount_paise),
                                                           "payment_mandate_id": pm.mandate_id, "bank_verified": False})
    return {"status": "claimed", "order_id": order_id, "utr": utr, "bank_verified": False, "note": CLAIM_NOTE}


def cancel(order_id: str) -> dict:
    o = store.order(order_id)
    if o is None:
        return {"status": "not_found"}
    if o["status"] != "cooling_off" or payment_status(o) == "claimed" or store.iso() > o["cooling_off_until"]:
        return {"status": o["status"], "error": "cancel only during cooling-off"}
    store.update_order(order_id, status="cancelled", payment_status="cancelled")
    if o.get("payment_mandate_id"):
        try:
            trust.mark_mandate(o["payment_mandate_id"], "revoked")  # the UPI request is void once the order is cancelled
        except Exception:
            log.exception("revoke payment mandate failed")
    trust.ledger_append(o["negotiation_id"], "order.cancelled", "owner", {"order_id": order_id,
                                                                         "payment_mandate_revoked": o.get("payment_mandate_id")})
    return {"status": "cancelled", "order_id": order_id}
