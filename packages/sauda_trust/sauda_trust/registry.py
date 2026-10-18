"""Supplier registry (`suppliers` collection). Identity is the registry record, never the agent's self-description."""
from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict

from . import settings
from .mandates import canonical, now_utc_iso, sha256_hex

log = logging.getLogger(__name__)
COLLECTION = "suppliers"


class Supplier(BaseModel):
    model_config = ConfigDict(extra="allow")
    supplier_id: str
    name: str
    agent_card_url: str
    fingerprint: str
    payout_vpa: str
    payout_account_hash: str | None = None
    status: Literal["allowlisted", "quarantined"] = "allowlisted"
    reputation_score: float | None = None


def card_fingerprint(card: dict) -> str:
    return sha256_hex(canonical(card))


def get_supplier(supplier_id: str, db=None) -> Supplier | None:
    snap = (db or settings.firestore_client()).collection(COLLECTION).document(supplier_id).get()
    return Supplier(**snap.to_dict()) if snap.exists else None


def upsert_supplier(supplier: Supplier | dict, db=None) -> Supplier:
    s = supplier if isinstance(supplier, Supplier) else Supplier(**supplier)
    (db or settings.firestore_client()).collection(COLLECTION).document(s.supplier_id).set(s.model_dump(), merge=True)
    return s


def verify_card(supplier_id: str, card: dict, *, quarantine_on_mismatch: bool = False, db=None) -> bool:
    """True iff the supplier is allowlisted and sha256(canonical(card)) equals the registered fingerprint."""
    try:
        s = get_supplier(supplier_id, db=db)
        if s is None or s.status != "allowlisted":
            return False
        ok = card_fingerprint(card) == s.fingerprint
        if not ok and quarantine_on_mismatch:
            quarantine(supplier_id, "CARD_FINGERPRINT_CHANGED", db=db)
        return ok
    except Exception:
        log.exception("verify_card failed for %s", supplier_id)
        return False  # fail closed


def quarantine(supplier_id: str, reason: str, negotiation_id: str | None = None, db=None) -> None:
    (db or settings.firestore_client()).collection(COLLECTION).document(supplier_id).set(
        {"status": "quarantined", "quarantine_reason": reason, "quarantined_at": now_utc_iso()}, merge=True
    )
    if negotiation_id:
        from sauda_ledger import append  # lazy: sauda_ledger depends on sauda_trust

        append(negotiation_id, "supplier.quarantined", "registry", {"supplier_id": supplier_id, "reason": reason})


# ---------------------------------------------------------------- payee masking for public outputs
import hashlib as _hashlib  # noqa: E402
import hmac as _hmac  # noqa: E402
import os as _os  # noqa: E402
import re as _re  # noqa: E402

VPA_RE = _re.compile(r"\b([\w.\-]{2,64})@([a-zA-Z][a-zA-Z0-9]{1,31})\b")
VPA_KEYS = ("payout_vpa", "payee_vpa", "claimed", "registered", "payee")


def mask_vpa(vpa: str | None) -> str | None:
    """'7912345357@ybl' -> '79••••357@ybl' (first 2 and last 3 of the local part, then @handle)."""
    if not vpa or "@" not in str(vpa):
        return vpa
    local, handle = str(vpa).rsplit("@", 1)
    if len(local) <= 5:
        return f"{local[:1]}••••@{handle}"
    return f"{local[:2]}••••{local[-3:]}@{handle}"


def payee_ref(vpa: str | None) -> str | None:
    """Keyed reference to a payee: HMAC-SHA256 (a plain hash of a 10-digit phone VPA is brute-forceable).
    Key = sha256(DEMO_OWNER_TOKEN + 'payee'): an existing server-side secret, no new one needed."""
    if not vpa:
        return None
    key = _hashlib.sha256((_os.environ.get("DEMO_OWNER_TOKEN", "") + "payee").encode()).digest()
    return _hmac.new(key, str(vpa).strip().lower().encode(), _hashlib.sha256).hexdigest()


def mask_payload(v):
    """Copy of v safe for public outputs: VPA-valued keys become <key>_masked + payee_ref (or <key>_ref), and
    VPAs inside free text are masked. Applied when ledger events are WRITTEN (so the hash covers the masked
    payload and /events stays byte-identical) and to public responses; never at read time of hashed data."""
    if isinstance(v, dict):
        out = {}
        for k, x in v.items():
            if k in VPA_KEYS and isinstance(x, str) and "@" in x:
                out[f"{k}_masked"] = mask_vpa(x)
                out["payee_ref" if k in ("payout_vpa", "payee_vpa", "payee") else f"{k}_ref"] = payee_ref(x)
            else:
                out[k] = mask_payload(x)
        return out
    if isinstance(v, (list, tuple)):
        return [mask_payload(x) for x in v]
    if isinstance(v, str) and "@" in v:
        return VPA_RE.sub(lambda m: mask_vpa(m.group(0)), v)
    return v
