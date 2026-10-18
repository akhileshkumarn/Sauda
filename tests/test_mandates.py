import copy

from sauda_trust import mandates

BODY = {
    "kind": "intent", "shop_id": "demo", "budget_paise": 2500000,
    "allowed_supplier_ids": ["metro", "sharma", "quickstock"],
    "lines": [{"gtin": "8901030865278", "qty": 24, "ceiling_paise": 11000, "ceiling_source": "last_paid_x1.10"}],
    "max_advance_pct": 20, "deliver_by": "2026-10-20", "autonomy_tier": 2,
    "expires_at": "2026-10-18T23:59:00+05:30", "nonce": "c1f0",
}


def test_canonical_is_sorted_compact():
    assert mandates.canonical({"b": 1, "a": "₹"}) == '{"a":"₹","b":1}'.encode()


def test_sign_verify_round_trip():
    s = mandates.sign(BODY)
    assert s.body_hash == mandates.body_hash(BODY)
    assert mandates.verify(BODY, s)


def test_tampered_body_fails():
    s = mandates.sign(BODY)
    bad = copy.deepcopy(BODY)
    bad["budget_paise"] = 9_999_999
    assert not mandates.verify(bad, s)


def test_forged_hash_fails():
    s = mandates.sign(BODY)
    bad = copy.deepcopy(BODY)
    bad["max_advance_pct"] = 50
    forged = s.model_copy(update={"body_hash": mandates.body_hash(bad)})
    assert not mandates.verify(bad, forged)


def test_build_record_and_intent_model():
    m = mandates.build("intent", BODY, owner_uid="uid_1", mandate_id="intent_x")
    assert m.status == "active" and m.body["owner_uid"] == "uid_1"
    assert m.signature_valid()
    assert m.intent().mandate_id == "intent_x"
