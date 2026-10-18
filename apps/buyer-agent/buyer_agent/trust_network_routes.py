"""Trust Network routes: business verification, invitations, relationships and the review queue.

Access rules
- Members of a business read and edit it in full.
- A counterparty (a business with a non-declined relationship) reads only the redacted profile.
- Reviewers (REVIEWER_UIDS / REVIEWER_EMAILS, or the operator token) read everything and decide review tasks.
- The operator token may act as a fixture user (X-Act-As: fx-user-...) so the demo journey can be exercised
  with several identities; it never acts as a real user.
Unknown or inaccessible ids return 404 so existence is not leaked.
"""
from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from sauda_verify import policy
from sauda_verify import store as tn
from sauda_verify.models import (
    Business,
    Check,
    CheckStatus,
    Dim,
    FieldCompare,
    RelState,
    ReviewerStamp,
    SourceKind,
)

from .deps import settings

log = logging.getLogger("buyer_agent.tn")
router = APIRouter()

INVITE_TTL_DAYS = 14
EVIDENCE_RETENTION_DAYS = 365
MAX_EVIDENCE_BYTES = 8 * 1024 * 1024
EVIDENCE_MIME = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
ACT_AS_RE = re.compile(r"^fx-user-[a-z0-9_\-]{1,40}$")


# ---------------------------------------------------------------- identity
@dataclass
class Viewer:
    uid: str
    is_reviewer: bool = False
    is_operator: bool = False

    @property
    def is_fixture_user(self) -> bool:
        return self.uid.startswith("fx-user-")


def _firebase_email(token: str) -> str | None:
    from firebase_admin import auth as fb_auth

    from .main import _verify_firebase

    _verify_firebase(token)  # initialises the app and validates the token
    return (fb_auth.verify_id_token(token) or {}).get("email")


def viewer(authorization: str | None = Header(default=None), x_act_as: str | None = Header(default=None)) -> Viewer:
    from .main import owner_uid

    uid = owner_uid(authorization)
    token = authorization.split(" ", 1)[1].strip() if authorization else ""
    op_token = settings().demo_owner_token
    is_op = bool(op_token) and secrets.compare_digest(token, op_token)
    if x_act_as:
        if not is_op or not ACT_AS_RE.match(x_act_as):
            raise HTTPException(403, "X-Act-As is only for the operator token and fixture users")
        return Viewer(uid=x_act_as)
    if is_op:
        return Viewer(uid=uid, is_reviewer=True, is_operator=True)
    rev = uid in settings().reviewer_uids
    if not rev and settings().reviewer_emails and settings().auth_mode == "firebase":
        try:
            rev = (_firebase_email(token) or "").lower() in settings().reviewer_emails
        except Exception:
            rev = False
    return Viewer(uid=uid, is_reviewer=rev)


def reviewer(v: Viewer = Depends(viewer)) -> Viewer:
    if not v.is_reviewer:
        raise HTTPException(403, "reviewers only")
    return v


def operator(v: Viewer = Depends(viewer)) -> Viewer:
    if not v.is_operator:
        raise HTTPException(403, "operator only")
    return v


def uid_hash(uid: str) -> str:
    return tn.keyed_hash(uid, "uid")[:16]


def _err(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "message": message, **extra,
                                                     "detail": {"code": code, "message": message, **extra}})


# ---------------------------------------------------------------- ledger
def ledger(bid: str, type_: str, actor: str, payload: dict) -> None:
    from . import trust

    try:
        trust.ledger_append(f"biz-{bid}", type_, actor, tn.mask_deep(payload))
    except Exception:
        log.exception("ledger append %s failed for %s", type_, bid)


# ---------------------------------------------------------------- business helpers
def _member(b: dict, v: Viewer) -> bool:
    return v.uid in (b.get("members") or [])


def _biz_or_404(bid: str) -> dict:
    b = tn.business(bid)
    if not b:
        raise HTTPException(404, "business not found")
    return b


def _require_member(bid: str, v: Viewer, allow_reviewer: bool = True) -> dict:
    b = _biz_or_404(bid)
    if _member(b, v) or (allow_reviewer and v.is_reviewer):
        return b
    raise HTTPException(404, "business not found")


def _model(b: dict) -> Business:
    return Business.model_validate(b)


def _checks(bid: str) -> list[Check]:
    out = []
    for c in tn.checks_of(bid):
        try:
            out.append(Check.model_validate(c))
        except ValidationError:
            log.warning("skipping malformed check %s", c.get("check_id"))
    return out


def summary_of(b: dict) -> dict:
    checks = _checks(b["bid"])
    ev = tn.evidence_of(b["bid"])
    s = policy.summarize(checks, _model(b), evidence=ev)
    d = s.model_dump(mode="json")
    d["review_reason_text"] = policy.reason_text(s.review_reasons)
    return d


def _mask_gstin(g: str | None) -> str | None:
    if not g:
        return None
    return f"{g[:2]}••••••{g[-3:]}" if len(g) >= 6 else "••••"


def redacted_profile(b: dict) -> dict:
    s = summary_of(b)
    addr = b.get("address") or {}
    pin = str(addr.get("pin") or "")
    return {
        "bid": b["bid"],
        "display_name": b.get("display_name"),
        "roles": b.get("roles", []),
        "category": b.get("category"),
        "products": b.get("products", []),
        "constitution": b.get("constitution"),
        "city": addr.get("city"),
        "state": addr.get("state"),
        "pin_prefix": (pin[:3] + "xxx") if len(pin) >= 3 else None,
        "gstin_masked": _mask_gstin(b.get("gstin")),
        "representative": {"role": (b.get("representative") or {}).get("role"),
                           "authority_status": (b.get("representative") or {}).get("authority_status")},
        "brand_claims": b.get("brand_claims", []),
        "is_fixture": bool(b.get("is_fixture")),
        "verification": {
            "category": s["category"], "category_label": s["category_label"],
            "dimensions": [{k: d[k] for k in ("dim", "status", "source_kind", "checked_at")} for d in s["dimensions"]],
            "outstanding_count": len(s["outstanding"]),
            "limitations": s["limitations"],
        },
        "redacted": True,
    }


def _public_dupe(b: dict) -> dict:
    addr = b.get("address") or {}
    return {"bid": b["bid"], "display_name": b.get("display_name"), "city": addr.get("city"),
            "gstin_masked": _mask_gstin(b.get("gstin"))}


def _index_fields(doc: dict) -> dict:
    addr = doc.get("address") or {}
    doc["gstin_norm"] = tn.normalize_gstin(doc.get("gstin"))
    doc["gstin"] = doc["gstin_norm"]
    name = doc.get("legal_name") or doc.get("display_name") or ""
    doc["name_pin_key"] = f"{tn.normalize_name(name)}|{str(addr.get('pin') or '').strip()}"
    return doc


def _public_business(b: dict) -> dict:
    return {k: v for k, v in b.items() if k not in ("contact_hash", "contact_hashes", "gstin_norm", "name_pin_key")}


# ---------------------------------------------------------------- business models
class AddressIn(BaseModel):
    line: str = Field("", max_length=200)
    city: str = Field("", max_length=80)
    state: str = Field("", max_length=80)
    pin: str = Field("", pattern=r"^(\d{6})?$")


class RepIn(BaseModel):
    name: str = Field("", max_length=120)
    role: str = Field("", max_length=60)


class BusinessIn(BaseModel):
    roles: list[Literal["buyer", "seller"]] = Field(min_length=1)
    display_name: str = Field(min_length=1, max_length=120)
    legal_name: str | None = Field(None, max_length=160)
    constitution: str | None = Field(None, max_length=60)
    category: str | None = Field(None, max_length=80)
    products: list[str] = Field(default_factory=list, max_length=30)
    gstin: str | None = Field(None, max_length=20)
    udyam: str | None = Field(None, max_length=30)
    fssai: str | None = Field(None, max_length=20)
    cin_llpin: str | None = Field(None, max_length=30)
    address: AddressIn = Field(default_factory=AddressIn)
    phone: str | None = Field(None, max_length=20)
    email: str | None = Field(None, max_length=120)
    representative: RepIn = Field(default_factory=RepIn)
    brand_claims: list[str] = Field(default_factory=list, max_length=20)
    requirements: dict[str, list[str]] | None = None
    confirm_not_duplicate: bool = False


class BusinessPatch(BaseModel):
    version: int
    display_name: str | None = Field(None, min_length=1, max_length=120)
    legal_name: str | None = Field(None, max_length=160)
    constitution: str | None = None
    category: str | None = None
    products: list[str] | None = None
    gstin: str | None = None
    udyam: str | None = None
    fssai: str | None = None
    cin_llpin: str | None = None
    address: AddressIn | None = None
    representative: RepIn | None = None
    brand_claims: list[str] | None = None
    requirements: dict[str, list[str]] | None = None
    roles: list[Literal["buyer", "seller"]] | None = None


def _contact_hashes(phone: str | None, email: str | None) -> dict:
    """Keyed hash per declared contact kind, so a later contact OTP can be compared without the raw value."""
    out = {}
    for raw in (phone, email):
        if raw:
            k, n = tn.normalize_contact(raw)
            out[k] = tn.keyed_hash(n, "contact")
    return out


def _contact(phone: str | None, email: str | None) -> tuple[dict, str | None]:
    out, hashes = {}, []
    if phone:
        k, n = tn.normalize_contact(phone)
        out["phone_masked"] = tn.mask_contact(k, n)
        hashes.append(tn.keyed_hash(n, "contact"))
    if email:
        k, n = tn.normalize_contact(email)
        out["email_masked"] = tn.mask_contact(k, n)
        hashes.append(tn.keyed_hash(n, "contact"))
    return out, (hashes[0] if hashes else None)


def _validate_requirements(req: dict[str, list[str]] | None) -> None:
    if req is None:
        return
    valid = {d.value for d in Dim} | {"human_review"}
    for tier, items in req.items():
        bad = [i for i in items if i not in valid]
        if bad:
            raise HTTPException(422, f"unknown requirement(s) in tier {tier}: {bad}")


def create_business_doc(body: BusinessIn, v: Viewer, *, bid: str | None = None, is_fixture: bool | None = None) -> dict:
    fixture = v.is_fixture_user if is_fixture is None else is_fixture
    bid = bid or (tn.new_id("fx_biz") if fixture else tn.new_id("biz"))
    contact, chash = _contact(body.phone, body.email)
    now = tn.iso()
    rep = body.representative.model_dump()
    rep["authority_status"] = "self_declared" if rep.get("name") else "unknown"
    doc = {
        "bid": bid, "roles": body.roles, "display_name": body.display_name.strip(), "legal_name": body.legal_name,
        "constitution": body.constitution, "category": body.category, "products": body.products,
        "gstin": body.gstin, "udyam": body.udyam, "fssai": body.fssai, "cin_llpin": body.cin_llpin,
        "address": body.address.model_dump(), "geo": None, "contact": contact, "contact_hash": chash,
        "contact_hashes": _contact_hashes(body.phone, body.email),
        "representative": rep, "brand_claims": body.brand_claims, "requirements": body.requirements,
        "owner_uid": v.uid, "members": [v.uid], "is_fixture": fixture, "created_at": now, "updated_at": now, "version": 1,
    }
    return _index_fields(doc)


