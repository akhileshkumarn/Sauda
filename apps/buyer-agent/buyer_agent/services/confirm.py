"""Confirmation service (4.6, SM-3): pending confirmations in Firestore `confirmations`, approve/decline,
Cart Mandate signing, gate re-run, ADK resume, then orders + payment mandates (idempotent)."""
from __future__ import annotations

import asyncio
import logging

from sauda_trust import registry as _reg

from .. import store, trust

log = logging.getLogger("buyer_agent.confirm")
ALL_RULES = [f"R{i}" for i in range(1, 13)]


class ConfirmError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def request(nid: str, cart_draft_id: str, *, session_id: str | None, user_id: str | None, invocation_id: str | None = None,
            function_call_id: str | None = None, mode: str = "adk") -> dict:
    """Create (or return) the one pending confirmation for a cart draft; writes confirmation.requested."""
    from . import orders

    cart = store.cart_draft(cart_draft_id) or {}
    chash = orders.cart_hash(cart) if cart.get("allocations") else None
    existing = store.confirmation_for_cart(cart_draft_id)
    if existing and existing.get("status") == "requested" and existing.get("cart_hash") != chash:
        # the cart changed after this confirmation was issued: it can no longer be approved
        if store.claim_confirmation(existing["confirmation_id"], "requested", status="superseded"):
            trust.ledger_append(nid, "confirmation.answered", "buyer", {"confirmation_id": existing["confirmation_id"],
                                                                         "answer": "superseded", "reason": "cart_changed"})
        existing = None
    if existing and existing.get("status") in ("requested", "approving", "approved"):
        if function_call_id and existing.get("status") == "requested" and existing.get("function_call_id") != function_call_id:
            store.update_confirmation(existing["confirmation_id"], function_call_id=function_call_id,
                                      invocation_id=invocation_id, mode=mode)
            existing = store.confirmation(existing["confirmation_id"])
        return existing
    n = store.negotiation(nid)
    c = store.create_confirmation(negotiation_id=nid, cart_draft_id=cart_draft_id, shop_id=n["shop_id"],
                                  owner_uid=n.get("owner_uid"), session_id=session_id, user_id=user_id,
                                  invocation_id=invocation_id, function_call_id=function_call_id, mode=mode,
                                  cart_hash=chash)
    trust.ledger_append(nid, "confirmation.requested", "buyer", {"confirmation_id": c["confirmation_id"],
                                                                  "cart_draft_id": cart_draft_id, "mode": mode,
                                                                  "cart_hash": chash})
    store.update_negotiation(nid, status="awaiting_confirmation", confirmation_id=c["confirmation_id"])
    return c


def view(cid: str) -> dict:
    """Shape for the owner app's Confirmation type (flat), plus the full records for the trust view."""
    c = store.confirmation(cid)
    if not c:
        raise ConfirmError("not_found", "confirmation not found", 404)
    cart = store.cart_draft(c["cart_draft_id"]) or {}
    n = store.negotiation(c["negotiation_id"]) or {}
    m = trust.get_mandate(n.get("intent_mandate_id")) if n.get("intent_mandate_id") else None
    allocs = []
    for a in cart.get("allocations", []):
        rec = trust.supplier(a["supplier_id"])
        allocs.append({**a, "payee_vpa": rec.payout_vpa if rec else None,
                       "payout_vpa_masked": _reg.mask_vpa(rec.payout_vpa) if rec else None,
                       "payee_ref": _reg.payee_ref(rec.payout_vpa) if rec else None,
                       "lines": [{**l, "ceiling_as_of": l.get("ceiling_as_of") or ""} for l in a["lines"]]})
    blocked: dict[str, set] = {}
    for e in store.ledger_events(c["negotiation_id"]):
        p = e.get("payload") or {}
        if e.get("type") == "gate.decision" and p.get("supplier_id") and p.get("verdict") == "DENY":
            blocked.setdefault(p["supplier_id"], set()).update(p.get("reasons") or [])
    gate_report = n.get("pre_confirmation_gate") or cart.get("gate_report")
    return {
        "confirmation_id": cid, "negotiation_id": c["negotiation_id"], "cart_draft_id": c["cart_draft_id"],
        "status": c["status"], "expires_at": c.get("expires_at"),
        "cart": {**cart, "allocations": allocs, "budget_paise": (m.body.get("budget_paise") if m else None),
                 "blocked_suppliers": [{"supplier_id": k, "reason_codes": sorted(v)} for k, v in blocked.items()]},
        "gate_report": gate_report,
        "confirmation": c,
        "intent_mandate": m.model_dump() if m else None,
        "negotiation": {k: n.get(k) for k in ("negotiation_id", "status", "round", "supplier_ids", "stats")},
    }


