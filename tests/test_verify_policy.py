"""Deterministic Trust Network policy: dimension rollup, category, review routing, readiness."""
from datetime import UTC, datetime, timedelta

from sauda_verify import policy
from sauda_verify.models import (
    AuthorityStatus,
    Business,
    Category,
    Check,
    Dim,
    FieldCompare,
    Representative,
)
from sauda_verify.models import (
    CheckStatus as S,
)
from sauda_verify.models import (
    SourceKind as K,
)

T0 = datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
_n = iter(range(10_000))


def ck(dim, kind, status, *, at=T0, fields=(), expires=None, observed=None, available=True, check_type="t"):
    return Check(check_id=f"c{next(_n)}", business_id="b", case_id="k", dim=Dim(dim), check_type=check_type, source_kind=K(kind),
                 source_name="src", status=S(status), summary=f"{dim} {status}", fields=list(fields), checked_at=at.isoformat(),
                 expires_at=expires.isoformat() if expires else None, observed=observed or {}, available=available)


def biz(**kw):
    return Business(bid="b", display_name="Shop", representative=Representative(name="R", role="Proprietor",
                                                                                authority_status=kw.pop("auth", AuthorityStatus.verified)), **kw)


def dims(checks, b=None):
    return policy.dimensions(checks, b, now=T0 + timedelta(minutes=5))


def cat(checks, b=None, **kw):
    return policy.category(checks, b, now=T0 + timedelta(minutes=5), **kw)


def confirmed_set(at=T0):
    return [ck("identity", "official_registry", "verified", at=at), ck("registration", "official_registry", "verified", at=at),
            ck("address", "uploaded_evidence", "verified", at=at), ck("representative", "human_review", "verified", at=at)]


# ---------------------------------------------------------------- rollup
def test_strongest_valid_source_wins():
    d = dims([ck("identity", "self_declared", "verified"), ck("identity", "official_registry", "partially_verified"),
              ck("identity", "uploaded_evidence", "verified")])[Dim.identity]
    assert d.source_kind == K.official_registry and d.status == S.partially_verified


def test_conflict_overrides_everything_else():
    checks = [ck("identity", "official_registry", "verified"), ck("identity", "human_review", "verified", at=T0 - timedelta(hours=1)),
              ck("identity", "uploaded_evidence", "conflict")]
    d = dims(checks)[Dim.identity]
    assert d.status == S.conflict
    assert cat(checks + confirmed_set()[1:]) == Category.additional_review_required
    assert "conflict" in policy.review_reasons(checks, now=T0)


def test_conflict_dominates_failed():
    assert dims([ck("registration", "official_registry", "failed"), ck("registration", "uploaded_evidence", "conflict")])[Dim.registration].status == S.conflict


def test_newer_human_review_resolves_older_conflict():
    checks = [ck("identity", "simulated_fixture", "conflict", at=T0), ck("identity", "human_review", "verified", at=T0 + timedelta(minutes=1))]
    d = dims(checks)[Dim.identity]
    assert d.status == S.verified and d.source_kind == K.human_review
    assert "conflict" not in policy.review_reasons(checks, now=T0 + timedelta(minutes=2))


def test_conflict_after_review_still_dominates():
    checks = [ck("identity", "human_review", "verified", at=T0), ck("identity", "official_registry", "conflict", at=T0 + timedelta(minutes=1))]
    assert dims(checks)[Dim.identity].status == S.conflict


def test_expired_check_is_stale():
    c = ck("registration", "official_registry", "verified", expires=T0 + timedelta(minutes=1))
    assert dims([c])[Dim.registration].status == S.stale
    assert policy.is_stale(c, T0 + timedelta(minutes=2)) and not policy.is_stale(c, T0)


def test_unchecked_core_dimension_is_pending():
    d = dims([])
    assert d[Dim.identity].status == S.pending and d[Dim.identity].source_kind is None
    assert Dim.payment_details not in d


# ---------------------------------------------------------------- category
def test_valid_gstin_alone_never_yields_identity_confirmed():
    checks = [ck("identity", "preliminary_validation", "verified"), ck("registration", "preliminary_validation", "verified")]
    assert cat(checks, biz()) == Category.additional_review_required
    assert not policy.identity_confirmed(dims(checks))


def test_simulated_fixtures_never_count_as_official_registry():
    checks = [ck("identity", "simulated_fixture", "verified"), ck("registration", "simulated_fixture", "verified"),
              ck("address", "simulated_fixture", "verified"), ck("representative", "simulated_fixture", "verified")]
    d = dims(checks)
    assert d[Dim.identity].source_kind == K.simulated_fixture
    assert not policy.satisfies(d[Dim.identity])
    assert cat(checks, biz()) == Category.additional_review_required
    r = policy.readiness("prepaid_small", None, checks, biz(), now=T0)
    assert not r.ready and set(r.missing) == {"identity", "registration"}
    assert any("simulated" in x.lower() for x in policy.limitations(checks))


def test_ready_for_counterparty_review():
    assert cat(confirmed_set(), biz()) == Category.ready_for_counterparty_review