# ---------------------------------------------------------------- business routes
@router.post("/tn/businesses")
def create_business(body: BusinessIn, v: Viewer = Depends(viewer)):
    _validate_requirements(body.requirements)
    doc = create_business_doc(body, v)
    if not body.confirm_not_duplicate:
        dupes = tn.duplicate_candidates(doc["gstin"], doc.get("legal_name") or doc["display_name"], doc["address"]["pin"])
        if dupes:
            return _err(409, "possible_duplicate", "A business with the same GSTIN or name and PIN is already registered.",
                        candidates=[_public_dupe(b) for b in dupes[:5]])
    elif doc["gstin"] and tn.where(tn.BUSINESSES, "gstin_norm", doc["gstin"]):
        # the same GSTIN can only be claimed once; a second claim goes to review instead
        return _err(409, "gstin_already_registered", "This GSTIN is already registered. Ask a member to invite you, or contact a reviewer.")
    tn.create(tn.BUSINESSES, doc["bid"], doc)
    ledger(doc["bid"], "tn.business.created", uid_hash(v.uid),
           {"bid": doc["bid"], "roles": doc["roles"], "display_name": doc["display_name"], "is_fixture": doc["is_fixture"]})
    return _public_business(doc)


@router.get("/tn/businesses/mine")
def my_businesses(v: Viewer = Depends(viewer)):
    out = []
    for b in tn.businesses_of(v.uid):
        out.append({**_public_business(b), "summary": summary_of(b)})
    return out


@router.get("/tn/businesses/{bid}")
def get_business(bid: str, v: Viewer = Depends(viewer)):
    b = _require_member(bid, v)
    return {**_public_business(b), "summary": summary_of(b)}


def _counterparty_of(bid: str, v: Viewer) -> dict | None:
    mine = {b["bid"] for b in tn.businesses_of(v.uid)}
    for r in tn.relationships_of(bid):
        if r.get("state") == RelState.declined.value:
            continue
        other = r["seller_bid"] if r["buyer_bid"] == bid else r["buyer_bid"]
        if other in mine:
            return r
    return None


@router.get("/tn/businesses/{bid}/profile")
def get_profile(bid: str, v: Viewer = Depends(viewer)):
    b = _biz_or_404(bid)
    if not (_member(b, v) or v.is_reviewer or _counterparty_of(bid, v)):
        raise HTTPException(404, "business not found")
    return redacted_profile(b)


@router.patch("/tn/businesses/{bid}")
def patch_business(bid: str, body: BusinessPatch, v: Viewer = Depends(viewer)):
    b = _require_member(bid, v, allow_reviewer=False)
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    if "requirements" in changes:
        _validate_requirements(changes["requirements"])
    added, removed = [], []
    if "roles" in changes:
        roles = sorted(set(changes["roles"] or []), key=["buyer", "seller"].index)
        if not roles:
            return _err(422, "role_required", "A business needs at least one role: buying, selling or both.")
        changes["roles"] = roles
        old_roles = set(b.get("roles") or [])
        added = [r for r in roles if r not in old_roles]
        removed = [r for r in ("buyer", "seller") if r in old_roles and r not in roles]
        for role in removed:
            in_use = _relationships_needing(bid, role)
            if in_use:
                side = "selling" if role == "seller" else "buying"
                return _err(409, "role_in_use", f"You still have active trading relationships where you are {side}. "
                            "Pause or end them before turning this off.", role=role, relationships=in_use)
        if not added and not removed:
            del changes["roles"]
    new = {**b, **changes}
    if "seller" in removed and (new.get("listing") or {}).get("listed"):
        new["listing"] = {**new["listing"], "listed": False, "updated_at": tn.iso()}  # stop showing in Find suppliers
    if "representative" in changes:
        rep = dict(changes["representative"])
        old = b.get("representative") or {}
        same = rep.get("name") == old.get("name")
        rep["authority_status"] = old.get("authority_status", "unknown") if same else ("self_declared" if rep.get("name") else "unknown")
        new["representative"] = rep
    new = _index_fields(new)
    if any(k in changes for k in ("gstin", "legal_name", "display_name", "address")):
        dupes = tn.duplicate_candidates(new["gstin"], new.get("legal_name") or new["display_name"],
                                        (new.get("address") or {}).get("pin", ""), exclude=[bid])
        if dupes:
            return _err(409, "possible_duplicate", "Another business already uses this GSTIN or name and PIN.",
                        candidates=[_public_dupe(x) for x in dupes[:5]])
    try:
        saved = tn.cas_replace(tn.BUSINESSES, bid, body.version, new)
    except tn.VersionConflict as e:
        return _err(409, "version_conflict", "This business changed elsewhere; reload it.",
                    current=_public_business(e.current) if e.current else None)
    actor = uid_hash(v.uid)
    ledger(bid, "tn.business.updated", actor, {"bid": bid, "fields": sorted(changes), "version": saved["version"]})
    if not (added or removed):
        return _public_business(saved)
    for role in removed:
        ledger(bid, "tn.business.role_removed", actor, {"bid": bid, "role": role, "roles": saved["roles"], "version": saved["version"]})
    new_checks: list[dict] = []
    for role in added:
        rows, reused = _role_checks(saved, role)
        new_checks += rows
        ledger(bid, "tn.business.role_added", actor, {"bid": bid, "role": role, "roles": saved["roles"], "version": saved["version"],
                                                       "identity_checks_reused": True, "idempotent": reused,
                                                       "checks": [{k: c[k] for k in ("check_id", "dim", "check_type", "status")} for c in rows]})
    if new_checks or removed:
        _ensure_review(saved, f"case_role_{bid}", actor)
    out = _public_business(saved)
    out["role_change"] = {"added": added, "removed": removed,
                          "new_checks": [{k: c.get(k) for k in ("check_id", "dim", "check_type", "status", "summary")} for c in new_checks],
                          "listing_eligibility": _listing_eligibility(saved) if "seller" in saved["roles"] else None}
    return out


# ---------------------------------------------------------------- role switch helpers
ACTIVE_REL_STATES = {"requested", "invited", "accepted", "onboarding", "under_review", "approved_for_trading", "paused"}


def _relationships_needing(bid: str, role: str) -> list[str]:
    """Relationships (not declined) in which this business plays `role`; removing the role would orphan them."""
    side = "seller_bid" if role == "seller" else "buyer_bid"
    return sorted(r["rid"] for r in tn.relationships_of(bid) if r.get(side) == bid and r.get("state") in ACTIVE_REL_STATES)


SELLER_PROVIDERS = {"bank"}  # providers that apply only because the business sells


def _role_checks(biz: dict, role: str) -> tuple[list[dict], bool]:
    """Run only the checks that a newly added role makes applicable, through the same provider path as verify.
    Identity and registration checks already on file are reused, never re-run. Idempotent: the case id is derived
    from the business, the role and its declared inputs, so adding the same role again returns the same rows."""
    if role != "seller":
        return [], False  # buying adds no buyer-only checks
    bid = biz["bid"]
    ih = _inputs_hash(biz, {})
    case_id = f"case_role_{tn.stable_hash([bid, role, ih])[:20]}"
    case = {"case_id": case_id, "bid": bid, "purpose": f"role_added:{role}", "status": "open", "inputs_hash": ih,
            "created_at": tn.iso(), "is_fixture": bool(biz.get("is_fixture"))}
    if not tn.create(tn.CASES, case_id, case):
        return [c for c in tn.checks_of(bid) if c.get("case_id") == case_id], True
    have = tn.checks_of(bid)
    have_types = {c.get("check_type") for c in have}
    ctx = {"mode": "verify", "consents": {}, "is_fixture": bool(biz.get("is_fixture")), "now": tn.iso(), "role_added": role}
    rows = []
    if "bank_account_validation" not in have_types:
        rows += run_providers(biz, case_id, ctx, names=SELLER_PROVIDERS)
    if biz.get("brand_claims"):
        rows += _baseline_checks(biz, case_id, {"representative"} | {c["dim"] for c in have})
    for c in rows:
        tn.put(tn.CHECKS, c["check_id"], c)
    tn.update(tn.CASES, case_id, {"status": "completed"})
    return rows, False


def _listing_eligibility(biz: dict) -> dict:
    """Whether the business can list in Find suppliers, and whether it passes the default 'verified only' filter."""
    from .trust_network_discovery import VERIFIED_CATEGORIES

    cat = policy.category(_checks(biz["bid"]), _model(biz), evidence=tn.evidence_of(biz["bid"]))
    shown = cat in VERIFIED_CATEGORIES
    return {"can_list": True, "listed": bool((biz.get("listing") or {}).get("listed")), "category": cat.value,
            "shown_with_verified_only": shown,
            "note": ("You can list in Find suppliers. Buyers who keep 'verified only' on will see you."
                     if shown else "You can list in Find suppliers, but buyers who keep 'verified only' on will not see you "
                     "until your business identity is confirmed.")}


# ---------------------------------------------------------------- checks from providers
def _providers() -> list:
    try:
        from sauda_verify.providers import REGISTRY

        return list(REGISTRY)
    except Exception:
        log.warning("providers registry not available", exc_info=True)
        return []


EVIDENCE_PROVIDERS = {"documents", "photo"}
REGISTRY_LIKE = {SourceKind.official_registry, SourceKind.authorised_provider}


# Real checks of the declared data itself (the PIN directory, Google geocoding, GSTIN format) keep their true source
# label even on demo businesses: the declared values are demo data, but the check against them is real.
REAL_DATA_CHECKS = {"pincode_directory", "geocode", "gstin_format"}

def _check_doc(bid: str, case_id: str, *, dim: Dim | str, check_type: str, source_kind: SourceKind | str, source_name: str,
               status: CheckStatus | str, summary: str, fields: list | None = None, evidence_ids: list | None = None,
               source_url: str | None = None, expires_at: str | None = None, provider_ref: str | None = None,
               observed: dict | None = None, available: bool = True, reviewer: dict | None = None,
               check_id: str | None = None, checked_at: str | None = None) -> dict:
    c = Check(check_id=check_id or tn.new_id("chk"), business_id=bid, case_id=case_id, dim=Dim(dim), check_type=check_type,
              source_kind=SourceKind(source_kind), source_name=source_name, source_url=source_url, status=CheckStatus(status),
              summary=summary, fields=fields or [], evidence_ids=evidence_ids or [], checked_at=checked_at or tn.iso(),
              expires_at=expires_at, provider_ref=provider_ref, available=available, observed=observed or {},
              reviewer=ReviewerStamp.model_validate(reviewer) if reviewer else None)
    return c.model_dump(mode="json")


def run_providers(biz: dict, case_id: str, ctx: dict, names: set[str] | None = None, evidence_ids: list | None = None) -> list[dict]:
    model = _model(biz)
    out = []
    for p in _providers():
        pname = getattr(p, "name", type(p).__name__)
        if names is not None and pname not in names:
            continue
        if names is None and pname in EVIDENCE_PROVIDERS:
            continue  # document/photo extraction runs only on an upload
        try:
            if not p.applicable(model):
                continue
            results = p.run(model, ctx) or []
        except Exception as e:  # a source being down is not a finding about the business
            log.warning("provider %s failed: %s", pname, e)
            dims = list(getattr(p, "dims", []) or [Dim.identity])
            out.append(_check_doc(biz["bid"], case_id, dim=dims[0], check_type=pname, source_kind=SourceKind.preliminary_validation,
                                  source_name=pname, status=CheckStatus.inconclusive, available=False,
                                  summary=f"The {pname} source could not be reached; this check needs to be repeated.",
                                  evidence_ids=evidence_ids))
            continue
        for r in results:
            kind = SourceKind(r.source_kind)
            if biz.get("is_fixture") and kind in REGISTRY_LIKE and pname not in REAL_DATA_CHECKS:
                kind = SourceKind.simulated_fixture  # a demo business never carries real registry results
            dim = getattr(r, "dim", None) or (list(getattr(p, "dims", [])) or [Dim.identity])[0]
            out.append(_check_doc(
                biz["bid"], case_id, dim=dim, check_type=getattr(r, "check_type", None) or pname, source_kind=kind,
                source_name=r.source_name, source_url=r.source_url, status=r.status, summary=r.summary,
                fields=[f.model_dump() for f in r.fields], observed=tn.mask_deep(r.observed or {}), provider_ref=r.provider_ref,
                available=r.available, expires_at=getattr(r, "expires_at", None), evidence_ids=evidence_ids))
    return out


