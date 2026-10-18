"""Draft quantities are the owner's (contract item 1): uplift is only a suggestion; budget parsed; ambiguity
returns clarifications. Uses the deterministic fallback parser (Gemini disabled)."""
from datetime import datetime

import pytest
from buyer_agent.services import demand


@pytest.fixture
def offline(env, monkeypatch):
    def no_gemini(*a, **k):
        raise RuntimeError("offline")
    monkeypatch.setattr(demand, "gemini_json", no_gemini)
    return env


def by_name(d):
    return {l["name"]: l for l in d["lines"]}


@pytest.mark.parametrize("text,paise", [
    ("keep under 8000", 800000), ("keep under ₹8,000", 800000), ("budget 8k", 800000), ("8000 ke andar", 800000),
    ("max rs 2500.50", 250050), ("10 atta, 20 salt", None),
])
def test_budget_parse(text, paise):
    assert demand.parse_budget_paise(text)[0] == paise


def test_messy_request_keeps_owner_qty_and_budget(offline):
    d = demand.build_draft("demo", "10 aashirvad ata, 20 salt, oil 12, maggi 2 dozen, keep under 8000")
    q = {l["owner_words"]: l for l in d["lines"]}
    assert q["10 aashirvad ata"]["qty"] == 10 and q["10 aashirvad ata"]["qty_source"] == "owner"
    assert q["10 aashirvad ata"]["name"] == "Aashirvaad Superior MP Atta" and q["10 aashirvad ata"]["confidence"] == "high"
    assert q["oil 12"]["qty"] == 12 and q["oil 12"]["confidence"] == "low" and q["oil 12"]["alternatives"]
    assert q["maggi 2 dozen"]["qty"] == 24 and q["20 salt"]["qty"] == 20
    assert d["stated_budget_paise"] == 800000 == d["suggested_budget_paise"] == d["suggested_mandate"]["budget_paise"]
    assert {c["owner_words"] for c in d["clarifications"]} >= {"oil 12", "20 salt"}
    assert all(c["options"] and c["question"] for c in d["clarifications"])
    assert all(l["qty"] == l["requested_qty"] for l in d["lines"])
    assert [l["qty"] for l in d["suggested_mandate"]["lines"]] == [l["qty"] for l in d["lines"]]


def test_hinglish(offline):
    d = demand.build_draft("demo", "das packet Aashirvaad atta 1 kilo aur bees Tata namak")
    n = by_name(d)
    assert n["Aashirvaad Superior MP Atta"]["qty"] == 10 and n["Salt LITE"]["qty"] == 20
    assert d["clarifications"] == [] and d["stated_budget_paise"] is None


def test_ambiguous_12_oil(offline):
    d = demand.build_draft("demo", "12 oil")
    (l,) = d["lines"]
    assert l["qty"] == 12 and l["confidence"] == "low" and len(l["alternatives"]) >= 2
    assert d["clarifications"][0]["owner_words"] == "12 oil"


def test_no_number_is_inferred(offline):
    (l,) = demand.build_draft("demo", "some parachute coconut oil")["lines"]
    assert l["qty_source"] == "inferred" and l["requested_qty"] is None and l["qty"] == demand.DEFAULT_QTY


def test_festival_uplift_is_suggestion_only(offline, monkeypatch):
    class D(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 25, 12, 0, tzinfo=tz)
    monkeypatch.setattr(demand, "datetime", D)
    (l,) = demand.build_draft("demo", "10 parachute coconut oil")["lines"]
    assert l["qty"] == 10 and l["suggested_qty"] == 13 and "Diwali" in l["suggestion_reason"]


def test_fragment_without_product_is_unmatched_not_guessed(offline, monkeypatch):
    d = demand.build_draft("demo", "prepare tomorrow's restock, 10 packets of 1")
    assert d["lines"] == [] and "10 packets of 1" in d["unmatched"]
    # same when the model guesses a product for words that name none
    prods = demand.store.products()
    soap = next(g for g, p in prods.items() if p["name"].startswith("Johnson"))
    oil = next(g for g, p in prods.items() if p["name"] == "Refined Sunflower Oil")
    fake = demand.ParsedRequest(lines=[demand.ReqLine(gtin=soap, qty=10, owner_words="10 packets of 1", confidence="low"),
                                       demand.ReqLine(gtin=oil, qty=12, owner_words="oil 12", confidence="low"),
                                       demand.ReqLine(gtin=oil, qty=2, owner_words="दो तेल", confidence="low")])
    monkeypatch.setattr(demand, "gemini_json", lambda *a, **k: fake.model_copy(deep=True))
    p = demand.parse_request("whatever", prods)
    assert [l.owner_words for l in p.lines] == ["oil 12", "दो तेल"] and p.unmatched == ["10 packets of 1"]


@pytest.mark.parametrize("words", ["10 aashirvad ata", "bees Tata namak", "maggi 2 dozen", "chai patti 5", "12 oil"])
def test_names_product_accepts_real_items(offline, words):
    prods = demand.store.products()
    p = demand._fallback_parse(words, prods)
    assert p.lines and demand.names_product(words, prods[p.lines[0].gtin])
