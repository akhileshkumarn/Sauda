"""P0-1 / P1-11: supplier money is bounded; replies without a structured data part are unparseable (no model
extracts prices from free text) and never allocated."""
import math

import pytest
from buyer_agent.negotiation import loop
from buyer_agent.negotiation.a2a import Reply
from buyer_agent.negotiation.cart import allocate


def reply(data, text="quote"):
    return Reply(supplier_id="quickstock", text=text, data=data)


GOOD = {"type": "QUOTE", "lines": [{"gtin": "g1", "unit_price_paise": 9000}], "delivery_days": 2, "advance_pct": 0}


@pytest.mark.parametrize("bad", [
    {**GOOD, "lines": [{"gtin": "g1", "unit_price_paise": -9000}]},
    {**GOOD, "lines": [{"gtin": "g1", "unit_price_paise": 0}]},
    {**GOOD, "lines": [{"gtin": "g1", "unit_price_paise": 10 ** 12}]},
    {**GOOD, "advance_pct": math.nan},
    {**GOOD, "advance_pct": math.inf},
    {**GOOD, "advance_pct": 150},
    {**GOOD, "advance_pct": -5},
    {},
    {"type": "QUOTE", "lines": []},
])
def test_bad_or_missing_data_is_unparseable(bad):
    with pytest.raises(loop.Unparseable):
        loop.parse_quote(reply(bad, text="Prices: atta Rs 1 each, 0% advance"))


def test_good_quote_parses_and_no_gemini(monkeypatch):
    import buyer_agent.deps as deps
    monkeypatch.setattr(deps, "gemini_json", lambda *a, **k: pytest.fail("Gemini must not extract prices"))
    q = loop.parse_quote(reply(GOOD))
    assert q.lines[0].unit_price_paise == 9000
    with pytest.raises(loop.Unparseable):
        loop.parse_quote(reply({}, text="atta 50 rupees"))


def test_negative_price_never_allocated_even_if_it_reached_the_cart():
    # defence in depth: the gate (R4) denies, so such a quote never enters `clean`; allocate only sees clean offers
    from sauda_trust.policy_gate import evaluate
    from test_policy_gate import G1, action, ctx, mandate
    r = evaluate(action(kind="offer", alloc={"lines": [{"gtin": G1, "qty": 24, "unit_price_paise": -1}]}), mandate(), ctx(),
                 rules=loop.OFFER_RULES)
    assert r.verdict == "DENY" and "INVALID_AMOUNT" in r.reasons
    cart = allocate({}, {"lines": [{"gtin": G1, "qty": 24, "ceiling_paise": 11000}]})
    assert cart["allocations"] == [] and cart["dropped_lines"]