def _baseline_checks(biz: dict, case_id: str, have: set[str]) -> list[dict]:
    """Self-declared rows for dimensions no provider covered, so the profile says what is only declared."""
    out = []
    rep = biz.get("representative") or {}
    if "representative" not in have:
        st = rep.get("authority_status") or "unknown"
        if st == "verified":
            pass
        elif rep.get("name"):
            out.append(_check_doc(biz["bid"], case_id, dim=Dim.representative, check_type="representative_declaration",
                                  source_kind=SourceKind.self_declared, source_name="Owner declaration", status=CheckStatus.pending,
                                  summary=f"{rep.get('role') or 'Representative'} is self-declared; authority to act for the business has not been shown yet."))
        else:
            out.append(_check_doc(biz["bid"], case_id, dim=Dim.representative, check_type="representative_declaration",
                                  source_kind=SourceKind.self_declared, source_name="Owner declaration", status=CheckStatus.pending,
                                  summary="No representative has been named yet."))
    if biz.get("brand_claims") and "distribution_authority" not in have:
        out.append(_check_doc(biz["bid"], case_id, dim=Dim.distribution_authority, check_type="brand_authorisation_claim",
                              source_kind=SourceKind.self_declared, source_name="Owner declaration", status=CheckStatus.pending,
                              summary=f"Claims to distribute {', '.join(biz['brand_claims'])}; a reviewer must see the brand's authorisation letter."))
    return out


def _ensure_review(biz: dict, case_id: str, actor: str) -> dict | None:
    """Open (or refresh) the business's review task when policy finds reasons for a person to look."""
    s = policy.summarize(_checks(biz["bid"]), _model(biz), evidence=tn.evidence_of(biz["bid"]))
    tid = f"rv_{biz['bid']}"
    cur = tn.get(tn.REVIEWS, tid)
    if not s.review_reasons:
        if cur and cur["status"] in ("open", "needs_evidence", "escalated"):
            tn.mutate(tn.REVIEWS, tid, lambda d: {**d, "reasons": [], "status": "approved"})
        return cur
    if cur is None:
        doc = {"tid": tid, "bid": biz["bid"], "case_id": case_id, "reasons": s.review_reasons, "status": "open", "decisions": [],
               "is_fixture": bool(biz.get("is_fixture")), "created_at": tn.iso(), "updated_at": tn.iso(), "version": 1}
        if tn.create(tn.REVIEWS, tid, doc):
            ledger(biz["bid"], "tn.review.opened", actor, {"tid": tid, "reasons": s.review_reasons})
            return doc
        cur = tn.get(tn.REVIEWS, tid)

    def refresh(d):
        d["reasons"] = s.review_reasons
        d["case_id"] = case_id
        if d["status"] in ("approved", "rejected"):
            d["status"] = "open"
        return d
    return tn.mutate(tn.REVIEWS, tid, refresh)


# ---------------------------------------------------------------- verify
class VerifyIn(BaseModel):
    consents: dict[str, bool] = Field(default_factory=dict)


def _inputs_hash(b: dict, consents: dict) -> str:
    keys = ("display_name", "legal_name", "gstin", "udyam", "fssai", "cin_llpin", "address", "representative", "brand_claims", "constitution")
    return tn.stable_hash({"declared": {k: b.get(k) for k in keys}, "consents": {k: bool(v) for k, v in sorted(consents.items())}})


@router.post("/tn/businesses/{bid}/verify")
def verify_business(bid: str, body: VerifyIn, v: Viewer = Depends(viewer)):
    b = _require_member(bid, v, allow_reviewer=False)
    ih = _inputs_hash(b, body.consents)
    case_id = f"case_{tn.stable_hash([bid, ih])[:20]}"
    case = {"case_id": case_id, "bid": bid, "purpose": "general", "status": "open", "inputs_hash": ih,
            "consents": {k: bool(x) for k, x in body.consents.items()}, "created_at": tn.iso(), "created_by_hash": uid_hash(v.uid),
            "is_fixture": bool(b.get("is_fixture"))}
    if not tn.create(tn.CASES, case_id, case):
        existing = tn.get(tn.CASES, case_id)
        return {"case": existing, "checks": [c for c in tn.checks_of(bid) if c.get("case_id") == case_id],
                "summary": summary_of(b), "idempotent": True}
    ctx = {"mode": "verify", "consents": case["consents"], "is_fixture": bool(b.get("is_fixture")), "now": tn.iso()}
    new = run_providers(b, case_id, ctx)
    new += _baseline_checks(b, case_id, {c["dim"] for c in new} | {c["dim"] for c in tn.checks_of(bid)})
    for c in new:
        tn.put(tn.CHECKS, c["check_id"], c)
    actor = uid_hash(v.uid)
    ledger(bid, "tn.verify.run", actor, {"case_id": case_id, "inputs_hash": ih,
                                         "checks": [{k: c[k] for k in ("check_id", "dim", "source_kind", "status")} for c in new]})
    rv = _ensure_review(b, case_id, actor)
    tn.update(tn.CASES, case_id, {"status": "in_review" if rv and rv.get("status") == "open" else "completed"})
    return {"case": tn.get(tn.CASES, case_id), "checks": new, "summary": summary_of(b), "idempotent": False}


class ReviewRequestIn(BaseModel):
    note: str = Field(default="", max_length=500)


@router.post("/tn/businesses/{bid}/request-review")
def request_review(bid: str, body: ReviewRequestIn, v: Viewer = Depends(viewer)):
    """A member asks a person to look at the business (e.g. after correcting details). Idempotent per open task."""
    b = _require_member(bid, v, allow_reviewer=False)
    tid = f"rv_{bid}"
    actor = uid_hash(v.uid)
    note = body.note.strip()

    def add(d):
        if "owner_requested" not in d.get("reasons", []):
            d["reasons"] = [*d.get("reasons", []), "owner_requested"]
        if note:
            d["owner_note"] = note
        if d.get("status") in ("approved", "rejected"):
            d["status"] = "open"
        d["updated_at"] = tn.iso()
        return d

    if tn.get(tn.REVIEWS, tid) is None:
        doc = {"tid": tid, "bid": bid, "case_id": None, "reasons": ["owner_requested"], "status": "open", "decisions": [],
               "is_fixture": bool(b.get("is_fixture")), "created_at": tn.iso(), "updated_at": tn.iso(), "version": 1}
        if note:
            doc["owner_note"] = note
        if not tn.create(tn.REVIEWS, tid, doc):
            tn.mutate(tn.REVIEWS, tid, add)
    else:
        tn.mutate(tn.REVIEWS, tid, add)
    ledger(bid, "tn.review.requested", actor, {"tid": tid, "with_note": bool(note)})
    t = tn.get(tn.REVIEWS, tid)
    return {"task": {k: t.get(k) for k in ("tid", "status", "reasons")}, "reason_text": policy.reason_text(t.get("reasons", []))}


@router.get("/tn/businesses/{bid}/summary")
def business_summary(bid: str, v: Viewer = Depends(viewer)):
    b = _require_member(bid, v)
    return summary_of(b)


@router.get("/tn/businesses/{bid}/checks")
def business_checks(bid: str, v: Viewer = Depends(viewer)):
    _require_member(bid, v)
    out = []
    for c in tn.checks_of(bid):
        if "contact_hash" in (c.get("observed") or {}):
            c = {**c, "observed": {k: x for k, x in c["observed"].items() if k != "contact_hash"}}
        out.append(c)
    return out


@router.get("/tn/businesses/{bid}/ledger")
def business_ledger(bid: str, v: Viewer = Depends(viewer)):
    """The business's signed audit chain (payloads were masked when written) and its verification."""
    _require_member(bid, v)
    from . import trust

    try:
        from sauda_ledger import list_events

        events = list_events(f"biz-{bid}")
        checks = trust.verify_chain(f"biz-{bid}").to_dict()
    except Exception:
        log.exception("ledger read failed for %s", bid)
        raise HTTPException(503, "ledger is unavailable")
    return {"chain_id": f"biz-{bid}", "events": events, "verification": checks}


# ---------------------------------------------------------------- evidence
def _gcs_put(bucket: str, path: str, data: bytes, mime: str) -> None:  # monkeypatched in tests
    from google.cloud import storage

    storage.Client(project=settings().project).bucket(bucket).blob(path).upload_from_string(data, content_type=mime)


def _gcs_signed_url(bucket: str, path: str) -> str:  # monkeypatched in tests
    from google.cloud import storage

    blob = storage.Client(project=settings().project).bucket(bucket).blob(path)
    try:
        return blob.generate_signed_url(version="v4", expiration=timedelta(minutes=10), method="GET")
    except Exception:
        # Token-only credentials (Cloud Run metadata server) cannot sign locally: sign through IAM signBlob.
        import google.auth
        from google.auth.transport.requests import Request

        creds, _ = google.auth.default()
        creds.refresh(Request())
        email = getattr(creds, "service_account_email", None)
        if not email or email == "default":
            raise
        return blob.generate_signed_url(version="v4", expiration=timedelta(minutes=10), method="GET",
                                        service_account_email=email, access_token=creds.token)


def _private_bucket() -> str:
    from sauda_trust import settings as ts

    return ts.get_settings().private_bucket


def _screen(text: str) -> dict:
    if not text:
        return {"blocked": False, "categories": []}
    from . import trust

    try:
        vd = trust.verdict_dict(trust.screen(text[:8000], "inbound"))
        return {"blocked": bool(vd.get("blocked") or vd.get("verdict") not in (None, "clean")), "categories": vd.get("categories", [])}
    except Exception:
        log.warning("evidence screening failed", exc_info=True)
        return {"blocked": False, "categories": [], "unscreened": True}


EVIDENCE_DIM = {"gst_certificate": Dim.registration, "udyam_certificate": Dim.registration, "fssai_licence": Dim.product_compliance,
                "shop_photo": Dim.operational, "storefront_photo": Dim.operational, "authorisation_letter": Dim.representative,
                "partnership_deed": Dim.representative, "brand_authorisation": Dim.distribution_authority,
                "address_proof": Dim.address, "trade_reference": Dim.trading_references, "invoice": Dim.trading_references,
                "cancelled_cheque": Dim.payment_details}