def _cart_mandate_body(n: dict, cart: dict, report: dict) -> dict:
    return {
        "kind": "cart", "shop_id": n["shop_id"], "intent_mandate_id": n["intent_mandate_id"],
        "negotiation_id": n["negotiation_id"], "cart_draft_id": cart["cart_draft_id"],
        "allocations": [{"supplier_id": a["supplier_id"], "lines": [{"gtin": l["gtin"], "qty": l["qty"], "unit_price_paise": l["unit_price_paise"]} for l in a["lines"]],
                         "subtotal_paise": a["subtotal_paise"], "delivery_days": a["delivery_days"], "advance_pct": a["advance_pct"],
                         "payout_vpa": a["payout_vpa"]} for a in cart["allocations"]],
        "total_paise": cart["total_paise"], "savings_paise": cart["savings_paise"],
        "gate_report": {"verdict": report.get("verdict"), "results": [{"rule": r["rule"], "verdict": r["verdict"], "reason": r["reason"]} for r in report.get("results", [])]},
    }


async def answer(cid: str, uid: str, approved: bool) -> dict:
    """Owner's answer. The backend, not the UI, enforces it: one atomic requested->approving/declined transition
    (a second POST is 409 and can never create a second order), the confirmation is bound to the cart hash it
    was issued for, and all twelve gate rules re-run here with fresh mandate/registry/kill-switch state."""
    from ..agent import root, tools
    from . import orders

    c = store.confirmation(cid)
    if not c:
        raise ConfirmError("not_found", "confirmation not found", 404)
    if c.get("owner_uid") and c["owner_uid"] != uid:
        raise ConfirmError("forbidden", "only the mandate's owner may answer", 403)
    nid = c["negotiation_id"]
    if c["status"] != "requested":
        raise ConfirmError("already_answered", f"confirmation is {c['status']}", 409)
    if store.iso() > c["expires_at"]:
        if store.claim_confirmation(cid, "requested", status="expired"):
            trust.ledger_append(nid, "confirmation.answered", "owner", {"confirmation_id": cid, "answer": "expired"})
        raise ConfirmError("expired", "confirmation expired", 410)
    n = store.negotiation(nid) or {}
    cart = store.cart_draft(c["cart_draft_id"])
    stale = None
    if not cart or not cart.get("allocations"):
        stale = "cart_missing"
    elif not c.get("cart_hash") or orders.cart_hash(cart) != c["cart_hash"]:
        stale = "cart_changed"
    elif n.get("status") in ("cancelled", "failed", "ordered"):
        stale = f"negotiation_{n.get('status')}"
    if stale:
        if store.claim_confirmation(cid, "requested", status="stale", stale_reason=stale, answered_at=store.iso()):
            trust.ledger_append(nid, "confirmation.answered", "owner", {"confirmation_id": cid, "answer": "stale", "reason": stale})
        msg = ("the cart changed after this confirmation was issued; review the new cart" if stale == "cart_changed"
               else f"this confirmation can no longer be approved ({stale})")
        raise ConfirmError(stale, msg, 409)

    if not approved:
        if not store.claim_confirmation(cid, "requested", status="declined", answered_at=store.iso(), answered_by=uid):
            raise ConfirmError("already_answered", "confirmation was already answered", 409)
        trust.ledger_append(nid, "confirmation.answered", "owner", {"confirmation_id": cid, "answer": "declined"})
        store.update_negotiation(nid, status="cancelled", ended_at=store.iso())
        store.update_shop(n["shop_id"], active_negotiation_id=None)
        if c.get("mode") == "adk" and c.get("function_call_id"):
            fut = root.resume_confirmation(c["user_id"], c["session_id"], c["function_call_id"], False, {}, lambda _e: None)
            try:
                await asyncio.wait_for(asyncio.wrap_future(fut), 60)
            except Exception:
                log.exception("ADK resume (decline) failed")
        return {"status": "declined"}

    if not store.claim_confirmation(cid, "requested", status="approving", answered_at=store.iso(), answered_by=uid):
        raise ConfirmError("already_answered", "confirmation was already answered", 409)
    from sauda_trust.policy_gate import evaluate

    try:
        # Re-run all twelve rules before anything is signed: fresh mandate status/expiry (R1), registry (R2, R8),
        # kill switch and revocation (R12), idempotency (R11).
        bc = await asyncio.to_thread(tools.build_place_order_context, nid, c["cart_draft_id"], True)
        rep = evaluate(bc.action, bc.mandate, bc.ctx, rules=ALL_RULES)
    except Exception as e:
        log.exception("post-confirmation gate failed")
        rep = None
        err = f"{type(e).__name__}"
    if rep is None or rep.verdict == "DENY":
        d = rep.to_dict() if rep else {"verdict": "DENY", "reasons": ["GATE_ERROR"], "error": err}
        trust.ledger_append(nid, "gate.decision", "gate", {"tool": "place_order", "stage": "post_confirmation", **d})
        store.update_confirmation(cid, status="denied")
        trust.ledger_append(nid, "confirmation.answered", "owner", {"confirmation_id": cid, "answer": "approved_but_denied",
                                                                     "reasons": d.get("reasons")})
        store.update_negotiation(nid, status="failed", ended_at=store.iso())
        store.update_shop(n["shop_id"], active_negotiation_id=None)
        return {"status": "denied", "reasons": d.get("reasons", []), "gate_report": d}

    # Approve: sign the Cart Mandate on the owner's behalf (inside an authenticated request).
    pre = n.get("pre_confirmation_gate") or cart.get("gate_report") or {}
    if not n.get("cart_mandate_id"):
        try:
            cm = await asyncio.to_thread(trust.create_mandate, "cart", _cart_mandate_body(n, cart, pre), uid)
        except Exception:
            store.update_confirmation(cid, status="error")  # never left half-approved
            raise
        store.update_negotiation(nid, cart_mandate_id=cm.mandate_id, status="confirmed")
        trust.ledger_append(nid, "mandate.signed", "owner", {"mandate_id": cm.mandate_id, "kind": "cart", "body_hash": cm.body_hash,
                                                              "kms_key_version": cm.kms_key_version})
    store.update_confirmation(cid, status="approved")
    trust.ledger_append(nid, "confirmation.answered", "owner", {"confirmation_id": cid, "answer": "approved"})
    trust.ledger_append(nid, "gate.decision", "gate", {"tool": "place_order", "stage": "post_confirmation", **rep.to_dict()})

    agent_text: list[str] = []
    if c.get("mode") == "adk" and c.get("function_call_id"):
        def push(item):
            ev = item.get("adk_event")
            try:
                if ev is not None and ev.content and ev.content.parts:
                    agent_text.extend(p.text for p in ev.content.parts if getattr(p, "text", None))
            except Exception:
                pass

        fut = root.resume_confirmation(c["user_id"], c["session_id"], c["function_call_id"], True, {}, push)
        try:
            await asyncio.wait_for(asyncio.wrap_future(fut), 120)
        except Exception:
            log.exception("ADK resume failed; placing the order directly (same brokered tool)")
    # Ensure orders and payment mandates exist (idempotent; same brokered tools the agent uses).
    if not store.orders_for(nid):
        res = await asyncio.to_thread(tools.place_order, nid, c["cart_draft_id"])
        if res.get("status") == "denied":
            return {"status": "denied", "reasons": res.get("reasons", [])}
    for o in store.orders_for(nid):
        if not o.get("payment_mandate_id"):
            res = await asyncio.to_thread(tools.issue_payment_mandate, o["order_id"])
            if res.get("status") == "denied":
                log.warning("payment mandate denied for %s: %s", o["order_id"], res)
    if agent_text:
        store.update_confirmation(cid, agent_text="\n".join(agent_text)[:4000])
    return _result(nid, "approved")


def _result(nid: str, status: str) -> dict:
    os_ = store.orders_for(nid)
    pms = [o.get("payment_mandate_id") for o in os_ if o.get("payment_mandate_id")]
    return {"status": status, "order_ids": sorted(o["order_id"] for o in os_),
            "payment_mandate_id": pms[0] if len(pms) == 1 else (pms or None), "payment_mandate_ids": pms}
