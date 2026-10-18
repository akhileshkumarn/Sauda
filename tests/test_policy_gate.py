from datetime import UTC, datetime

import pytest
from sauda_trust.mandates import IntentMandate
from sauda_trust.policy_gate import Action, GateContext, evaluate

NOW = datetime(2026, 10, 17, 15, 0, tzinfo=UTC)  # 20:30 IST
G1, G2 = "8901030865278", "8901725181222"


def mandate(**kw):
    body = dict(shop_id="demo", budget_paise=500000, allowed_supplier_ids=["metro", "sharma", "quickstock"],
                lines=[{"gtin": G1, "qty": 24, "ceiling_paise": 11000}, {"gtin": G2, "qty": 10, "ceiling_paise": 5000}],
                max_advance_pct=20, deliver_by="2026-10-20", autonomy_tier=2,
                expires_at="2026-10-18T23:59:00+05:30", nonce="n1")
    body.update(kw)
    return IntentMandate(**body)


def ctx(**kw):
    base = dict(
        now=NOW, mandate_id="intent_1", mandate_status="active", signature_valid=True,
        suppliers={"sharma": {"status": "allowlisted", "fingerprint": "fp_sharma", "payout_vpa": "sharma.traders@ybl"},
                   "quickstock": {"status": "allowlisted", "fingerprint": "fp_qs", "payout_vpa": "quickstock@ybl"}},
        card_fingerprints={"sharma": "fp_sharma", "quickstock": "fp_qs"},
        guard_verdicts={"sharma": {"blocked": False}, "quickstock": {"blocked": False}},
        forecast={G1: 24, G2: 10}, reference_prices={G1: 10500, G2: 4800},
        seen_idempotency_keys={"old_key"}, owner_confirmed=True,
    )
    base.update(kw)
    return GateContext(**base)


def action(**kw):
    alloc = dict(supplier_id="sharma", lines=[{"gtin": G1, "qty": 24, "unit_price_paise": 10000},
                                              {"gtin": G2, "qty": 10, "unit_price_paise": 4500}],
                 delivery_days=2, advance_pct=0, payout_vpa="sharma.traders@ybl")
    alloc.update(kw.pop("alloc", {}))
    base = dict(kind="place_order", negotiation_id="neg_1", allocations=[alloc], idempotency_key="k1")
    base.update(kw)
    return Action(**base)


def failing(report):
    return {(r.rule, r.verdict, r.reason) for r in report.results if r.verdict != "ALLOW"}


def test_clean_pass_all_twelve():
    r = evaluate(action(), mandate(), ctx())
    assert r.verdict == "ALLOW" and len(r.results) == 12 and r.mandate_id == "intent_1"


@pytest.mark.parametrize("name,a,m,c,expected", [
    ("R1 expired", action(), mandate(expires_at="2026-10-17T10:00:00+05:30"), ctx(), ("R1", "DENY", "MANDATE_INVALID")),
    ("R2 fingerprint", action(), mandate(), ctx(card_fingerprints={"sharma": "changed"}), ("R2", "DENY", "SUPPLIER_UNKNOWN")),
    ("R3 budget", action(), mandate(budget_paise=100000), ctx(), ("R3", "DENY", "OVER_BUDGET")),
    ("R4 ceiling", action(alloc={"lines": [{"gtin": G1, "qty": 24, "unit_price_paise": 11500}]}), mandate(), ctx(), ("R4", "DENY", "OVER_CEILING")),
    ("R5 advance", action(alloc={"advance_pct": 50}), mandate(), ctx(), ("R5", "DENY", "ADVANCE_TOO_HIGH")),
    ("R6 late", action(alloc={"delivery_days": 7}), mandate(), ctx(), ("R6", "CONFIRM", "LATE_DELIVERY")),
    ("R7 too cheap", action(alloc={"lines": [{"gtin": G1, "qty": 24, "unit_price_paise": 4000}]}), mandate(), ctx(), ("R7", "CONFIRM", "ANOMALY")),
    ("R8 payee", action(alloc={"payout_vpa": "qs.payments77@paytm"}), mandate(), ctx(), ("R8", "DENY", "PAYEE_MISMATCH")),
    ("R9 guard", action(), mandate(), ctx(guard_verdicts={"sharma": {"blocked": True}}), ("R9", "DENY", "GUARD_BLOCKED")),
    ("R10 approval", action(), mandate(), ctx(owner_confirmed=False), ("R10", "CONFIRM", "OWNER_APPROVAL")),
    ("R11 duplicate", action(idempotency_key="old_key"), mandate(), ctx(), ("R11", "DENY", "DUPLICATE")),
    ("R12 kill switch", action(), mandate(), ctx(kill_switch=True), ("R12", "DENY", "REVOKED")),
], ids=lambda v: v if isinstance(v, str) else "")
def test_rule_fails(name, a, m, c, expected):
    r = evaluate(a, m, c)
    assert failing(r) == {expected}
    assert r.verdict == expected[1]
    assert expected[2] in r.reasons