@router.post("/tn/businesses/{bid}/evidence")
async def upload_evidence(bid: str, file: UploadFile = File(...), type: str = Form(...), consent: bool = Form(True),
                          v: Viewer = Depends(viewer)):
    b = _require_member(bid, v, allow_reviewer=False)
    if not consent:
        raise HTTPException(422, "consent is required to store evidence")
    if type not in EVIDENCE_DIM:
        raise HTTPException(422, f"type must be one of {sorted(EVIDENCE_DIM)}")
    data = await file.read(MAX_EVIDENCE_BYTES + 1)
    if len(data) > MAX_EVIDENCE_BYTES:
        raise HTTPException(413, "file too large (8 MB max)")
    mime = (file.content_type or "").lower()
    if mime not in EVIDENCE_MIME:
        raise HTTPException(415, "only PDF, JPEG, PNG or WebP")
    digest = tn.sha256_hex(data)
    same = tn.where(tn.EVIDENCE, "sha256", digest)
    for e in same:
        if e["bid"] == bid and e["type"] == type:
            return {"evidence": _public_evidence(e), "checks": [c for c in tn.checks_of(bid) if e["eid"] in (c.get("evidence_ids") or [])],
                    "deduplicated": True}
    reused = any(e["bid"] != bid for e in same)
    eid = f"ev_{digest[:20]}_{bid[-6:]}"
    path = f"tn/{bid}/{eid}"
    bucket = _private_bucket()
    try:
        _gcs_put(bucket, path, data, mime)
    except Exception:
        log.exception("evidence upload failed")
        raise HTTPException(503, "evidence storage is unavailable; try again")
    case_id = f"case_ev_{eid}"
    ctx = {"mode": "evidence", "is_fixture": bool(b.get("is_fixture")), "now": tn.iso(),
           "evidence": {"eid": eid, "type": type, "mime": mime, "size": len(data), "data": data}}
    checks = run_providers(b, case_id, ctx, names={"documents", "photo"}, evidence_ids=[eid])
    text = " ".join(str((c.get("observed") or {}).get("text") or "") for c in checks)
    guard = _screen(text)
    extracted = {}
    for c in checks:
        extracted.update({k: x for k, x in (c.get("observed") or {}).items() if k != "text"})
    dim = EVIDENCE_DIM[type]
    if guard["blocked"] or reused:
        why = "re-used from another business" if reused else "flagged by content screening"
        checks.append(_check_doc(bid, case_id, dim=dim, check_type="document_screening", source_kind=SourceKind.uploaded_evidence,
                                 source_name="Evidence screening", status=CheckStatus.conflict, evidence_ids=[eid],
                                 observed={"suspicious": True, "reused_by_other_business": reused, "guard_blocked": guard["blocked"]},
                                 summary=f"The uploaded {type.replace('_', ' ')} was {why}; a reviewer must look at it."))
    if not any(c["dim"] == dim.value for c in checks):
        checks.append(_check_doc(bid, case_id, dim=dim, check_type=f"document_{type}", source_kind=SourceKind.uploaded_evidence,
                                 source_name="Uploaded document", status=CheckStatus.pending, evidence_ids=[eid],
                                 summary=f"{type.replace('_', ' ').capitalize()} uploaded; waiting for a reviewer to compare it with the declared details."))
    ev = {"eid": eid, "bid": bid, "type": type, "gcs_uri": f"gs://{bucket}/{path}", "sha256": digest, "mime": mime, "size": len(data),
          "extracted": tn.mask_deep(extracted), "contact_hashes": _extracted_contact_hashes(extracted), "guard": guard, "reused_by_other_business": reused,
          "uploaded_by_hash": uid_hash(v.uid), "consent": True, "is_fixture": bool(b.get("is_fixture")), "created_at": tn.iso(),
          "retention_until": tn.iso(tn.now() + timedelta(days=EVIDENCE_RETENTION_DAYS))}
    tn.put(tn.EVIDENCE, eid, ev)
    tn.create(tn.CASES, case_id, {"case_id": case_id, "bid": bid, "purpose": "general", "status": "open", "created_at": tn.iso(),
                                  "is_fixture": bool(b.get("is_fixture"))})
    for c in checks:
        tn.put(tn.CHECKS, c["check_id"], c)
    actor = uid_hash(v.uid)
    ledger(bid, "tn.evidence.added", actor, {"eid": eid, "type": type, "sha256": digest, "reused": reused, "guard_blocked": guard["blocked"],
                                            "checks": [{k: c[k] for k in ("check_id", "dim", "status")} for c in checks]})
    _ensure_review(b, case_id, actor)
    return {"evidence": _public_evidence(ev), "checks": checks, "deduplicated": False}


def _public_evidence(e: dict) -> dict:
    return {k: e.get(k) for k in ("eid", "bid", "type", "sha256", "mime", "size", "extracted", "guard", "reused_by_other_business",
                                  "created_at", "retention_until")}


@router.get("/tn/businesses/{bid}/evidence")
def list_evidence(bid: str, v: Viewer = Depends(viewer)):
    _require_member(bid, v)
    return [_public_evidence(e) for e in tn.evidence_of(bid)]


@router.get("/tn/evidence/{eid}/url")
def evidence_url(eid: str, v: Viewer = Depends(viewer)):
    e = tn.get(tn.EVIDENCE, eid)
    if not e:
        raise HTTPException(404, "evidence not found")
    _require_member(e["bid"], v)  # owner members or reviewers only; counterparties never see documents
    try:
        url = _gcs_signed_url(_private_bucket(), f"tn/{e['bid']}/{eid}")
    except Exception:
        log.warning("signed url failed", exc_info=True)
        raise HTTPException(503, "signed links are unavailable in this environment")
    return {"eid": eid, "url": url, "expires_in_s": 600}


# ---------------------------------------------------------------- location
class LocationIn(BaseModel):
    lat: float = Field(ge=6.0, le=37.5)  # India's bounding box
    lng: float = Field(ge=68.0, le=97.5)
    accuracy_m: float | None = Field(None, ge=0, le=100000)
    consent: bool


@router.post("/tn/businesses/{bid}/location")
def post_location(bid: str, body: LocationIn, v: Viewer = Depends(viewer)):
    b = _require_member(bid, v, allow_reviewer=False)
    if not body.consent:
        raise HTTPException(422, "location is stored only with consent")
    geo = {"lat": round(body.lat, 5), "lng": round(body.lng, 5), "accuracy_m": body.accuracy_m, "captured_at": tn.iso(), "consent": True}
    b = tn.mutate(tn.BUSINESSES, bid, lambda d: {**d, "geo": geo})
    case_id = f"case_loc_{bid}"
    tn.create(tn.CASES, case_id, {"case_id": case_id, "bid": bid, "purpose": "general", "status": "open", "created_at": tn.iso(),
                                  "is_fixture": bool(b.get("is_fixture"))})
    ctx = {"mode": "location", "location": geo, "is_fixture": bool(b.get("is_fixture")), "now": tn.iso()}
    checks = [c for c in run_providers(b, case_id, ctx, names={"geocode"}) if c["dim"] == Dim.address.value]
    if not checks:
        checks = [_check_doc(bid, case_id, dim=Dim.address, check_type="device_location", source_kind=SourceKind.device_signal,
                             source_name="Device location (with consent)", status=CheckStatus.inconclusive, available=False,
                             summary="Location recorded with consent, but the declared address could not be geocoded to compare it.")]
    for c in checks:
        c["source_kind"] = SourceKind.device_signal.value if c["source_kind"] != SourceKind.simulated_fixture.value else c["source_kind"]
        tn.put(tn.CHECKS, c["check_id"], c)
    actor = uid_hash(v.uid)
    ledger(bid, "tn.location.added", actor, {"case_id": case_id, "accuracy_m": body.accuracy_m,
                                             "checks": [{k: c[k] for k in ("check_id", "status")} for c in checks]})
    _ensure_review(b, case_id, actor)
    return {"checks": checks, "summary": summary_of(b)}


# ---------------------------------------------------------------- business contact (phone / email one-time code)
CONTACT_OTP_PER_HOUR = 5
CONTACT_TOKEN_MAX_AGE_S = 15 * 60
CONTACT_TEMP_USER_MAX_AGE_S = 60 * 60
CONTACT_OTP_SOURCE = "Firebase Authentication OTP"
_contact_hits: dict[str, list[float]] = {}


def _contact_limited(bid: str) -> bool:
    import time

    now = time.time()
    hits = [t for t in _contact_hits.get(bid, []) if now - t < 3600]
    if len(hits) >= CONTACT_OTP_PER_HOUR:
        _contact_hits[bid] = hits
        return True
    _contact_hits[bid] = [*hits, now]
    return False


def _contact_fb_app():
    """The same Firebase project the owner signs in with; the browser uses a second, temporary app instance."""
    import firebase_admin

    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(options={"projectId": settings().project})


def _delete_temp_contact_user(claims: dict, owner_uid: str) -> str:
    """Delete the temporary Firebase user created by the phone/email sign-in, so no stray accounts remain.
    Only a user that is not the owner, has just this one sign-in method and was created in the last hour is
    deleted; an existing account that happens to own the number or address is never touched."""
    from firebase_admin import auth as fb_auth

    uid = claims.get("uid") or claims.get("sub") or ""
    if not uid or uid == owner_uid:
        return "kept_owner_account"
    try:
        app = _contact_fb_app()
        u = fb_auth.get_user(uid, app=app)
        providers = {p.provider_id for p in (u.provider_data or [])}
        created_ms = getattr(u.user_metadata, "creation_timestamp", None) or 0
        import time

        fresh = created_ms and (time.time() * 1000 - created_ms) < CONTACT_TEMP_USER_MAX_AGE_S * 1000
        if len(providers) > 1 or not fresh:
            return "kept_existing_account"
        fb_auth.delete_user(uid, app=app)
        return "deleted"
    except Exception:
        log.warning("temporary contact user cleanup failed", exc_info=True)
        return "cleanup_failed"


def _declared_contact_hash(b: dict, kind: str) -> str | None:
    hashes = b.get("contact_hashes") or {}
    if hashes.get(kind):
        return hashes[kind]
    c = b.get("contact") or {}
    # older records keep one hash: the phone's when a phone was declared, otherwise the email's
    if kind == "phone" and c.get("phone_masked"):
        return b.get("contact_hash")
    if kind == "email" and c.get("email_masked") and not c.get("phone_masked"):
        return b.get("contact_hash")
    return None


def _document_contact_hashes(bid: str, kind: str) -> list[tuple[str, str]]:
    """(evidence type, keyed hash) for contacts extracted from uploaded GST / Udyam / FSSAI documents."""
    out = []
    for e in tn.evidence_of(bid):
        if e.get("type") not in ("gst_certificate", "udyam_certificate", "fssai_licence"):
            continue
        for h in (e.get("contact_hashes") or {}).get(kind) or []:
            out.append((e["type"], h))
    return out


def _extracted_contact_hashes(extracted: dict) -> dict:
    out: dict[str, list[str]] = {}
    for key, val in (extracted or {}).items():
        if not isinstance(val, str) or not val.strip():
            continue
        k = key.lower()
        if not any(w in k for w in ("phone", "mobile", "email", "contact")):
            continue
        kind, n = tn.normalize_contact(val)
        if (kind == "phone" and len(n) == 10) or (kind == "email" and "@" in n):
            out.setdefault(kind, []).append(tn.keyed_hash(n, "contact"))
    return out


class ContactVerifyIn(BaseModel):
    kind: Literal["phone", "email"]
    id_token: str = Field(min_length=20, max_length=8192)