def test_identity_confirmed_only():
    checks = [ck("identity", "official_registry", "verified"), ck("registration", "preliminary_validation", "verified")]
    assert cat(checks, biz()) == Category.identity_confirmed


def test_evidence_reviewed():
    checks = [ck("identity", "official_registry", "verified"), ck("address", "uploaded_evidence", "verified")]
    assert cat(checks, biz()) == Category.evidence_reviewed


def test_reviewer_rejection_is_unsuccessful():
    checks = confirmed_set() + [ck("identity", "human_review", "failed", at=T0 + timedelta(minutes=1))]
    assert cat(checks, biz()) == Category.verification_unsuccessful
    assert "verification_unsuccessful" in policy.readiness("prepaid_small", None, checks, biz(), now=T0 + timedelta(minutes=2)).missing


def test_failed_registration_needs_review():
    checks = confirmed_set() + [ck("registration", "official_registry", "failed", at=T0 + timedelta(minutes=1))]
    assert cat(checks, biz()) == Category.additional_review_required


# ---------------------------------------------------------------- review routing
def reasons(checks, b=None, **kw):
    return policy.review_reasons(checks, b, now=T0 + timedelta(minutes=5), **kw)


def test_reason_field_mismatch():
    c = ck("identity", "simulated_fixture", "partially_verified", fields=[FieldCompare(field="trade_name", declared="A", observed="B", match=False)])
    assert "field_mismatch" in reasons([c])


def test_reason_failed_and_cancelled():
    r = reasons([ck("registration", "official_registry", "failed", observed={"registration_status": "Cancelled"})])
    assert {"failed", "registration_cancelled"} <= set(r)


def test_reason_representative_authority_unknown():
    assert "representative_authority_unknown" in reasons([], biz(auth=AuthorityStatus.pending))
    assert "representative_authority_unknown" not in reasons([ck("representative", "human_review", "verified")], biz(auth=AuthorityStatus.pending))


def test_reason_location_inconclusive():
    assert "location_inconclusive" in reasons([ck("address", "device_signal", "inconclusive")])


def test_reason_suspicious_document():
    assert "suspicious_document" in reasons([ck("registration", "uploaded_evidence", "conflict", check_type="document_screening")])
    assert "suspicious_document" in reasons([], evidence=[{"reused_by_other_business": True}])
    assert "suspicious_document" in reasons([], evidence=[{"guard": {"blocked": True}}])


def test_reason_brand_authorisation_unconfirmed():
    b = biz(brand_claims=["Fortune"])
    assert "brand_authorisation_unconfirmed" in reasons([], b)
    assert dims([], b)[Dim.distribution_authority].status == S.pending
    assert "brand_authorisation_unconfirmed" not in reasons([ck("distribution_authority", "human_review", "verified")], b)


def test_reason_source_unavailable():
    assert "source_unavailable" in reasons([ck("registration", "official_registry", "inconclusive", available=False)])


def test_reason_high_value_relationship():
    assert "high_value_relationship" in reasons([], requested_tiers=["credit"])
    assert "high_value_relationship" not in reasons([], requested_tiers=["prepaid_small"])


# ---------------------------------------------------------------- readiness
def test_prepaid_ready_when_requirements_met():
    r = policy.readiness("prepaid_small", None, confirmed_set(), biz(), now=T0)
    assert r.ready and not r.requires_human_review and r.missing == []


def test_credit_never_auto_approved():
    r = policy.readiness("credit", None, confirmed_set() + [ck("trading_references", "uploaded_evidence", "verified")], biz(), now=T0)
    assert r.requires_human_review and "human_review" in r.missing and not r.ready
    r2 = policy.readiness("credit", None, confirmed_set() + [ck("trading_references", "uploaded_evidence", "verified")], biz(),
                          relationship_reviewed=True, now=T0)
    assert r2.requires_human_review  # still flagged for a person; the route never auto-approves it
    assert policy.needs_person("large_order", ["identity"]) and policy.needs_person("payment_terms", [])


def test_reviewer_approving_identity_does_not_approve_relationship():
    checks = [ck("identity", "simulated_fixture", "partially_verified", at=T0),
              ck("identity", "human_review", "verified", at=T0 + timedelta(minutes=1))]
    assert policy.identity_confirmed(dims(checks))
    r = policy.readiness("prepaid_small", None, checks, biz(), now=T0 + timedelta(minutes=2))
    assert not r.ready and r.missing == ["registration"]
    assert not policy.readiness("credit", None, checks, biz(), now=T0 + timedelta(minutes=2)).ready


def test_unknown_tier():
    assert not policy.readiness("nope", None, [], None).ready


# ---------------------------------------------------------------- text
def test_summary_is_plain_english_without_scores():
    s = policy.summarize([ck("identity", "preliminary_validation", "verified")], biz(auth=AuthorityStatus.pending), now=T0)
    assert s.category_label == "Partially verified"
    assert s.next_step and s.outstanding and s.limitations
    dumped = s.model_dump_json().lower()
    assert "score" not in dumped.replace("numeric trust score", "") and "probab" not in dumped
