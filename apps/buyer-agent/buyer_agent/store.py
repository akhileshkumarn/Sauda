"""Firestore access for negotiations, offers, cart_drafts, orders, confirmations, shops, products."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

from .deps import db, settings


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


def _get(coll: str, doc_id: str) -> dict | None:
    if not doc_id:
        return None
    snap = db().collection(coll).document(doc_id).get()
    return snap.to_dict() if snap.exists else None


def _set(coll: str, doc_id: str, data: dict, merge: bool = False) -> None:
    db().collection(coll).document(doc_id).set(data, merge=merge)


def _update(coll: str, doc_id: str, fields: dict) -> None:
    db().collection(coll).document(doc_id).set(fields, merge=True)


# ---------------------------------------------------------------- shops
def shop(shop_id: str) -> dict:
    return _get("shops", shop_id) or {"shop_id": shop_id}


def update_shop(shop_id: str, **fields) -> None:
    _update("shops", shop_id, fields)


# ---------------------------------------------------------------- products
_products_cache: dict | None = None
_products_ts = 0.0


def products() -> dict[str, dict]:
    """Product master from Firestore `products`; falls back to data/products.csv (the same file the
    supplier catalogs are built from) while the seed has not run. Cached 5 minutes."""
    global _products_cache, _products_ts
    import time

    if _products_cache and time.time() - _products_ts < 300:
        return _products_cache
    out = {}
    for d in db().collection("products").stream():
        p = d.to_dict()
        gtin = str(p.get("gtin") or d.id)
        p["gtin"] = gtin
        out[gtin] = p
    if not out:
        try:
            from sauda_data.products import load_csv

            out = {str(r["gtin"]): r for r in load_csv() if r.get("mrp_paise")}
        except Exception:
            out = {}
    if out:
        _products_cache, _products_ts = out, time.time()
    return out


# ---------------------------------------------------------------- negotiations
def create_negotiation(shop_id: str, owner_uid: str, draft: dict | None = None, nid: str | None = None) -> dict:
    nid = nid or new_id("neg")
    doc = {
        "negotiation_id": nid,
        "shop_id": shop_id,
        "owner_uid": owner_uid,
        "intent_mandate_id": None,
        "status": "created",
        "round": 0,
        "supplier_ids": [],
        "started_at": iso(),
        "ended_at": None,
        "cart_mandate_id": None,
        "cart_draft_id": None,
        "draft": draft,
    }
    _set("negotiations", nid, doc)
    return doc


def negotiation(nid: str) -> dict | None:
    return _get("negotiations", nid)


def negotiation_for_mandate(mandate_id: str) -> dict | None:
    for d in db().collection("negotiations").where("intent_mandate_id", "==", mandate_id).limit(1).stream():
        return d.to_dict()
    return None


def update_negotiation(nid: str, **fields) -> None:
    fields.setdefault("updated_at", iso())  # last activity: the per-shop owner lock goes stale after 15 min
    _update("negotiations", nid, fields)


def negotiations_for_shop(shop_id: str) -> list[dict]:
    return [d.to_dict() for d in db().collection("negotiations").where("shop_id", "==", shop_id).stream()]


# ---------------------------------------------------------------- offers
def save_offer(offer: dict) -> str:
    oid = offer.get("offer_id") or new_id("off")
    offer["offer_id"] = oid
    offer.setdefault("ts", iso())
    _set("offers", oid, offer)
    return oid


def offers_for(nid: str) -> list[dict]:
    rows = [d.to_dict() for d in db().collection("offers").where("negotiation_id", "==", nid).stream()]
    return sorted(rows, key=lambda r: (r.get("round", 0), r.get("ts", "")))


# ---------------------------------------------------------------- cart drafts
def save_cart_draft(nid: str, cart: dict) -> str:
    cid = cart.get("cart_draft_id") or f"cart_{nid}"
    cart["cart_draft_id"] = cid
    cart["negotiation_id"] = nid
    cart["created_at"] = iso()
    _set("cart_drafts", cid, cart)
    update_negotiation(nid, cart_draft_id=cid)
    return cid


def cart_draft(cid: str) -> dict | None:
    return _get("cart_drafts", cid)


# ---------------------------------------------------------------- confirmations
def create_confirmation(**fields) -> dict:
    cid = fields.get("confirmation_id") or new_id("conf")
    doc = {
        "confirmation_id": cid,
        "status": "requested",
        "created_at": iso(),
        "expires_at": iso(now() + timedelta(minutes=settings().confirmation_ttl_min)),
        **fields,
    }
    doc["confirmation_id"] = cid
    _set("confirmations", cid, doc)
    return doc


def confirmation(cid: str) -> dict | None:
    return _get("confirmations", cid)


def confirmations_for_cart(cart_draft_id: str) -> list[dict]:
    rows = [d.to_dict() for d in db().collection("confirmations").where("cart_draft_id", "==", cart_draft_id).stream()]
    return sorted(rows, key=lambda r: r.get("created_at") or "")


def confirmation_for_cart(cart_draft_id: str) -> dict | None:
    """The live confirmation for a cart draft: newest requested/approved one, else the newest of any status."""
    rows = confirmations_for_cart(cart_draft_id)
    live = [r for r in rows if r.get("status") in ("requested", "approving", "approved")]
    return (live or rows or [None])[-1]


def claim_confirmation(cid: str, expected: str, **fields) -> bool:
    """Atomic compare-and-set on confirmations/{cid}.status (Firestore transaction): True only for the one
    caller that saw status == expected. Two concurrent POST /confirm can never both proceed."""
    from google.cloud import firestore

    client = db()
    ref = client.collection("confirmations").document(cid)

    @firestore.transactional
    def _txn(tx) -> bool:
        snap = ref.get(transaction=tx)
        if not snap.exists or (snap.to_dict() or {}).get("status") != expected:
            return False
        tx.update(ref, fields)
        return True

    return _txn(client.transaction())


def update_confirmation(cid: str, **fields) -> None:
    _update("confirmations", cid, fields)


# ---------------------------------------------------------------- orders
def order(oid: str) -> dict | None:
    return _get("orders", oid)


def save_order(o: dict) -> None:
    _set("orders", o["order_id"], o)


def create_order(o: dict) -> bool:
    """Create orders/{order_id} only if it does not exist yet (Firestore create precondition). False if it does:
    a second approval can never send a second PO for the same deterministic order id."""
    try:
        db().collection("orders").document(o["order_id"]).create(o)
        return True
    except Exception as e:
        if type(e).__name__ in ("Conflict", "AlreadyExists") or "exist" in str(e).lower():
            return False
        raise


def orders_with_utr(utr: str) -> list[dict]:
    return [d.to_dict() for d in db().collection("orders").where("utr", "==", utr).stream()]


def update_order(oid: str, **fields) -> None:
    _update("orders", oid, fields)


def orders_for_shop(shop_id: str) -> list[dict]:
    return [d.to_dict() for d in db().collection("orders").where("shop_id", "==", shop_id).stream()]


def orders_for(nid: str) -> list[dict]:
    return [d.to_dict() for d in db().collection("orders").where("negotiation_id", "==", nid).stream()]


# ---------------------------------------------------------------- ledger (read only; writes go through sauda_ledger)
def ledger_events(nid: str) -> list[dict]:
    from sauda_ledger import list_events

    return sorted(list_events(nid), key=lambda r: r.get("seq", 0))