@router.post("/tn/businesses/{bid}/contact/verify")
def verify_contact(bid: str, body: ContactVerifyIn, v: Viewer = Depends(viewer)):
    """Record that a member proved control of the business phone or email with a Firebase one-time code.
    The browser signs in on a second, temporary Firebase app (the owner's session is untouched) and sends that
    session's ID token. Only a keyed hash and a masked value are stored."""
    b = _require_member(bid, v, allow_reviewer=False)
    if _contact_limited(bid):
        return _err(429, "rate_limited", f"At most {CONTACT_OTP_PER_HOUR} contact verification attempts an hour for a business.")
    from firebase_admin import auth as fb_auth

    try:
        app = _contact_fb_app()
    except Exception:
        log.warning("firebase admin unavailable for contact verification", exc_info=True)
        return _err(503, "contact_verification_unavailable", "Phone/email verification isn't switched on yet.")
    try:
        claims = fb_auth.verify_id_token(body.id_token, app=app)
    except Exception:
        return _err(401, "invalid_contact_token", "The verification sign-in could not be confirmed. Send a new code and try again.")
    import time

    auth_time = int(claims.get("auth_time") or 0)
    if not auth_time or time.time() - auth_time > CONTACT_TOKEN_MAX_AGE_S:
        return _err(401, "invalid_contact_token", "That code was confirmed too long ago. Send a new code and try again.")
    provider = ((claims.get("firebase") or {}).get("sign_in_provider") or "").lower()
    if body.kind == "phone":
        raw = claims.get("phone_number") or ""
        if not raw or provider not in ("phone", ""):
            return _err(422, "contact_missing", "The sign-in did not include a phone number confirmed by a code.")
    else:
        raw = claims.get("email") or ""
        if not raw:
            return _err(422, "contact_missing", "The sign-in did not include an email address.")
        if claims.get("email_verified") is not True:
            return _err(422, "email_not_verified", "The email address was not confirmed. Open the sign-in link sent to it.")
        if provider not in ("emaillink", "password", ""):
            return _err(422, "contact_missing", "Use the email sign-in link to confirm the business email.")
    kind, norm = tn.normalize_contact(raw)
    if kind != body.kind or (kind == "phone" and len(norm) != 10):
        return _err(422, "contact_missing", "Only Indian mobile numbers (+91) and email addresses can be confirmed here.")
    masked = tn.mask_contact(kind, norm)
    chash = tn.keyed_hash(norm, "contact")
    cleanup = _delete_temp_contact_user(claims, v.uid)

    label = "phone" if kind == "phone" else "email"
    fields = [FieldCompare(field=f"business_{label}", declared=None, observed=masked, match=None)]
    review_note = None
    declared_hash = _declared_contact_hash(b, kind)
    declared_match = None
    if declared_hash:
        declared_match = secrets.compare_digest(declared_hash, chash)
        declared_masked = (b.get("contact") or {}).get(f"{label}_masked")
        fields[0] = FieldCompare(field=f"business_{label}", declared=declared_masked, observed=masked, match=declared_match)
    doc_hashes = _document_contact_hashes(bid, kind)
    doc_match = None
    if doc_hashes:
        doc_match = any(secrets.compare_digest(h, chash) for _, h in doc_hashes)
        fields.append(FieldCompare(field=f"document_{label}", declared=", ".join(sorted({t for t, _ in doc_hashes})),
                                   observed=masked, match=doc_match))
    summary = (f"Controls the business {label} {masked}. This shows access to the business contact, "
               "not legal authority to act for the business.")
    status = CheckStatus.partially_verified
    if declared_match is True:
        summary += f" It matches the {label} declared when the business was added."
    if doc_match is True:
        summary += f" It matches the {label} on an uploaded registration document."
    if declared_match is False or doc_match is False:
        status = CheckStatus.inconclusive
        which = " and ".join(w for w, m in (("the declared " + label, declared_match), ("the uploaded document", doc_match)) if m is False)
        review_note = f"The confirmed {label} differs from {which}."
        summary += f" {review_note} A reviewer needs to look at this."
    case_id = f"case_contact_{bid}"
    tn.create(tn.CASES, case_id, {"case_id": case_id, "bid": bid, "purpose": "business_contact", "status": "open",
                                  "created_at": tn.iso(), "is_fixture": bool(b.get("is_fixture"))})
    check = _check_doc(bid, case_id, dim=Dim.representative, check_type="business_contact_otp",
                       source_kind=SourceKind.authorised_provider, source_name=CONTACT_OTP_SOURCE, status=status,
                       summary=summary, fields=[f.model_dump() for f in fields],
                       observed={"kind": kind, "masked": masked, "contact_hash": chash, "declared_match": declared_match,
                                 "document_match": doc_match, "review_reason": review_note,
                                 "proves": "control of the business contact", "does_not_prove": "authority to act for the business"})
    tn.put(tn.CHECKS, check["check_id"], check)
    actor = uid_hash(v.uid)
    ledger(bid, "tn.contact.verified", actor, {"check_id": check["check_id"], "kind": kind, "masked": masked, "status": status.value,
                                              "declared_match": declared_match, "document_match": doc_match,
                                              "temp_user": cleanup})
    _ensure_review(b, case_id, actor)
    left = CONTACT_OTP_PER_HOUR - len(_contact_hits.get(bid, []))
    pub = {k: x for k, x in check.items() if k != "observed"}
    pub["observed"] = {k: x for k, x in check["observed"].items() if k != "contact_hash"}
    return {"check": pub, "contact": {"kind": kind, "masked": masked, "declared_match": declared_match, "document_match": doc_match},
            "temp_user": cleanup, "attempts_left": max(left, 0), "summary": summary_of(b)}


# ---------------------------------------------------------------- invitations
class InvitationIn(BaseModel):
    from_bid: str
    role_invited: Literal["seller", "buyer"]
    contact: str = Field(min_length=5, max_length=120)
    categories: list[str] = Field(default_factory=list, max_length=20)
    display_name_hint: str | None = Field(None, max_length=120)


def _share_link(token: str) -> str:
    origin = (settings().owner_app_origin.split(",")[0] or "").strip().rstrip("/")
    return f"{origin}/network/invite/{token}"


def _public_invitation(i: dict) -> dict:
    return {k: i.get(k) for k in ("iid", "from_bid", "role_invited", "contact_masked", "status", "expires_at", "rid", "categories",
                                  "display_name_hint", "created_at")}


@router.post("/tn/invitations")
def create_invitation(body: InvitationIn, v: Viewer = Depends(viewer)):
    b = _require_member(body.from_bid, v, allow_reviewer=False)
    other_role = "buyer" if body.role_invited == "seller" else "seller"
    if other_role not in (b.get("roles") or []):
        raise HTTPException(422, f"only a {other_role} business can invite a {body.role_invited}")
    kind, norm = tn.normalize_contact(body.contact)
    if (kind == "phone" and len(norm) != 10) or (kind == "email" and not tn.EMAIL_RE.fullmatch(norm)):
        raise HTTPException(422, "contact must be an email address or a 10-digit Indian mobile number")
    chash = tn.keyed_hash(norm, "contact")
    idem = tn.stable_hash([body.from_bid, chash, body.role_invited])
    iid = f"inv_{idem[:20]}"
    token = secrets.token_urlsafe(24)
    doc = {"iid": iid, "from_bid": body.from_bid, "role_invited": body.role_invited, "contact_masked": tn.mask_contact(kind, norm),
           "contact_kind": kind, "contact_hash": chash, "token_hash": tn.sha256_hex(token), "status": "sent",
           "expires_at": tn.iso(tn.now() + timedelta(days=INVITE_TTL_DAYS)), "rid": None, "idem_key": idem,
           "categories": body.categories, "display_name_hint": body.display_name_hint, "created_by_hash": uid_hash(v.uid),
           "is_fixture": bool(b.get("is_fixture")), "created_at": tn.iso()}
    if not tn.create(tn.INVITATIONS, iid, doc):
        cur = tn.get(tn.INVITATIONS, iid)
        # The token is shown once only; repeating the request does not re-issue it.
        return {"invitation": _public_invitation(cur), "token": None, "share_link": None, "duplicate": True}
    ledger(body.from_bid, "tn.invitation.sent", uid_hash(v.uid),
           {"iid": iid, "role_invited": body.role_invited, "contact": doc["contact_masked"], "categories": body.categories})
    return {"invitation": _public_invitation(doc), "token": token, "share_link": _share_link(token), "duplicate": False}


@router.get("/tn/invitations")
def list_invitations(bid: str = Query(...), v: Viewer = Depends(viewer)):
    _require_member(bid, v)
    return [_public_invitation(i) for i in tn.where(tn.INVITATIONS, "from_bid", bid)]


def _invitation_by_token(token: str) -> dict:
    if not token or len(token) > 100:
        raise HTTPException(404, "invitation not found")
    rows = tn.where(tn.INVITATIONS, "token_hash", tn.sha256_hex(token))
    if not rows:
        raise HTTPException(404, "invitation not found")
    inv = rows[0]
    if inv["status"] == "sent" and inv["expires_at"] < tn.iso():
        tn.update(tn.INVITATIONS, inv["iid"], {"status": "expired"})
        inv["status"] = "expired"
    return inv


@router.get("/tn/invitations/{token}")
def get_invitation(token: str):
    inv = _invitation_by_token(token)
    b = tn.business(inv["from_bid"]) or {}
    return {"inviter_display_name": b.get("display_name"), "inviter_city": (b.get("address") or {}).get("city"),
            "role_invited": inv["role_invited"], "categories": inv.get("categories", []), "status": inv["status"],
            "expires_at": inv["expires_at"], "is_fixture": bool(inv.get("is_fixture"))}


class AcceptIn(BaseModel):
    bid: str


@router.post("/tn/invitations/{token}/accept")
def accept_invitation(token: str, body: AcceptIn, v: Viewer = Depends(viewer)):
    inv = _invitation_by_token(token)
    acceptor = _require_member(body.bid, v, allow_reviewer=False)
    if inv["status"] in ("expired", "revoked"):
        return _err(410, f"invitation_{inv['status']}", f"This invitation is {inv['status']}.")
    if body.bid == inv["from_bid"]:
        raise HTTPException(422, "a business cannot accept its own invitation")
    if inv["role_invited"] not in (acceptor.get("roles") or []):
        raise HTTPException(422, f"this invitation is for a {inv['role_invited']} business")
    buyer_bid, seller_bid = (inv["from_bid"], body.bid) if inv["role_invited"] == "seller" else (body.bid, inv["from_bid"])
    rid = f"rel_{tn.stable_hash([buyer_bid, seller_bid])[:16]}"
    if inv["status"] == "accepted":
        if inv.get("rid") != rid:
            return _err(409, "invitation_used", "This invitation was already accepted by another business.")
        return {"relationship": tn.get(tn.RELATIONSHIPS, rid), "idempotent": True}
    seller = tn.business(seller_bid) or {}
    now = tn.iso()
    actor = uid_hash(v.uid)
    rel = {"rid": rid, "buyer_bid": buyer_bid, "seller_bid": seller_bid, "initiated_by_bid": inv["from_bid"],
           "state": RelState.onboarding.value, "categories": inv.get("categories", []), "provenance": "invitation",
           "shared_fields": ["display_name", "city", "state", "category", "products", "verification_summary"],
           "requirements": seller.get("requirements") or policy.DEFAULT_REQUIREMENTS, "approved_tiers": [],
           "human_review": None, "invitation_id": inv["iid"],
           "history": [{"from": None, "to": "invited", "by_hash": inv.get("created_by_hash"), "reason": "invitation sent", "at": inv["created_at"]},
                       {"from": "invited", "to": "accepted", "by_hash": actor, "reason": "invitation accepted", "at": now},
                       {"from": "accepted", "to": "onboarding", "by_hash": actor, "reason": "profiles shared for review", "at": now}],
           "is_fixture": bool(inv.get("is_fixture") and acceptor.get("is_fixture")), "created_at": now, "updated_at": now, "version": 1}
    if not tn.create(tn.RELATIONSHIPS, rid, rel):
        rel = tn.get(tn.RELATIONSHIPS, rid)
        if rel.get("state") == RelState.declined.value:
            return _err(409, "relationship_declined", "These businesses already have a declined relationship.")
    tn.update(tn.INVITATIONS, inv["iid"], {"status": "accepted", "rid": rid, "accepted_at": now})
    for bid in (buyer_bid, seller_bid):
        ledger(bid, "tn.relationship.accepted", actor, {"rid": rid, "buyer_bid": buyer_bid, "seller_bid": seller_bid,
                                                        "iid": inv["iid"], "state": rel["state"]})
    return {"relationship": rel, "idempotent": False}


