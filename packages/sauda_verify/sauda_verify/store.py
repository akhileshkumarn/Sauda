"""Firestore access for the Trust Network collections (tn_* only).

The client comes from sauda_trust.settings so tests can inject the in-memory double. Writes that race
(business edits, relationship transitions, review decisions) use compare-and-set on a `version` field.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

BUSINESSES = "tn_businesses"
CHECKS = "tn_checks"
CASES = "tn_cases"
EVIDENCE = "tn_evidence"
REVIEWS = "tn_reviews"
RELATIONSHIPS = "tn_relationships"
INVITATIONS = "tn_invitations"
ALL_COLLECTIONS = (BUSINESSES, CHECKS, CASES, EVIDENCE, REVIEWS, RELATIONSHIPS, INVITATIONS)


class VersionConflict(Exception):
    def __init__(self, current: dict | None):
        super().__init__("version_conflict")
        self.current = current


def db():
    from sauda_trust import settings as ts

    return ts.firestore_client()


def now() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime | None = None) -> str:
    return (dt or now()).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def sha256_hex(b: bytes | str) -> str:
    return hashlib.sha256(b.encode() if isinstance(b, str) else b).hexdigest()


def stable_hash(obj: Any) -> str:
    return sha256_hex(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str))


def keyed_hash(value: str, purpose: str) -> str:
    """HMAC of a contact/identifier: a plain hash of a phone number is brute-forceable. The key derives from
    an existing server secret, so no new secret is introduced."""
    key = hashlib.sha256((os.environ.get("DEMO_OWNER_TOKEN", "") + purpose).encode()).digest()
    return hmac.new(key, value.strip().lower().encode(), hashlib.sha256).hexdigest()


# ---------------------------------------------------------------- masking
EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+\-]{1,64})@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?91[\s\-]?)?([6-9]\d{4})[\s\-]?(\d{5})(?!\d)")


def mask_email(e: str) -> str:
    m = EMAIL_RE.fullmatch(e.strip())
    if not m:
        return e
    local, dom = m.group(1), m.group(2)
    return f"{local[:1]}••••@{dom}"


def mask_phone(p: str) -> str:
    digits = re.sub(r"\D", "", p)
    if len(digits) < 10:
        return "••••"
    return f"••••••{digits[-4:]}"


def mask_text(s: str) -> str:
    s = EMAIL_RE.sub(lambda m: mask_email(m.group(0)), s)
    return PHONE_RE.sub(lambda m: mask_phone(m.group(0)), s)


def mask_deep(v):
    if isinstance(v, dict):
        return {k: mask_deep(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [mask_deep(x) for x in v]
    if isinstance(v, str):
        return mask_text(v)
    return v


def normalize_contact(c: str) -> tuple[str, str]:
    """-> (kind, normalized). Emails lowercased; Indian mobiles reduced to 10 digits."""
    c = (c or "").strip()
    if "@" in c:
        return "email", c.lower()
    digits = re.sub(r"\D", "", c)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    return "phone", digits


def mask_contact(kind: str, norm: str) -> str:
    return mask_email(norm) if kind == "email" else mask_phone(norm)


# ---------------------------------------------------------------- generic doc helpers
def get(coll: str, doc_id: str) -> dict | None:
    if not doc_id:
        return None
    snap = db().collection(coll).document(doc_id).get()
    return snap.to_dict() if snap.exists else None


def put(coll: str, doc_id: str, doc: dict) -> dict:
    db().collection(coll).document(doc_id).set(doc)
    return doc


def create(coll: str, doc_id: str, doc: dict) -> bool:
    """Create only if absent. False when the document already exists (idempotency key hit)."""
    try:
        db().collection(coll).document(doc_id).create(doc)
        return True
    except Exception as e:  # AlreadyExists (google) or Conflict (test double)
        if type(e).__name__ in ("AlreadyExists", "Conflict", "Conflict409"):
            return False
        raise


def update(coll: str, doc_id: str, fields: dict) -> None:
    db().collection(coll).document(doc_id).update(fields)


def delete(coll: str, doc_id: str) -> None:
    ref = db().collection(coll).document(doc_id)
    if hasattr(ref, "delete"):
        ref.delete()
    else:  # in-memory double
        client = db()
        with client.lock:
            client.data.get(coll, {}).pop(doc_id, None)


def where(coll: str, field: str, value) -> list[dict]:
    return [s.to_dict() for s in db().collection(coll).where(field, "==", value).stream()]


def where_in_array(coll: str, field: str, value) -> list[dict]:
    """Array membership. Uses array_contains on Firestore; the in-memory double has only equality filters."""
    client = db()
    if hasattr(client, "replace_if"):
        return [d for d in client.data.get(coll, {}).values() if value in (d.get(field) or [])]
    from google.cloud.firestore_v1.base_query import FieldFilter

    return [s.to_dict() for s in client.collection(coll).where(filter=FieldFilter(field, "array_contains", value)).stream()]


def all_docs(coll: str, limit: int = 500) -> list[dict]:
    return [s.to_dict() for s in db().collection(coll).limit(limit).stream()]


def cas_replace(coll: str, doc_id: str, expected_version: int, doc: dict) -> dict:
    """Replace the document only if its version is still expected_version; bumps version. Raises VersionConflict."""
    doc = {**doc, "version": int(expected_version) + 1, "updated_at": iso()}
    client = db()
    if hasattr(client, "replace_if"):
        ok = client.replace_if(coll, doc_id, "version", expected_version, doc)
    else:
        from google.cloud import firestore

        ref = client.collection(coll).document(doc_id)

        @firestore.transactional
        def _txn(tx) -> bool:
            snap = ref.get(transaction=tx)
            if not snap.exists or (snap.to_dict() or {}).get("version") != expected_version:
                return False
            tx.set(ref, doc)
            return True

        ok = _txn(client.transaction())
    if not ok:
        raise VersionConflict(get(coll, doc_id))
    return doc


def mutate(coll: str, doc_id: str, fn, retries: int = 4) -> dict:
    """Read-modify-write with optimistic retries; fn(doc) -> new doc (or raises)."""
    for _ in range(retries):
        cur = get(coll, doc_id)
        if cur is None:
            raise KeyError(doc_id)
        new = fn(dict(cur))
        try:
            return cas_replace(coll, doc_id, int(cur.get("version", 1)), new)
        except VersionConflict:
            continue
    raise VersionConflict(get(coll, doc_id))


# ---------------------------------------------------------------- domain queries
def business(bid: str) -> dict | None:
    return get(BUSINESSES, bid)


def businesses_of(uid: str) -> list[dict]:
    return where_in_array(BUSINESSES, "members", uid)


def checks_of(bid: str) -> list[dict]:
    return sorted(where(CHECKS, "business_id", bid), key=lambda c: c.get("checked_at") or "")


def evidence_of(bid: str) -> list[dict]:
    return where(EVIDENCE, "bid", bid)


def relationships_of(bid: str) -> list[dict]:
    seen, out = set(), []
    for r in where(RELATIONSHIPS, "buyer_bid", bid) + where(RELATIONSHIPS, "seller_bid", bid):
        if r["rid"] not in seen:
            seen.add(r["rid"])
            out.append(r)
    return out


def normalize_gstin(g: str | None) -> str | None:
    if not g:
        return None
    g = re.sub(r"\s", "", g).upper()
    return g or None


def normalize_name(n: str | None) -> str:
    n = (n or "").lower()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    stop = {"m", "s", "ms", "the", "and", "&", "pvt", "ltd", "private", "limited", "llp", "co", "company"}
    return " ".join(w for w in n.split() if w not in stop)


def duplicate_candidates(gstin: str | None, name: str, pin: str, exclude: Iterable[str] = ()) -> list[dict]:
    exclude = set(exclude)
    out: dict[str, dict] = {}
    g = normalize_gstin(gstin)
    if g:
        for b in where(BUSINESSES, "gstin_norm", g):
            out[b["bid"]] = b
    key = f"{normalize_name(name)}|{(pin or '').strip()}"
    if normalize_name(name) and pin:
        for b in where(BUSINESSES, "name_pin_key", key):
            out[b["bid"]] = b
    return [b for k, b in out.items() if k not in exclude]
