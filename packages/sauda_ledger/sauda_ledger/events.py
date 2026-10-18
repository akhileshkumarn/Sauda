"""Append-only, hash-chained, KMS-signed ledger: ledger_events/{negotiation_id}_{seq:06d}."""
from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sauda_trust import kms, settings
from sauda_trust.mandates import canonical, sha256_hex

COLLECTION = "ledger_events"
HEADS = "ledger_heads"  # ledger_heads/{negotiation_id}: KMS-signed {count, last_hash} (tail-truncation check)
SIG_VERSION = 2

EVENT_TYPES = (
    "mandate.signed", "rfq.sent", "offer.received", "guard.verdict", "gate.decision", "counter.sent",
    "cart.assembled", "confirmation.requested", "confirmation.answered", "order.placed",
    "payment_mandate.issued", "mandate.revoked", "attack.tested",
    "payment.claimed", "payment.settled", "payment.mismatch", "offer.unparseable", "order.cancelled", "attack.scenario",
)


class Event(BaseModel):
    seq: int
    ts: str
    negotiation_id: str
    type: str
    actor: str
    payload: dict
    payload_hash: str
    prev_hash: str
    signature: str  # v2: ECDSA over sig_digest_v2(...); v1 (legacy): over sha256(payload_hash + prev_hash)
    key_version: str = ""
    sig_version: int = 1  # absent on legacy events -> 1


def genesis_hash(negotiation_id: str) -> str:
    return sha256_hex(negotiation_id.encode())


def link_digest(payload_hash: str, prev_hash: str) -> bytes:
    """v1 (legacy) signature scope: payload and link only; type/actor/ts/seq were not signed."""
    return hashlib.sha256((payload_hash + prev_hash).encode()).digest()


def sig_digest_v2(seq: int, ts: str, negotiation_id: str, type: str, actor: str, payload_hash: str, prev_hash: str) -> bytes:
    """v2 signature scope: every field of the event except the signature itself."""
    return hashlib.sha256(canonical({"v": 2, "seq": seq, "ts": ts, "negotiation_id": negotiation_id, "type": type,
                                     "actor": actor, "payload_hash": payload_hash, "prev_hash": prev_hash})).digest()


def head_digest(negotiation_id: str, count: int, last_hash: str) -> bytes:
    return hashlib.sha256(canonical({"v": 1, "negotiation_id": negotiation_id, "count": count, "last_hash": last_hash})).digest()


def build_head(negotiation_id: str, count: int, last_hash: str, signer: kms.Signer | None = None) -> dict:
    s = signer or kms.get_signer()
    return {"negotiation_id": negotiation_id, "count": count, "last_hash": last_hash,
            "sig": kms.b64(s.sign(head_digest(negotiation_id, count, last_hash))), "key_version": s.key_version(),
            "updated_at": datetime.now(UTC).isoformat()}


def doc_id(negotiation_id: str, seq: int) -> str:
    return f"{negotiation_id}_{seq:06d}"


def normalize_payload(payload: Any) -> dict:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    elif hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    return json.loads(json.dumps(payload, default=str))


def build_event(negotiation_id: str, seq: int, prev_hash: str, type: str, actor: str, payload: dict,
                signer: kms.Signer | None = None, ts: str | None = None) -> Event:
    """Pure (apart from signing): compute hashes and signature for the next event."""
    payload = normalize_payload(payload)
    ph = sha256_hex(canonical(payload))
    s = signer or kms.get_signer()
    ts = ts or datetime.now(UTC).isoformat()
    sig = s.sign(sig_digest_v2(seq, ts, negotiation_id, type, actor, ph, prev_hash))
    return Event(seq=seq, ts=ts, negotiation_id=negotiation_id,
                 type=type, actor=actor, payload=payload, payload_hash=ph, prev_hash=prev_hash,
                 signature=kms.b64(sig), key_version=s.key_version(), sig_version=SIG_VERSION)


def _range_query(db, negotiation_id: str, descending: bool):
    from google.cloud import firestore
    from google.cloud.firestore_v1.base_query import FieldFilter
    from google.cloud.firestore_v1.field_path import FieldPath

    col = db.collection(COLLECTION)
    q = (col.where(filter=FieldFilter(FieldPath.document_id(), ">=", col.document(doc_id(negotiation_id, 0))))
            .where(filter=FieldFilter(FieldPath.document_id(), "<=", col.document(doc_id(negotiation_id, 999999))))
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING if descending else firestore.Query.ASCENDING))
    return q


def append(negotiation_id: str, type: str, actor: str, payload: dict, db=None) -> Event:
    """Firestore transaction: read last event -> seq+1, prev_hash = last payload_hash; sign; create doc."""
    from google.cloud import firestore

    db = db or settings.firestore_client()
    payload = normalize_payload(payload)
    # ascending doc-id range needs no composite index; chains are short (tens of events)
    q = _range_query(db, negotiation_id, descending=False)

    @firestore.transactional
    def _txn(tx) -> Event:
        last = [d.to_dict() for d in q.stream(transaction=tx)][-1:]
        if last:
            seq, prev = int(last[0]["seq"]) + 1, last[0]["payload_hash"]
        else:
            seq, prev = 1, genesis_hash(negotiation_id)
        ev = build_event(negotiation_id, seq, prev, type, actor, payload)
        tx.create(db.collection(COLLECTION).document(doc_id(negotiation_id, seq)), ev.model_dump())
        tx.set(db.collection(HEADS).document(negotiation_id), build_head(negotiation_id, seq, ev.payload_hash))
        return ev

    return _txn(db.transaction())


def get_head(negotiation_id: str, db=None) -> dict | None:
    db = db or settings.firestore_client()
    snap = db.collection(HEADS).document(negotiation_id).get()
    return snap.to_dict() if snap.exists else None


def list_events(negotiation_id: str, db=None) -> list[dict]:
    db = db or settings.firestore_client()
    return [d.to_dict() for d in _range_query(db, negotiation_id, descending=False).stream()]