@router.post("/tn/invitations/{iid}/revoke")
def revoke_invitation(iid: str, v: Viewer = Depends(viewer)):
    inv = tn.get(tn.INVITATIONS, iid)
    if not inv:
        raise HTTPException(404, "invitation not found")
    _require_member(inv["from_bid"], v, allow_reviewer=False)
    if inv["status"] != "sent":
        return _err(409, "invalid_state", f"invitation is {inv['status']}")
    tn.update(tn.INVITATIONS, iid, {"status": "revoked"})
    ledger(inv["from_bid"], "tn.invitation.revoked", uid_hash(v.uid), {"iid": iid})
    return {**_public_invitation(inv), "status": "revoked"}


# ---------------------------------------------------------------- relationships
TRANSITIONS: dict[str, set[str]] = {
    "requested": {"accepted", "declined"},  # discovery request: only the seller accepts or declines
    "invited": {"accepted", "declined"},
    "accepted": {"onboarding", "declined", "paused"},
    "onboarding": {"under_review", "declined", "paused"},
    "under_review": {"approved_for_trading", "declined", "paused"},
    "approved_for_trading": {"paused", "declined"},
    "paused": {"under_review", "declined"},
    "declined": set(),
}


def can_transition(a: str, b: str) -> bool:
    return b in TRANSITIONS.get(a, set())


def _rel_view(r: dict, viewer_bids: set[str]) -> dict:
    buyer = tn.business(r["buyer_bid"]) or {}
    seller = tn.business(r["seller_bid"]) or {}
    out = {**r, "buyer_display_name": buyer.get("display_name"), "seller_display_name": seller.get("display_name")}
    if r["seller_bid"] in viewer_bids and buyer:
        rq = r.get("requirements") or policy.DEFAULT_REQUIREMENTS
        checks = _checks(r["buyer_bid"])
        out["readiness"] = {t: policy.readiness(t, rq, checks, _model(buyer),
                                                relationship_reviewed=bool((r.get("human_review") or {}).get("approved"))).model_dump()
                            for t in rq}
    return out


@router.get("/tn/relationships")
def list_relationships(bid: str = Query(...), v: Viewer = Depends(viewer)):
    _require_member(bid, v)
    mine = {b["bid"] for b in tn.businesses_of(v.uid)} | ({bid} if v.is_reviewer else set())
    return [_rel_view(r, mine) for r in tn.relationships_of(bid)]


@router.get("/tn/relationships/{rid}")
def get_relationship(rid: str, v: Viewer = Depends(viewer)):
    r = tn.get(tn.RELATIONSHIPS, rid)
    mine = {b["bid"] for b in tn.businesses_of(v.uid)}
    if not r or not (v.is_reviewer or {r["buyer_bid"], r["seller_bid"]} & mine):
        raise HTTPException(404, "relationship not found")
    return _rel_view(r, mine)


class RelDecisionIn(BaseModel):
    action: Literal["approve_for_trading", "decline", "pause", "start_review", "resume", "accept_request"]
    reason: str = Field(min_length=3, max_length=500)
    tier: str = "prepaid_small"
    version: int | None = None


@router.post("/tn/relationships/{rid}/decision")
def relationship_decision(rid: str, body: RelDecisionIn, v: Viewer = Depends(viewer)):
    r = tn.get(tn.RELATIONSHIPS, rid)
    mine = {b["bid"] for b in tn.businesses_of(v.uid)}
    if not r or not ({r["buyer_bid"], r["seller_bid"]} & mine):
        raise HTTPException(404, "relationship not found")
    side_bid = r["seller_bid"] if r["seller_bid"] in mine else r["buyer_bid"]
    if body.version is not None and body.version != r.get("version"):
        return _err(409, "version_conflict", "This relationship changed elsewhere; reload it.", current=r)
    state = r["state"]
    target = {"approve_for_trading": "approved_for_trading", "decline": "declined", "pause": "paused",
              "start_review": "under_review", "resume": "under_review", "accept_request": "onboarding"}[body.action]
    path = [target]
    if state == RelState.requested.value and r["seller_bid"] not in mine:
        return _err(403, "not_approver", "Only the seller accepts or declines a connection request.")
    if body.action == "accept_request":
        if r["seller_bid"] not in mine:
            return _err(403, "not_approver", "Only the seller accepts a connection request.")
        if state in ("accepted", "onboarding"):
            return {"relationship": r, "idempotent": True}
        path = ["accepted", "onboarding"]
    if body.action == "approve_for_trading":
        if r["seller_bid"] not in mine:
            return _err(403, "not_approver", "Only the seller decides whether to trade with this buyer.")
        rq = r.get("requirements") or policy.DEFAULT_REQUIREMENTS
        buyer = tn.business(r["buyer_bid"]) or {}
        ready = policy.readiness(body.tier, rq, _checks(r["buyer_bid"]), _model(buyer) if buyer else None,
                                 relationship_reviewed=bool((r.get("human_review") or {}).get("approved")))
        if ready.requires_human_review:
            return _err(409, "human_review_required", ready.note, tier=body.tier, missing=ready.missing)
        if not ready.ready:
            return _err(409, "requirements_not_met", ready.note, tier=body.tier, missing=ready.missing)
        if state == "approved_for_trading":
            if body.tier in r.get("approved_tiers", []):
                return {"relationship": r, "idempotent": True}
            path = []
        elif state in ("onboarding", "paused"):
            path = ["under_review", "approved_for_trading"]
    elif state == target:
        return {"relationship": r, "idempotent": True}
    cur = state
    for nxt in path:
        if not can_transition(cur, nxt):
            return _err(409, "invalid_transition", f"cannot go from {cur} to {nxt}", allowed=sorted(TRANSITIONS.get(cur, set())))
        cur = nxt
    actor = uid_hash(v.uid)

    def apply(d):
        if d["state"] != state:
            raise tn.VersionConflict(d)
        prev = d["state"]
        for nxt in path:
            d["history"] = [*d.get("history", []), {"from": prev, "to": nxt, "by_hash": actor, "by_bid": side_bid,
                                                    "reason": body.reason, "at": tn.iso(),
                                                    **({"tier": body.tier} if nxt == "approved_for_trading" else {})}]
            prev = nxt
        d["state"] = prev
        if body.action == "approve_for_trading":
            d["approved_tiers"] = sorted(set(d.get("approved_tiers", [])) | {body.tier})
        return d
    try:
        saved = tn.mutate(tn.RELATIONSHIPS, rid, apply)
    except tn.VersionConflict as e:
        return _err(409, "version_conflict", "This relationship changed elsewhere; reload it.", current=e.current)
    for bid in (r["buyer_bid"], r["seller_bid"]):
        ledger(bid, "tn.relationship.decision", actor, {"rid": rid, "action": body.action, "from": state, "to": saved["state"],
                                                        "tier": body.tier if body.action == "approve_for_trading" else None,
                                                        "reason": body.reason, "by_bid": side_bid})
    return {"relationship": saved, "idempotent": False}


# ---------------------------------------------------------------- review
OPEN_REVIEW = ("open", "needs_evidence", "escalated", "in_review")


DEMO_REVIEWER_LABEL = "Recorded review"
DEMO_NOTE = "You can review your ready shop and the showcase businesses. Real businesses are reviewed by the Sauda team."


def _demo_visible(b: dict | None, v: Viewer) -> bool:
    """What a non-reviewer may see and act on in the review console: shared demo fixtures and their own sample shop.
    Never a real business, and never another user's sample shop."""
    if not b or b.get("is_fixture") is not True:
        return False
    if b.get("sandbox"):
        return v.uid in (b.get("members") or [])
    return str(b.get("bid") or "").startswith("fx_")


def _review_access(t: dict, v: Viewer) -> tuple[dict, bool]:
    """-> (business, demo). Real reviewers see everything; anyone else only demo data, else 403."""
    b = tn.business(t["bid"]) or {}
    if v.is_reviewer:
        return b, False
    if not _demo_visible(b, v):
        raise HTTPException(403, "Without reviewer access you can act only on showcase businesses and your own ready shop.")
    return b, True


@router.get("/review/me")
def review_me(v: Viewer = Depends(viewer)):
    return {"reviewer": v.is_reviewer, "demo": not v.is_reviewer, "note": None if v.is_reviewer else DEMO_NOTE}


@router.get("/review/queue")
def review_queue(status: str | None = Query(None), v: Viewer = Depends(viewer)):
    rows = [t for t in tn.all_docs(tn.REVIEWS) if (t["status"] == status if status else t["status"] in OPEN_REVIEW)]
    out = []
    for t in sorted(rows, key=lambda t: t.get("created_at") or ""):
        b = tn.business(t["bid"]) or {}
        if not v.is_reviewer and not _demo_visible(b, v):
            continue
        out.append({**t, "display_name": b.get("display_name"), "is_fixture": bool(b.get("is_fixture")),
                    "sandbox": bool(b.get("sandbox")), "demo": not v.is_reviewer,
                    "reason_text": policy.reason_text(t.get("reasons", []))})
    return out


@router.get("/review/tasks/{tid}")
def review_task(tid: str, v: Viewer = Depends(viewer)):
    t = tn.get(tn.REVIEWS, tid)
    if not t:
        raise HTTPException(404, "task not found")
    b, demo = _review_access(t, v)
    checks = tn.checks_of(t["bid"])
    manual = [c for c in checks if c.get("source_kind") == "human_review" and c.get("status") == "pending"]
    summ = summary_of(b) if b else None
    if any(c.get("status") in ("conflict", "failed") for c in checks):
        rec = "Compare the conflicting fields with the official record, then approve or reject that specific claim with a reason."
    elif manual:
        rec = "Open each official portal link below, record what it shows, and attach a screenshot as evidence."
    elif any(c.get("dim") == "representative" and c.get("status") == "pending" for c in checks):
        rec = "Confirm the representative's authority (authorisation letter or confirmation from the owner) before approving identity."
    else:
        rec = (summ or {}).get("next_step") or "Review the evidence and record a decision with a reason."
    return {"task": {**t, "reason_text": policy.reason_text(t.get("reasons", []))},
            "recommended_action": rec,
            "manual_checks": [{**{k: c.get(k) for k in ("check_id", "dim", "check_type", "source_name", "source_url", "summary")},
                               "title": c.get("source_name") or c.get("check_type"),
                               "fields": ["Name shown on the portal", "Status shown", "Address shown", "What you checked and when"]}
                              for c in manual],
            "business": _public_business(b) if b else None, "summary": summ,
            "checks": checks, "evidence": [_public_evidence(e) for e in tn.evidence_of(t["bid"])],
            "relationships": [r for r in tn.relationships_of(t["bid"]) if not demo or r.get("is_fixture") is True],
            "demo": demo, "demo_note": DEMO_NOTE if demo else None}


