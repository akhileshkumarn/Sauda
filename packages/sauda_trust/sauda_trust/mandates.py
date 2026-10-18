"""Mandates: canonical JSON, KMS signing/verification and the Firestore `mandates` collection."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import kms, settings

MandateKind = Literal["intent", "cart", "payment"]
MandateStatus = Literal["draft", "active", "consumed", "revoked", "expired"]
STATUSES = ("draft", "active", "consumed", "revoked", "expired")
COLLECTION = "mandates"


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def body_hash(body: dict) -> str:
    return sha256_hex(canonical(body))


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------- body models
class _Body(BaseModel):
    model_config = ConfigDict(extra="allow")


class MandateLine(_Body):
    gtin: str
    qty: int
    ceiling_paise: int
    ceiling_source: str | None = None


class IntentMandate(_Body):
    kind: Literal["intent"] = "intent"
    shop_id: str
    budget_paise: int
    allowed_supplier_ids: list[str]
    lines: list[MandateLine]
    max_advance_pct: float
    deliver_by: str  # YYYY-MM-DD
    autonomy_tier: int = 2
    expires_at: str  # ISO 8601 with offset
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    owner_uid: str | None = None
    mandate_id: str | None = Field(default=None, exclude=True)  # convenience, never part of the signed body


class AllocationLine(_Body):
    gtin: str
    qty: int
    unit_price_paise: int


class Allocation(_Body):
    supplier_id: str
    lines: list[AllocationLine]
    subtotal_paise: int
    delivery_days: int | None = None
    advance_pct: float = 0
    payout_vpa: str | None = None


class CartMandate(_Body):
    kind: Literal["cart"] = "cart"
    shop_id: str
    intent_mandate_id: str
    allocations: list[Allocation]
    total_paise: int
    savings_paise: int = 0
    gate_report: dict = Field(default_factory=dict)
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    owner_uid: str | None = None


class PaymentMandate(_Body):
    kind: Literal["payment"] = "payment"
    shop_id: str
    cart_mandate_id: str
    cart_hash: str
    amount_paise: int
    payee_vpa: str  # must equal suppliers.payout_vpa (R8)
    method: Literal["upi"] = "upi"
    cooling_off_until: str
    supplier_id: str | None = None
    order_id: str | None = None
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    owner_uid: str | None = None


# ---------------------------------------------------------------- signing
class Signed(BaseModel):
    body_hash: str
    signature: str  # base64 DER ECDSA
    key_version: str


def _digest(body: dict) -> tuple[str, bytes]:
    c = canonical(body)
    return sha256_hex(c), hashlib.sha256(c).digest()


def sign(body: dict) -> Signed:
    """Sign sha256(canonical(body)) with the active signer (KMS by default). KMS errors propagate."""
    h, d = _digest(body)
    signer = kms.get_signer()
    return Signed(body_hash=h, signature=kms.b64(signer.sign(d)), key_version=signer.key_version())


def _signer_for(version: str):
    s = kms.get_signer()
    if s.key_version() == version:
        return s
    if isinstance(s, kms.KmsSigner):
        return kms.KmsSigner(version=version)
    return s


def verify(body: dict, sig: Signed | dict) -> bool:
    try:
        sig = sig if isinstance(sig, Signed) else Signed(**sig)
        h, d = _digest(body)
        if h != sig.body_hash:
            return False
        signer = _signer_for(sig.key_version)
        return kms.verify_digest(d, kms.unb64(sig.signature), signer.public_key_pem())
    except Exception:
        return False


# ---------------------------------------------------------------- Firestore records
class Mandate(BaseModel):
    mandate_id: str
    kind: MandateKind
    shop_id: str
    parent_mandate_id: str | None = None
    owner_uid: str | None = None
    body: dict
    body_hash: str
    signature: str
    kms_key_version: str
    status: MandateStatus = "active"
    created_at: str
    expires_at: str | None = None

    @property
    def signed(self) -> Signed:
        return Signed(body_hash=self.body_hash, signature=self.signature, key_version=self.kms_key_version)

    def signature_valid(self) -> bool:
        return verify(self.body, self.signed)

    def intent(self) -> IntentMandate:
        m = IntentMandate(**self.body)
        m.mandate_id = self.mandate_id
        return m


def _body_dict(body: Any) -> dict:
    if isinstance(body, BaseModel):
        return body.model_dump(mode="json", exclude_none=False)
    return json.loads(json.dumps(body, default=str))


def build(kind: MandateKind, body: Any, owner_uid: str, mandate_id: str | None = None) -> Mandate:
    """Sign a body and build the Mandate record (no Firestore write)."""
    b = _body_dict(body)
    b["kind"] = kind
    if not b.get("owner_uid"):
        b["owner_uid"] = owner_uid
    if not b.get("nonce"):
        b["nonce"] = uuid.uuid4().hex
    model = {"intent": IntentMandate, "cart": CartMandate, "payment": PaymentMandate}[kind]
    model(**b)  # validate shape
    s = sign(b)
    parent = b.get("intent_mandate_id") if kind == "cart" else b.get("cart_mandate_id") if kind == "payment" else None
    return Mandate(
        mandate_id=mandate_id or f"{kind}_{uuid.uuid4().hex[:16]}",
        kind=kind,
        shop_id=b["shop_id"],
        parent_mandate_id=parent,
        owner_uid=owner_uid,
        body=b,
        body_hash=s.body_hash,
        signature=s.signature,
        kms_key_version=s.key_version,
        status="active",
        created_at=now_utc_iso(),
        expires_at=b.get("expires_at") or b.get("cooling_off_until"),
    )


def create(kind: MandateKind, body: Any, owner_uid: str, mandate_id: str | None = None, db=None) -> Mandate:
    """Sign and persist to mandates/{mandate_id}. Call only inside a request with a verified owner token."""
    m = build(kind, body, owner_uid, mandate_id)
    (db or settings.firestore_client()).collection(COLLECTION).document(m.mandate_id).create(m.model_dump())
    return m


def get(mandate_id: str, db=None) -> Mandate | None:
    snap = (db or settings.firestore_client()).collection(COLLECTION).document(mandate_id).get()
    return Mandate(**snap.to_dict()) if snap.exists else None


def mark(mandate_id: str, status: MandateStatus, db=None) -> None:
    if status not in STATUSES:
        raise ValueError(f"bad mandate status {status!r}")
    (db or settings.firestore_client()).collection(COLLECTION).document(mandate_id).update(
        {"status": status, "status_changed_at": now_utc_iso()}
    )
