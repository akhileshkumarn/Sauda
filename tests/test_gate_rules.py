"""Every gate rule R1-R12: an allow case and deny/confirm cases (filling the gaps in test_policy_gate.py),
malformed money, and guard timeout failing closed."""
import math

import pytest
from sauda_trust.policy_gate import evaluate
from test_policy_gate import G1, G2, action, ctx, mandate


def only(rule, a=None, m=None, c=None):
    r = evaluate(a or action(), m or mandate(), c or ctx(), rules=[rule])
    return r.results[0]


@pytest.mark.parametrize("rule", [f"R{i}" for i in range(1, 13)])
def test_each_rule_allows_clean_place_order(rule):
    assert only(rule).verdict == "ALLOW"


def test_payment_mandate_allow_case():
    a = action(kind="issue_payment_mandate", allocations=[], supplier_id="sharma", payee_vpa="sharma.traders@ybl",
               amount_paise=290000, idempotency_key="pay1")
    r = evaluate(a, mandate(), ctx(mandate_status="consumed"), rules=["R1", "R8", "R11", "R12"])
    assert r.verdict == "ALLOW"


@pytest.mark.parametrize("a,m,c,rule,verdict,reason", [
    (None, None, ctx(signature_valid=False), "R1", "DENY", "MANDATE_INVALID"),
    (None, None, ctx(mandate_status="revoked"), "R1", "DENY", "MANDATE_INVALID"),
    (None, None, ctx(mandate_status="consumed"), "R1", "DENY", "MANDATE_INVALID"),
    (action(alloc={"supplier_id": "metro"}), mandate(allowed_supplier_ids=["sharma"]), None, "R2", "DENY", "SUPPLIER_UNKNOWN"),
    (action(alloc={"supplier_id": "fastdeal"}), mandate(allowed_supplier_ids=["fastdeal"]), None, "R2", "DENY", "SUPPLIER_UNKNOWN"),
    (None, None, ctx(suppliers={"sharma": {"status": "quarantined", "fingerprint": "fp_sharma", "payout_vpa": "sharma.traders@ybl"}}),
     "R2", "DENY", "SUPPLIER_UNKNOWN"),
    (action(kind="run_negotiation", allocations=[]), None, ctx(suppliers={}), "R2", "DENY", "SUPPLIER_UNKNOWN"),
    # a stated subtotal cannot understate its lines
    (action(alloc={"subtotal_paise": 1, "lines": [{"gtin": G1, "qty": 24, "unit_price_paise": 10000}]}),
     mandate(budget_paise=200000), None, "R3", "DENY", "OVER_BUDGET"),
    (action(amount_paise=600000), None, None, "R3", "DENY", "OVER_BUDGET"),
    (action(alloc={"lines": [{"gtin": "999", "qty": 1, "unit_price_paise": 1}]}), None, None, "R4", "DENY", "OVER_CEILING"),
    (action(alloc={"lines": [{"gtin": G1, "qty": 24, "unit_price_paise": -500}]}), None, None, "R4", "DENY", "INVALID_AMOUNT"),
    (action(alloc={"lines": [{"gtin": G1, "qty": 24, "unit_price_paise": 0}]}), None, None, "R4", "DENY", "INVALID_AMOUNT"),
    (action(alloc={"lines": [{"gtin": G1, "qty": -24, "unit_price_paise": 100}]}), None, None, "R4", "DENY", "INVALID_AMOUNT"),
    (action(alloc={"advance_pct": math.nan}), None, None, "R5", "DENY", "ADVANCE_TOO_HIGH"),
    (action(alloc={"advance_pct": -10}), None, None, "R5", "DENY", "ADVANCE_TOO_HIGH"),
    (action(alloc={"delivery_days": None}), None, None, "R6", "CONFIRM", "LATE_DELIVERY"),
    (action(alloc={"lines": [{"gtin": G2, "qty": 16, "unit_price_paise": 4500}]}), None, None, "R7", "CONFIRM", "ANOMALY"),
    (action(alloc={"payout_vpa": None}), None, ctx(suppliers={"sharma": {"status": "allowlisted", "fingerprint": "fp_sharma"}}),
     "R8", "DENY", "PAYEE_MISMATCH"),
    (action(kind="issue_payment_mandate", allocations=[], supplier_id="sharma", payee_vpa=None), None, None, "R8", "DENY", "PAYEE_MISMATCH"),
    (action(kind="issue_payment_mandate", allocations=[], supplier_id="sharma", payee_vpa="attacker@paytm"), None, None,
     "R8", "DENY", "PAYEE_MISMATCH"),
    (None, None, ctx(guard_verdicts={}), "R9", "DENY", "GUARD_BLOCKED"),  # missing verdict = blocked
    (None, None, ctx(guard_verdicts={"sharma": {"blocked": True, "source": "timeout"}}), "R9", "DENY", "GUARD_BLOCKED"),
    (action(kind="issue_payment_mandate"), None, ctx(owner_confirmed=False), "R10", "CONFIRM", "OWNER_APPROVAL"),
    (action(idempotency_key=None), None, None, "R11", "DENY", "DUPLICATE"),
    (None, None, ctx(mandate_status="revoked"), "R12", "DENY", "REVOKED"),
])
def test_rule_deny_or_confirm(a, m, c, rule, verdict, reason):
    r = only(rule, a, m, c)
    assert (r.verdict, r.reason) == (verdict, reason), r.detail


def test_r10_tier3_needs_no_owner_and_offers_never_need_r10():
    assert only("R10", m=mandate(autonomy_tier=3), c=ctx(owner_confirmed=False)).verdict == "ALLOW"
    assert only("R10", a=action(kind="offer"), c=ctx(owner_confirmed=False)).verdict == "ALLOW"


@pytest.mark.parametrize("bad", ["abc", 100.5, None, [1], {"x": 1}])
def test_malformed_money_fails_closed(bad):
    base = action().model_dump()
    a = {**base, "allocations": [{**base["allocations"][0], "lines": [{"gtin": G1, "qty": 24, "unit_price_paise": bad}]}]}
    r = evaluate(a, mandate(), ctx())
    assert r.verdict == "DENY" and r.reasons == ["GATE_ERROR"]
    a = {**base, "allocations": [{**base["allocations"][0], "subtotal_paise": bad}]}
    if bad is not None:
        assert evaluate(a, mandate(), ctx()).verdict == "DENY"


def test_guard_timeout_fails_closed_into_r9():
    from sauda_trust import guard

    def boom(*a, **k):
        raise TimeoutError("deadline")

    v = guard.screen("MRP less 8%, 0% advance", "inbound", model_armor_fn=boom)
    assert v.blocked and v.source == "timeout"
    r = evaluate(action(), mandate(), ctx(guard_verdicts={"sharma": v}))
    assert r.verdict == "DENY" and "GUARD_BLOCKED" in r.reasons