class ReviewDecisionIn(BaseModel):
    action: Literal["approve_identity", "approve_claim", "reject_claim", "request_evidence", "escalate"]
    scope: str = Field(pattern=r"^(identity|claim:[A-Za-z0-9_\-]+|relationship:[A-Za-z0-9_\-]+)$")
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/review/tasks/{tid}/decision")
def review_decision(tid: str, body: ReviewDecisionIn, v: Viewer = Depends(viewer)):
    t = tn.get(tn.REVIEWS, tid)
    if not t:
        raise HTTPException(404, "task not found")
    _, demo = _review_access(t, v)
    if not body.reason.strip():
        raise HTTPException(422, "a reason is required")
    bid = t["bid"]
    b = _biz_or_404(bid)
    rh = uid_hash(v.uid)
    at = tn.iso()
    if demo:
        return _demo_decision(t, b, body, v, rh, at)
    stamp = {"uid_hash": rh, "decision": body.action, "reason": body.reason.strip(), "at": at}
    case_id = t.get("case_id") or f"case_review_{bid}"
    new_checks: list[dict] = []
    if body.action == "approve_identity":
        if body.scope != "identity":
            raise HTTPException(422, "approve_identity takes scope 'identity'")
        new_checks.append(_check_doc(bid, case_id, dim=Dim.identity, check_type="reviewer_identity", source_kind=SourceKind.human_review,
                                     source_name="Sauda reviewer", status=CheckStatus.verified, reviewer=stamp,
                                     summary=f"A reviewer confirmed the business identity: {body.reason.strip()}"))
    elif body.action in ("approve_claim", "reject_claim"):
        if body.scope.startswith("claim:"):
            c = tn.get(tn.CHECKS, body.scope.split(":", 1)[1])
            if not c or c.get("business_id") != bid:
                raise HTTPException(404, "check not found for this business")
            ok = body.action == "approve_claim"
            new_checks.append(_check_doc(bid, case_id, dim=c["dim"], check_type=f"reviewer_{c['check_type']}",
                                         source_kind=SourceKind.human_review, source_name="Sauda reviewer",
                                         status=CheckStatus.verified if ok else CheckStatus.failed, reviewer=stamp,
                                         evidence_ids=c.get("evidence_ids", []),
                                         summary=(f"A reviewer {'confirmed' if ok else 'rejected'} the {c['dim'].replace('_', ' ')} claim: "
                                                  f"{body.reason.strip()}")))
            if c["dim"] == Dim.representative.value:
                tn.mutate(tn.BUSINESSES, bid, lambda d: {**d, "representative": {**(d.get("representative") or {}),
                                                                                   "authority_status": "verified" if ok else "rejected"}})
                b = tn.business(bid)
        elif body.scope.startswith("relationship:"):
            rid = body.scope.split(":", 1)[1]
            r = tn.get(tn.RELATIONSHIPS, rid)
            if not r or bid not in (r["buyer_bid"], r["seller_bid"]):
                raise HTTPException(404, "relationship not found for this business")
            # Records that a person reviewed the relationship terms; it does not change the relationship state.
            hr = {"approved": body.action == "approve_claim", "reviewer_hash": rh, "reason": body.reason.strip(), "at": at}
            tn.mutate(tn.RELATIONSHIPS, rid, lambda d: {**d, "human_review": hr})
        else:
            raise HTTPException(422, "approve_claim/reject_claim take scope 'claim:<check_id>' or 'relationship:<rid>'")
    for c in new_checks:
        tn.put(tn.CHECKS, c["check_id"], c)
    decision = {"action": body.action, "scope": body.scope, "reason": body.reason.strip(), "reviewer_hash": rh, "at": at}
    s = policy.summarize(_checks(bid), _model(b), evidence=tn.evidence_of(bid))
    rejected = body.action == "reject_claim" and s.category.value == "verification_unsuccessful"

    def apply(d):
        d["decisions"] = [*d.get("decisions", []), decision]
        d["reasons"] = s.review_reasons
        if body.action == "request_evidence":
            d["status"] = "needs_evidence"
        elif body.action == "escalate":
            d["status"] = "escalated"
        elif rejected:
            d["status"] = "rejected"
        elif not s.review_reasons:
            d["status"] = "approved"
        else:
            d["status"] = "in_review"
        return d
    saved = tn.mutate(tn.REVIEWS, tid, apply)
    ledger(bid, "tn.review.decision", f"reviewer:{rh}", {"tid": tid, **decision, "status": saved["status"],
                                                         "category": s.category.value,
                                                         "checks": [c["check_id"] for c in new_checks]})
    return {"task": saved, "summary": summary_of(b), "checks": new_checks}


def _demo_decision(t: dict, b: dict, body: ReviewDecisionIn, v: Viewer, rh: str, at: str) -> dict:
    """A non-reviewer's decision on demo data. Recorded on the task and in the ledger, labelled "Demo reviewer action".
    On the user's own sample shop it takes effect like a review (with a demo-labelled check); on the shared demo
    fixtures it is recorded only, so the shared tasks stay open for every visitor."""
    bid = t["bid"]
    own = bool(b.get("sandbox")) and v.uid in (b.get("members") or [])
    if body.scope.startswith("relationship:"):
        r = tn.get(tn.RELATIONSHIPS, body.scope.split(":", 1)[1])
        if not r or bid not in (r["buyer_bid"], r["seller_bid"]) or r.get("is_fixture") is not True:
            raise HTTPException(403, "Without reviewer access you can act only on showcase relationships.")
    if body.action == "approve_identity" and body.scope != "identity":
        raise HTTPException(422, "approve_identity takes scope 'identity'")
    claim = None
    if body.scope.startswith("claim:"):
        claim = tn.get(tn.CHECKS, body.scope.split(":", 1)[1])
        if not claim or claim.get("business_id") != bid:
            raise HTTPException(404, "check not found for this business")
    decision = {"action": body.action, "scope": body.scope, "reason": body.reason.strip(), "reviewer_hash": rh, "at": at,
                "demo": True, "label": DEMO_REVIEWER_LABEL}
    new_checks: list[dict] = []
    if own and body.action in ("approve_identity", "approve_claim", "reject_claim") and not body.scope.startswith("relationship:"):
        ok = body.action != "reject_claim"
        dim = Dim.identity.value if body.action == "approve_identity" else claim["dim"]
        c = _check_doc(bid, t.get("case_id") or f"case_review_{bid}", dim=dim, check_type="demo_reviewer_" + (
            "identity" if body.action == "approve_identity" else claim["check_type"]), source_kind=SourceKind.simulated_fixture,
            source_name="Owner review (ready shop, not a Sauda reviewer)",
            status=CheckStatus.verified if ok else CheckStatus.failed,
            summary=f"{DEMO_REVIEWER_LABEL}: {'confirmed' if ok else 'rejected'} on a ready shop. {body.reason.strip()}"
                    " (not checked against a government registry yet)")
        c["is_fixture"] = True
        c["sandbox"] = True
        tn.put(tn.CHECKS, c["check_id"], c)
        new_checks.append(c)

    def apply(d):
        d["decisions"] = [*d.get("decisions", []), decision]
        if own:
            if body.action == "request_evidence":
                d["status"] = "needs_evidence"
            elif body.action == "escalate":
                d["status"] = "escalated"
            elif body.action == "reject_claim":
                d["status"] = "rejected"
            else:
                d["status"] = "approved"
        return d
    saved = tn.mutate(tn.REVIEWS, t["tid"], apply)
    ledger(bid, "tn.review.demo_decision", f"demo-reviewer:{rh}", {"tid": t["tid"], **decision, "status": saved["status"],
                                                                   "checks": [c["check_id"] for c in new_checks]})
    note = ("Recorded on your ready shop." if own else
            "Recorded. Showcase businesses stay open so everyone can use the review.")
    return {"task": saved, "summary": summary_of(tn.business(bid) or b), "checks": new_checks, "demo": True,
            "label": DEMO_REVIEWER_LABEL, "note": note}


# ---------------------------------------------------------------- fixtures
@router.post("/tn/fixtures/seed")
def seed_fixtures(reset: bool = Query(False), v: Viewer = Depends(operator)):
    return seed(reset=reset)


# ---------------------------------------------------------------- demo scenario (all simulated)
FX_BUYER = "fx_buyer_srilakshmi"
FX_ANNAPURNA = "fx_seller_annapurna"
FX_DECCAN = "fx_seller_deccan"
FX_METRO = "fx_seller_metro"
FX_PUNE = "fx_seller_pune_dryfruits"
FX_BLR = "fx_seller_blr_homecare"
FX_UIDS = {FX_BUYER: "fx-user-srilakshmi", FX_ANNAPURNA: "fx-user-annapurna", FX_DECCAN: "fx-user-deccan", FX_METRO: "fx-user-metro",
           FX_PUNE: "fx-user-pune", FX_BLR: "fx-user-blr"}


def _fx_listing(categories: list[str], kind: str, districts: list[str] = (), states: list[str] = (), min_rupees: int | None = None,
                notes: str | None = None) -> dict:
    return {"listed": True, "categories": categories,
            "service_area": {"kind": kind, "districts": list(districts), "states": list(states), "basis": "self_declared"},
            "min_order_paise": min_rupees * 100 if min_rupees else None, "notes": notes, "updated_at": tn.iso()}


# Simulated sellers listed in Find suppliers (the service areas are self-declared demo values).
FX_LISTINGS = {
    FX_ANNAPURNA: _fx_listing(["staples", "rice"], "district", ["HYDERABAD"], ["TELANGANA"], 5000, "Showcase listing."),
    FX_DECCAN: _fx_listing(["edible oil"], "state", [], ["TELANGANA"], 10000, "Showcase listing."),
    FX_METRO: _fx_listing(["fmcg", "staples", "packaged foods", "personal care"], "pan_india", min_rupees=15000,
                          notes="Showcase listing."),
    FX_PUNE: _fx_listing(["dry fruits", "spices"], "district", ["PUNE"], ["MAHARASHTRA"], 3000, "Showcase listing."),
    FX_BLR: _fx_listing(["cleaning", "personal care"], "state", [], ["KARNATAKA"], 4000, "Showcase listing."),
}
SIM = "Not checked against a government registry yet"
SIM_NOTE = " (not checked against a government registry yet)"


def _fx_business(bid: str, **kw) -> dict:
    now = tn.iso()
    members = [FX_UIDS[bid]] + (["demo-owner"] if bid == FX_BUYER else [])
    doc = {"bid": bid, "roles": ["seller"], "display_name": "", "legal_name": None, "constitution": None, "category": None,
           "products": [], "gstin": None, "udyam": None, "fssai": None, "cin_llpin": None,
           "address": {"line": "", "city": "Hyderabad", "state": "Telangana", "pin": ""}, "geo": None, "contact": {},
           "contact_hash": None, "representative": {"name": "Showcase Representative", "role": "Proprietor", "authority_status": "self_declared"},
           "brand_claims": [], "requirements": None, "owner_uid": FX_UIDS[bid], "members": members, "is_fixture": True,
           "fixture_label": "Showcase business. Not checked against a government registry yet.", "created_at": now, "updated_at": now, "version": 1}
    doc.update(kw)
    return _index_fields(doc)


