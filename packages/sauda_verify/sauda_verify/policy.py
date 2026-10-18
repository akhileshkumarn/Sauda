"""Deterministic verification policy.

Inputs are Check records (plus the declared Business and any open reviewer decisions); outputs are a status
per dimension, an overall category, review-routing reasons, relationship readiness and plain-English text.
There are no probabilities and no numeric scores: every outcome is explained by the rule that produced it.

Key rules
- A dimension rolls up from its checks. Checks past expires_at count as `stale`. A newer human-review check
  on a dimension supersedes the older automated checks on that dimension (that is how a reviewer resolves a
  discrepancy). Among what remains, a `conflict` dominates, then `failed`; otherwise the strongest valid
  source with a positive status wins.
- Simulated fixtures and preliminary validation (format / checksum) never confirm anything: a valid GSTIN
  alone never yields identity_confirmed.
- Relationship readiness is evaluated against the counterparty's requirement tiers. Credit, payment and
  large-order tiers always need a person; nothing here auto-approves them.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from .models import (
    AuthorityStatus,
    Business,
    Category,
    Check,
    CheckStatus,
    Dim,
    DimensionSummary,
    Readiness,
    SourceKind,
    Summary,
)

S, K = CheckStatus, SourceKind

# Strength of a source when several checks agree. Simulated fixtures rank lowest and never confirm.
SOURCE_RANK: dict[SourceKind, int] = {
    K.human_review: 7,
    K.official_registry: 6,
    K.authorised_provider: 5,
    K.uploaded_evidence: 4,
    K.device_signal: 3,
    K.preliminary_validation: 2,
    K.self_declared: 1,
    K.simulated_fixture: 0,
}
# Sources that can confirm identity or registration.
CONFIRMING = {K.official_registry, K.authorised_provider, K.human_review}
# Sources that count as evidence for other dimensions (address, representative, ...).
EVIDENTIAL = CONFIRMING | {K.uploaded_evidence, K.device_signal}
POSITIVE = {S.verified, S.partially_verified}
STRONG_DIMS = {Dim.identity, Dim.registration}
KEY_DIMS = (Dim.identity, Dim.registration, Dim.representative)
CORE_DIMS = (Dim.identity, Dim.registration, Dim.address, Dim.operational, Dim.representative)
# Fallback order when no check is positive: the most informative non-positive status is shown.
FALLBACK_ORDER = [S.pending, S.inconclusive, S.self_declared, S.stale, S.not_applicable]
# Checks that show control of a business channel (phone/email one-time code) but never authority to act for the
# business. They can lift the representative dimension to partially_verified at most, and never satisfy it: authority
# still needs a document reviewed by a person.
CHANNEL_ONLY_CHECKS = {"business_contact_otp"}
CANCELLED_WORDS = {"cancelled", "canceled", "suspended", "inactive", "struck off", "strike off"}

CATEGORY_LABELS = {
    Category.identity_confirmed: "Identity confirmed",
    Category.evidence_reviewed: "Evidence reviewed",
    Category.ready_for_counterparty_review: "Ready for counterparty review",
    Category.additional_review_required: "Partially verified",
    Category.verification_unsuccessful: "Verification unsuccessful",
}

REASON_TEXT = {
    "owner_requested": "The business asked for a manual review.",
    "conflict": "Two sources disagree on a key detail.",
    "failed": "A check did not pass.",
    "field_mismatch": "A declared detail does not match what the source shows (for example a spelling difference).",
    "registration_cancelled": "A registration appears cancelled, suspended or inactive at the source.",
    "representative_authority_unknown": "The person acting for the business has not shown authority to do so.",
    "location_inconclusive": "The device location could not be matched to the declared address.",
    "suspicious_document": "An uploaded document needs a closer look (flagged content or re-used file).",
    "brand_authorisation_unconfirmed": "A claimed brand distributorship has not been confirmed.",
    "source_unavailable": "A source could not be reached; the check needs to be repeated or done manually.",
    "high_value_relationship": "The requested relationship terms (credit, payment or large orders) need a person to review.",
}

DIM_LABELS = {
    Dim.identity: "Business identity",
    Dim.registration: "Registrations (GST, Udyam, MCA)",
    Dim.address: "Business address",
    Dim.operational: "Operating status",
    Dim.representative: "Authorised representative",
    Dim.product_compliance: "Product licences (e.g. FSSAI)",
    Dim.distribution_authority: "Brand distribution authority",
    Dim.trading_references: "Trading references",
    Dim.payment_details: "Payment details",
    Dim.operational_capability: "Operational capability",
}

HIGH_VALUE_WORDS = ("credit", "large", "payment", "bulk")


# ---------------------------------------------------------------- helpers
def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _now(now: datetime | None) -> datetime:
    return now or datetime.now(UTC)


def is_stale(c: Check, now: datetime | None = None) -> bool:
    exp = _parse(c.expires_at)
    return bool(exp and exp <= _now(now))


def effective_status(c: Check, now: datetime | None = None) -> CheckStatus:
    """A positive check past its expiry is shown as stale; negative findings (conflict/failed) do not expire."""
    if c.status in POSITIVE | {S.self_declared, S.pending, S.inconclusive} and is_stale(c, now):
        return S.stale
    if c.check_type in CHANNEL_ONLY_CHECKS and c.status == S.verified:
        return S.partially_verified  # a contact code never verifies anything on its own
    return c.status


def effective_checks(checks: Iterable[Check], now: datetime | None = None) -> list[Check]:
    """Drop automated checks superseded by a newer human-review check on the same dimension, and apply staleness."""
    checks = list(checks)
    latest_review: dict[Dim, datetime] = {}
    for c in checks:
        if c.source_kind == K.human_review:
            t = _parse(c.checked_at) or datetime.min.replace(tzinfo=UTC)
            if c.dim not in latest_review or t > latest_review[c.dim]:
                latest_review[c.dim] = t
    out = []
    for c in checks:
        t = _parse(c.checked_at) or datetime.min.replace(tzinfo=UTC)
        rv = latest_review.get(c.dim)
        if rv is not None and (c.source_kind != K.human_review and t <= rv):
            continue
        if rv is not None and c.source_kind == K.human_review and t < rv:
            continue  # an older reviewer decision is replaced by the newer one
        out.append(c.model_copy(update={"status": effective_status(c, now)}))
    return out


def satisfies(d: DimensionSummary) -> bool:
    """Whether a rolled-up dimension counts as evidenced for categories and requirement checks."""
    if d.status not in POSITIVE or d.source_kind is None:
        return False
    if d.check_type in CHANNEL_ONLY_CHECKS:
        return False  # control of a contact channel is not authority to act for the business
    allowed = CONFIRMING if d.dim in STRONG_DIMS else EVIDENTIAL
    return d.source_kind in allowed


# ---------------------------------------------------------------- dimension rollup
def _pick(cands: list[Check]) -> Check:
    # channel-only checks (contact codes) lose to any other check of the same kind of status
    return max(cands, key=lambda c: (c.check_type not in CHANNEL_ONLY_CHECKS, SOURCE_RANK[c.source_kind],
                                     c.status == S.verified, c.checked_at or ""))


def _ds(dim: Dim, status: CheckStatus, c: Check) -> DimensionSummary:
    return DimensionSummary(dim=dim, status=status, source_kind=c.source_kind, summary=c.summary, checked_at=c.checked_at,
                            check_type=c.check_type)


def rollup_dimension(dim: Dim, checks: list[Check], now: datetime | None = None) -> DimensionSummary:
    """Roll up already-effective checks for one dimension."""
    mine = [c for c in checks if c.dim == dim]
    if not mine:
        status = S.pending if dim in CORE_DIMS else S.not_applicable
        text = "Not checked yet." if status == S.pending else "Not needed for this business so far."
        return DimensionSummary(dim=dim, status=status, source_kind=None, summary=text, checked_at=None)
    for bad in (S.conflict, S.failed):  # a conflict dominates everything, then a failure
        hits = [c for c in mine if c.status == bad]
        if hits:
            return _ds(dim, bad, _pick(hits))
    pos = [c for c in mine if c.status in POSITIVE]
    if pos:
        c = _pick(pos)
        return _ds(dim, c.status, c)
    for st in FALLBACK_ORDER:
        hits = [c for c in mine if c.status == st]
        if hits:
            return _ds(dim, st, _pick(hits))
    c = _pick(mine)  # pragma: no cover - every status is covered above
    return _ds(dim, c.status, c)


def dimensions(checks: Iterable[Check], biz: Business | None = None, now: datetime | None = None) -> dict[Dim, DimensionSummary]:
    eff = effective_checks(checks, now)
    present = {c.dim for c in eff}
    wanted = list(CORE_DIMS)
    if biz is not None:
        if biz.brand_claims:
            wanted.append(Dim.distribution_authority)
        if biz.fssai:
            wanted.append(Dim.product_compliance)
    for d in Dim:
        if d in present and d not in wanted:
            wanted.append(d)
    out = {d: rollup_dimension(d, eff, now) for d in wanted}
    if biz is not None and Dim.distribution_authority in out and out[Dim.distribution_authority].source_kind is None:
        out[Dim.distribution_authority] = out[Dim.distribution_authority].model_copy(
            update={"status": S.pending, "summary": "Brand authorisation claimed; not yet confirmed."})
    return out


# ---------------------------------------------------------------- review routing
def review_reasons(checks: Iterable[Check], biz: Business | None = None, *, evidence: Iterable[dict] = (),
                   requested_tiers: Iterable[str] = (), now: datetime | None = None) -> list[str]:
    """Reasons a person should look at this business. Resolved items drop out because a newer human-review
    check supersedes the automated checks that raised them."""
    eff = effective_checks(checks, now)
    dims = dimensions(checks, biz, now)
    reasons: list[str] = []

    def add(r: str) -> None:
        if r not in reasons:
            reasons.append(r)

    for c in eff:
        if c.status == S.conflict:
            add("conflict")
        if c.status == S.failed and c.source_kind != K.human_review:
            add("failed")
        if c.source_kind != K.human_review and c.status in POSITIVE | {S.inconclusive} and any(f.match is False for f in c.fields):
            add("field_mismatch")
        reg = str((c.observed or {}).get("registration_status") or (c.observed or {}).get("status") or "").lower()
        if reg and any(w in reg for w in CANCELLED_WORDS):
            add("registration_cancelled")
        if c.dim == Dim.address and c.source_kind == K.device_signal and c.status in (S.inconclusive, S.conflict):
            add("location_inconclusive")
        if (c.observed or {}).get("suspicious") or (c.check_type.startswith("document") and c.status == S.conflict):
            add("suspicious_document")
        if not c.available:
            add("source_unavailable")
    for e in evidence:
        if (e.get("guard") or {}).get("blocked") or e.get("reused_by_other_business"):
            add("suspicious_document")
    rep = dims.get(Dim.representative)
    if biz is not None and not (rep and satisfies(rep)):
        if biz.representative.authority_status != AuthorityStatus.verified:
            add("representative_authority_unknown")
    if biz is not None and biz.brand_claims:
        da = dims.get(Dim.distribution_authority)
        if not (da and da.status == S.verified and da.source_kind in CONFIRMING):
            add("brand_authorisation_unconfirmed")
    if any(any(w in t.lower() for w in HIGH_VALUE_WORDS) for t in requested_tiers):
        add("high_value_relationship")
    return reasons


# ---------------------------------------------------------------- overall category
def reviewer_rejected(checks: Iterable[Check], now: datetime | None = None) -> bool:
    return any(c.source_kind == K.human_review and c.status == S.failed and c.dim in KEY_DIMS
               for c in effective_checks(checks, now))


def identity_confirmed(dims: dict[Dim, DimensionSummary]) -> bool:
    d = dims.get(Dim.identity)
    return bool(d and d.status == S.verified and d.source_kind in CONFIRMING)


def category(checks: Iterable[Check], biz: Business | None = None, *, evidence: Iterable[dict] = (),
             now: datetime | None = None) -> Category:
    checks = list(checks)
    if reviewer_rejected(checks, now):
        return Category.verification_unsuccessful
    dims = dimensions(checks, biz, now)
    if any(dims[d].status in (S.conflict, S.failed) for d in KEY_DIMS if d in dims):
        return Category.additional_review_required
    if not identity_confirmed(dims):
        return Category.additional_review_required
    reasons = review_reasons(checks, biz, evidence=evidence, now=now)
    core_ok = all(satisfies(dims[d]) for d in (Dim.registration, Dim.address, Dim.representative))
    no_bad = not any(v.status in (S.conflict, S.failed) for v in dims.values())
    if core_ok and no_bad and not reasons:
        return Category.ready_for_counterparty_review
    eff = effective_checks(checks, now)
    if any(c.dim != Dim.identity and c.status in POSITIVE and c.source_kind in (K.human_review, K.uploaded_evidence)
           for c in eff):
        return Category.evidence_reviewed
    return Category.identity_confirmed


# ---------------------------------------------------------------- relationship readiness
DEFAULT_REQUIREMENTS: dict[str, list[str]] = {
    "prepaid_small": ["identity", "registration"],
    "prepaid_regular": ["identity", "registration", "address"],
    "credit": ["identity", "registration", "address", "representative", "trading_references", "human_review"],
    "large_order": ["identity", "registration", "address", "representative", "human_review"],
}


def needs_person(tier: str, reqs: list[str]) -> bool:
    return "human_review" in reqs or any(w in tier.lower() for w in HIGH_VALUE_WORDS)


def readiness(tier: str, requirements: dict[str, list[str]] | None, checks: Iterable[Check], biz: Business | None = None,
              *, relationship_reviewed: bool = False, now: datetime | None = None) -> Readiness:
    """Does the counterparty meet `tier` of the requirements? Never approves anything by itself: credit,
    payment and large-order tiers are flagged for a person even when every listed check passes."""
    reqs = (requirements or DEFAULT_REQUIREMENTS).get(tier)
    if reqs is None:
        return Readiness(tier=tier, ready=False, missing=[f"unknown tier '{tier}'"], note="This tier is not defined in the requirements.")
    dims = dimensions(checks, biz, now)
    missing: list[str] = []
    for r in reqs:
        if r == "human_review":
            if not relationship_reviewed:
                missing.append("human_review")
            continue
        try:
            d = Dim(r)
        except ValueError:
            missing.append(r)
            continue
        dd = dims.get(d)
        if not (dd and satisfies(dd)) or (dd and dd.status in (S.conflict, S.failed)):
            missing.append(r)
    person = needs_person(tier, reqs)
    if reviewer_rejected(checks, now):
        missing.append("verification_unsuccessful")
    note = ("Credit, payment and large-order terms are the seller's decision after a person reviews them; "
            "Sauda does not approve them automatically." if person else
            "Meets the listed checks for this tier." if not missing else
            "Some required checks are not complete yet.")
    return Readiness(tier=tier, ready=not missing, missing=missing, requires_human_review=person, note=note)


# ---------------------------------------------------------------- plain-English summary
LIMITATIONS_BASE = [
    "Sauda does not give a numeric trust score. Each status comes from a named source and a stated rule.",
    "A valid GSTIN format only shows the number is well formed; it does not show who runs the business.",
    "Missing public information is not a sign of fraud; it means the check needs other evidence.",
    "Verification describes what was checked and when. It is not a guarantee, credit rating or legal opinion.",
]


def outstanding(dims: dict[Dim, DimensionSummary]) -> list[str]:
    out = []
    for d, s in dims.items():
        label = DIM_LABELS[d]
        if s.status in (S.conflict, S.failed):
            out.append(f"{label}: resolve the problem found ({s.status.value}).")
        elif s.status in (S.pending, S.inconclusive, S.self_declared, S.stale):
            out.append(f"{label}: {s.status.value.replace('_', ' ')}, needs evidence or a check.")
        elif s.status in POSITIVE and s.check_type in CHANNEL_ONLY_CHECKS:
            out.append(f"{label}: business contact confirmed; authority to act for the business still needs a "
                       "document reviewed by a person.")
        elif s.status in POSITIVE and not satisfies(s):
            src = SOURCE_PHRASE.get(s.source_kind, "an unconfirmed source") if s.source_kind else "an unconfirmed source"
            out.append(f"{label}: {src} so far; confirm with an authorised source or a reviewer.")
        elif s.status == S.partially_verified:
            out.append(f"{label}: partly verified; a detail still needs to be confirmed.")
    return out


def limitations(checks: Iterable[Check], biz: Business | None = None) -> list[str]:
    out = list(LIMITATIONS_BASE)
    checks = list(checks)
    if any(c.source_kind == K.simulated_fixture for c in checks) or (biz is not None and biz.is_fixture):
        out.insert(0, "Some results are not checked against a government registry yet.")
    if any(not c.available for c in checks):
        out.append("At least one source was unavailable when checked.")
    if any(c.source_kind == K.device_signal for c in checks):
        out.append("Device location shows where a phone was, with the owner's consent; it does not prove ownership of the premises.")
    return out


def next_step(cat: Category, reasons: list[str], dims: dict[Dim, DimensionSummary]) -> str:
    if cat == Category.verification_unsuccessful:
        return "A reviewer could not verify this business. Contact support with corrected details or new evidence."
    if "conflict" in reasons or "field_mismatch" in reasons:
        return "A reviewer will compare the mismatched details. Upload a document that shows the correct name or number."
    if not identity_confirmed(dims):
        return "Run verification with your GST consent, or upload your GST certificate for a reviewer to check."
    if "representative_authority_unknown" in reasons:
        return "Upload a document showing you can act for the business (e.g. partnership deed or authorisation letter)."
    if "brand_authorisation_unconfirmed" in reasons:
        return "Upload the brand's distributor authorisation letter for a reviewer to confirm."
    if reasons:
        return "A reviewer will look at the remaining items."
    if cat == Category.ready_for_counterparty_review:
        return "Share your profile with suppliers or buyers you trade with."
    return "Add evidence for the outstanding items to complete your profile."


def summarize(checks: Iterable[Check], biz: Business | None = None, *, evidence: Iterable[dict] = (),
              now: datetime | None = None) -> Summary:
    checks = list(checks)
    evidence = list(evidence)
    dims = dimensions(checks, biz, now)
    cat = category(checks, biz, evidence=evidence, now=now)
    reasons = review_reasons(checks, biz, evidence=evidence, now=now)
    return Summary(
        category=cat,
        category_label=CATEGORY_LABELS[cat],
        dimensions=list(dims.values()),
        outstanding=outstanding(dims),
        limitations=limitations(checks, biz),
        next_step=next_step(cat, reasons, dims),
        review_reasons=reasons,
    )


def reason_text(reasons: Iterable[str]) -> list[str]:
    return [REASON_TEXT.get(r, r) for r in reasons]


# Plain words for a source that is not yet strong enough, as shown to owners.
SOURCE_PHRASE = {
    SourceKind.simulated_fixture: "not checked against a government registry yet",
    SourceKind.preliminary_validation: "only a format check",
    SourceKind.self_declared: "only the owner's own statement",
    SourceKind.device_signal: "only a device signal",
    SourceKind.uploaded_evidence: "only an uploaded document",
}
