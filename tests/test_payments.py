"""Payment states are honest (contract item 5): issued | claimed (not bank-verified) | mismatch."""
from buyer_agent import store, trust
from buyer_agent.services import orders


def _ordered(env, **kw):
    nid, cid, conf, mid = env.cart_ready(**kw)
    assert env.approve(conf).json()["status"] == "approved"
    o = store.orders_for(nid)[0]
    return nid, o


def _proof(env, oid, utr, amount, payee=None, uid="alice"):
    body = {"utr": utr, "amount_paise": amount, **({"payee_vpa": payee} if payee else {})}
    return env.client.post(f"/payments/{oid}/proof", json=body, headers=env.auth(uid))


def test_payee_always_from_registry_never_from_quote(env):
    nid, cid, conf, _ = env.cart_ready()
    cart = store.cart_draft(cid)
    assert cart["allocations"][0]["payout_vpa"] is None
    assert env.approve(conf).status_code == 200
    o = store.orders_for(nid)[0]
    pm = trust.get_mandate(o["payment_mandate_id"])
    assert pm.body["payee_vpa"] == "sharma.registered@ybl"
    act = orders.payment_action({**o, "payee_vpa": "attacker@paytm"})
    assert act["payee_vpa"] == "sharma.registered@ybl"


def test_utr_typo_is_invalid_and_nothing_persisted(env):
    nid, o = _ordered(env)
    before = list(env.ledger.chains[nid])
    for utr in ("12345", "12345678901a", "", "1234 5678 9012"):
        r = _proof(env, o["order_id"], utr, o["total_paise"])
        assert r.json()["status"] == "invalid"
    assert env.ledger.chains[nid] == before
    assert store.order(o["order_id"])["payment_status"] == "issued"


def test_claimed_is_not_bank_verified(env):
    nid, o = _ordered(env)
    r = _proof(env, o["order_id"], "123456789012", o["total_paise"], payee="SHARMA.registered@ybl").json()
    assert r["status"] == "claimed" and r["bank_verified"] is False
    v = env.client.get(f"/orders/{o['order_id']}", headers=env.auth("alice")).json()
    assert v["payment_status"] == "claimed" and v["payment_mandate"]["bank_verified"] is False
    assert "payment.claimed" in env.ledger.types(nid) and "payment.settled" not in env.ledger.types(nid)


def test_amount_or_payee_mismatch_then_locked(env):
    nid, o = _ordered(env)
    r = _proof(env, o["order_id"], "123456789012", o["total_paise"] + 1).json()
    assert r["status"] == "mismatch" and "amount_mismatch" in r["problems"]
    r = _proof(env, o["order_id"], "123456789012", o["total_paise"]).json()
    assert r["status"] == "mismatch" and r["problems"] == ["previous_mismatch"]


def test_payee_mismatch(env):
    nid, o = _ordered(env)
    r = _proof(env, o["order_id"], "123456789012", o["total_paise"], payee="someone@paytm").json()
    assert r["status"] == "mismatch" and "payee_mismatch" in r["problems"]


def test_utr_reused_across_orders_is_mismatch(env):
    _, o1 = _ordered(env)
    _, o2 = _ordered(env)
    assert _proof(env, o1["order_id"], "111122223333", o1["total_paise"]).json()["status"] == "claimed"
    r = _proof(env, o2["order_id"], "111122223333", o2["total_paise"]).json()
    assert r["status"] == "mismatch" and "utr_reused" in r["problems"]


def test_malformed_money_in_proof_is_422(env):
    _, o = _ordered(env)
    for bad in ("12.5", 12.5, "abc", None, [1]):
        assert env.client.post(f"/payments/{o['order_id']}/proof", json={"utr": "123456789012", "amount_paise": bad},
                               headers=env.auth("alice")).status_code == 422


def test_cancel_revokes_payment_mandate_and_rejects_proof(env):
    nid, o = _ordered(env)
    assert env.client.post(f"/orders/{o['order_id']}/cancel", headers=env.auth("alice")).json()["status"] == "cancelled"
    assert trust.get_mandate(o["payment_mandate_id"]).status == "revoked"
    r = _proof(env, o["order_id"], "123456789012", o["total_paise"]).json()
    assert r["status"] == "invalid" and r["problems"] == ["order_cancelled"]


def test_no_payment_mandate_when_po_not_accepted(env):
    env.FakeSupplier.ack_status = "rejected"
    try:
        nid, cid, conf, _ = env.cart_ready()
        assert env.approve(conf).status_code == 200
        o = store.orders_for(nid)[0]
        assert o["po_status"] == "rejected" and not o.get("payment_mandate_id")
    finally:
        env.FakeSupplier.ack_status = "accepted"


def test_legacy_settled_reads_as_claimed(env):
    _, o = _ordered(env)
    store.update_order(o["order_id"], status="settled", payment_status="settled")
    v = env.client.get(f"/orders/{o['order_id']}", headers=env.auth("alice")).json()
    assert v["payment_status"] == "claimed" and v["status"] == "payment_claimed"
    assert _proof(env, o["order_id"], "123456789012", 1).json()["status"] == "claimed"


def test_demo_amount_is_labelled(env, monkeypatch):
    from buyer_agent import deps
    monkeypatch.setenv("DEMO_PAY_AMOUNT_PAISE", "100")
    deps.settings.cache_clear()
    _, o = _ordered(env)
    v = env.client.get(f"/orders/{o['order_id']}", headers=env.auth("alice")).json()
    assert v["demo_amount"] is True and v["payment_mandate"]["amount_paise"] == 100
    assert v["order_total_paise"] == o["total_paise"] != 100