def _fx_checks(bid: str, rows: list[tuple]) -> list[dict]:
    out = []
    for n, (dim, kind, status, summary, extra) in enumerate(rows, 1):
        src = {"simulated_fixture": SIM, "preliminary_validation": "GSTIN format and checksum", "device_signal": "Device location (with consent)",
               "self_declared": "Owner declaration"}[kind]
        if kind == "simulated_fixture":
            summary += SIM_NOTE
        out.append(_check_doc(bid, f"case_{bid}_seed", dim=dim, check_type=extra.pop("check_type", f"fixture_{dim}"), source_kind=kind,
                              source_name=src, status=status, summary=summary, check_id=f"chk_{bid}_{n:02d}", **extra))
    return out


def _fx_common(bid: str, gstin: str, name: str, pin: str, city: str = "Hyderabad") -> list[tuple]:
    from sauda_verify.models import FieldCompare as F

    return [
        ("registration", "preliminary_validation", "verified", "GSTIN is well formed and its checksum is valid. This alone says nothing about who runs the business.",
         {"check_type": "gstin_format", "fields": [F(field="gstin", declared=gstin, observed=gstin, match=True).model_dump()]}),
        ("registration", "simulated_fixture", "verified", "GST registration shows Active, regular taxpayer",
         {"check_type": "gst_registry", "observed": {"registration_status": "Active", "taxpayer_type": "Regular"}}),
        ("address", "simulated_fixture", "partially_verified", f"Principal place of business is in {city}, PIN {pin}",
         {"check_type": "gst_address", "fields": [F(field="pin", declared=pin, observed=pin, match=True).model_dump()]}),
        ("operational", "simulated_fixture", "verified", "Return filing is regular for the last 12 months", {"check_type": "gst_filing"}),
    ]


def scenario() -> tuple[list[dict], list[dict]]:
    from sauda_verify.models import FieldCompare as F

    g_b, g_a, g_d, g_m = "36ZZLPS0001S1Z9", "36ZZAPA0002A1Z2", "36ZZDFD0003D1ZA", "36ZZMCM0004M1ZE"
    g_p, g_k = "27ZZPDF0005P1Z8", "29ZZBHC0006B1Z5"
    biz = [
        _fx_business(FX_BUYER, roles=["buyer"], display_name="Sri Lakshmi General Stores", legal_name="Sri Lakshmi General Stores",
                     constitution="Proprietorship", category="Kirana / general store", products=["staples", "rice", "edible oil", "packaged foods"],
                     gstin=g_b, address={"line": "Plot 12, Prakash Nagar, Begumpet", "city": "Hyderabad", "state": "Telangana", "pin": "500016"},
                     geo={"lat": 17.4375, "lng": 78.4483, "accuracy_m": 25, "captured_at": tn.iso(), "consent": True},
                     representative={"name": "Showcase Proprietor", "role": "Proprietor", "authority_status": "pending"}),
        _fx_business(FX_ANNAPURNA, display_name="Annapurna Rice Traders", legal_name="Annapurna Rice Traders", constitution="Proprietorship",
                     category="Rice wholesaler", products=["rice"], gstin=g_a,
                     address={"line": "Godown 12", "city": "Hyderabad", "state": "Telangana", "pin": "500012"}),
        _fx_business(FX_DECCAN, display_name="Deccan Edible Oils", legal_name="Deccan Edible Oils", constitution="Partnership",
                     category="Edible oil distributor", products=["edible oil"], gstin=g_d, fssai="10000000000000", brand_claims=["Fortune"],
                     address={"line": "Unit 3, Industrial Estate", "city": "Hyderabad", "state": "Telangana", "pin": "500018"},
                     representative={"name": "Showcase Partner", "role": "Partner", "authority_status": "self_declared"}),
        _fx_business(FX_METRO, display_name="Metro Distributors", legal_name="Metro Distributors Private Limited", constitution="Private limited company",
                     category="FMCG distributor", products=["staples", "packaged foods", "personal care"], gstin=g_m, linked_supplier_id="metro",
                     address={"line": "Warehouse 7", "city": "Hyderabad", "state": "Telangana", "pin": "500037"},
                     representative={"name": "Showcase Manager", "role": "Sales manager", "authority_status": "self_declared"}),
        _fx_business(FX_PUNE, display_name="Pune Dry Fruits & Spices Co.", legal_name="Pune Dry Fruits & Spices Co.", constitution="Partnership",
                     category="Dry fruits and spices wholesaler", products=["dry fruits", "spices"], gstin=g_p,
                     address={"line": "Shop 4, Market Yard", "city": "Pune", "state": "Maharashtra", "pin": "411002"},
                     representative={"name": "Showcase Partner", "role": "Partner", "authority_status": "self_declared"}),
        _fx_business(FX_BLR, display_name="Bengaluru Home Care Supplies", legal_name="Bengaluru Home Care Supplies", constitution="Proprietorship",
                     category="Cleaning and home care distributor", products=["cleaning", "personal care"], gstin=g_k,
                     address={"line": "Unit 9, Industrial Layout", "city": "Bengaluru", "state": "Karnataka", "pin": "560068"}),
    ]
    for b in biz:
        if b["bid"] in FX_LISTINGS:
            b["listing"] = dict(FX_LISTINGS[b["bid"]])
    checks: list[dict] = []
    checks += _fx_checks(FX_BUYER, _fx_common(FX_BUYER, g_b, "Sri Lakshmi General Stores", "500016") + [
        ("identity", "simulated_fixture", "partially_verified",
         "GST record matches the GSTIN, state and constitution, but the trade name is spelled 'Sri Laxmi General Store'",
         {"check_type": "gst_name_match", "fields": [F(field="trade_name", declared="Sri Lakshmi General Stores", observed="Sri Laxmi General Store", match=False).model_dump(),
                                                    F(field="constitution", declared="Proprietorship", observed="Proprietorship", match=True).model_dump(),
                                                    F(field="state", declared="Telangana", observed="Telangana", match=True).model_dump()]}),
        ("address", "device_signal", "verified", "Phone location shared with consent is about 120 m from the geocoded shop address.",
         {"check_type": "device_location", "observed": {"distance_m": 120, "accuracy_m": 25}}),
        ("representative", "self_declared", "pending", "Proprietor is self-declared; authority to act for the business has not been shown yet.",
         {"check_type": "representative_declaration"}),
    ])
    for bid, g, name, pin, city in ((FX_ANNAPURNA, g_a, "Annapurna Rice Traders", "500012", "Hyderabad"),
                                    (FX_DECCAN, g_d, "Deccan Edible Oils", "500018", "Hyderabad"),
                                    (FX_METRO, g_m, "Metro Distributors Private Limited", "500037", "Hyderabad"),
                                    (FX_PUNE, g_p, "Pune Dry Fruits & Spices Co.", "411002", "Pune"),
                                    (FX_BLR, g_k, "Bengaluru Home Care Supplies", "560068", "Bengaluru")):
        rows = _fx_common(bid, g, name, pin, city) + [
            ("identity", "simulated_fixture", "verified", f"GST legal name matches '{name}'",
             {"check_type": "gst_name_match", "fields": [F(field="legal_name", declared=name, observed=name, match=True).model_dump()]}),
            ("representative", "self_declared", "pending", "Representative is self-declared; authority not yet shown.",
             {"check_type": "representative_declaration"}),
        ]
        if bid == FX_DECCAN:
            rows += [("product_compliance", "simulated_fixture", "verified", "FSSAI licence is listed as valid", {"check_type": "fssai_licence"}),
                     ("distribution_authority", "self_declared", "pending",
                      "Claims to be an authorised Fortune distributor; a reviewer must see the brand's authorisation letter.",
                      {"check_type": "brand_authorisation_claim"})]
        checks += _fx_checks(bid, rows)
    return biz, checks


ID_FIELD = {tn.BUSINESSES: "bid", tn.CHECKS: "check_id", tn.CASES: "case_id", tn.EVIDENCE: "eid", tn.REVIEWS: "tid",
            tn.RELATIONSHIPS: "rid", tn.INVITATIONS: "iid"}


def _fx_reset() -> int:
    """Remove fixture documents only (is_fixture or an fx_ business id). Never touches real businesses."""
    n = 0
    for coll, idf in ID_FIELD.items():
        for d in tn.all_docs(coll, limit=1000):
            owner = str(d.get("bid") or d.get("business_id") or d.get("from_bid") or d.get("buyer_bid") or "")
            if (d.get("is_fixture") is True or owner.startswith("fx_")) and d.get(idf):
                tn.delete(coll, d[idf])
                n += 1
    return n


def seed(reset: bool = False) -> dict:
    removed = _fx_reset() if reset else 0
    biz, checks = scenario()
    created = {"businesses": 0, "checks": 0, "reviews": 0, "relationships": 0}
    listings_added = 0
    for b in biz:
        if tn.create(tn.BUSINESSES, b["bid"], b):
            created["businesses"] += 1
            ledger(b["bid"], "tn.fixture.seeded", "operator", {"bid": b["bid"], "is_fixture": True, "label": "showcase business"})
        elif b.get("listing") and not (tn.business(b["bid"]) or {}).get("listing"):
            # fixtures seeded before listings existed get their simulated listing once; later edits are kept
            tn.mutate(tn.BUSINESSES, b["bid"], lambda d, lst=b["listing"]: {**d, "listing": lst} if d.get("is_fixture") else d)
            listings_added += 1
        tn.create(tn.CASES, f"case_{b['bid']}_seed", {"case_id": f"case_{b['bid']}_seed", "bid": b["bid"], "purpose": "general",
                                                      "status": "open", "is_fixture": True, "created_at": tn.iso()})
    for c in checks:
        c["is_fixture"] = True
        if tn.create(tn.CHECKS, c["check_id"], c):
            created["checks"] += 1
    for b in biz:
        before = tn.get(tn.REVIEWS, f"rv_{b['bid']}")
        _ensure_review(tn.business(b["bid"]), f"case_{b['bid']}_seed", "operator")
        if before is None and tn.get(tn.REVIEWS, f"rv_{b['bid']}"):
            created["reviews"] += 1
    rid = f"rel_{tn.stable_hash([FX_BUYER, FX_METRO])[:16]}"
    now = tn.iso()
    if tn.create(tn.RELATIONSHIPS, rid, {
        "rid": rid, "buyer_bid": FX_BUYER, "seller_bid": FX_METRO, "initiated_by_bid": FX_BUYER, "state": "accepted",
        "categories": ["staples", "packaged foods"], "provenance": "self_declared",
        "shared_fields": ["display_name", "city", "state", "category", "products", "verification_summary"],
        "requirements": policy.DEFAULT_REQUIREMENTS, "approved_tiers": [], "human_review": None, "invitation_id": None,
        "history": [{"from": None, "to": "accepted", "by_hash": "operator", "reason": "existing partner supplier agent linked", "at": now}],
        "is_fixture": True, "created_at": now, "updated_at": now, "version": 1}):
        created["relationships"] += 1
    return {"ok": True, "is_fixture": True, "label": "Showcase businesses. Not checked against a government registry yet.", "removed": removed,
            "created": created, "listings_added": listings_added, "businesses": {b["bid"]: b["display_name"] for b in biz},
            "fixture_users": FX_UIDS, "note": "Act as a fixture user with the operator token and header X-Act-As: <fixture uid>."}


from . import trust_network_discovery  # noqa: E402,F401  (registers /tn/discover, /tn/connect, listing routes on this router)
from . import trust_network_sandbox  # noqa: E402,F401  (registers /tn/sandbox routes on this router)
