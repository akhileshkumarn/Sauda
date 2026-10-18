"""Owner auth: 401 without a valid token; 403 for another shop's or another owner's records."""
import pytest
from buyer_agent import store


def test_401_without_or_with_bad_token(env):
    c = env.client
    for path in ("/negotiations/x", "/orders/x", "/mandates/x", "/confirm/x", "/products", "/shops/demo/overview"):
        assert c.get(path).status_code == 401
        assert c.get(path, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.post("/confirm", json={"confirmation_id": "x", "approved": True}).status_code == 401
    assert c.post("/chat", json={"shop_id": "demo", "message": "hi"}).status_code == 401


def test_operator_token_disabled_without_env(env, monkeypatch):
    from buyer_agent import deps
    monkeypatch.delenv("DEMO_OWNER_TOKEN")
    monkeypatch.setenv("AUTH_MODE", "demo")
    deps.settings.cache_clear()
    assert deps.settings().demo_owner_token == ""
    assert env.client.get("/products", headers={"Authorization": "Bearer sauda-demo-owner"}).status_code == 401


@pytest.fixture
def bob_records(env):
    nid, cid, conf, mid = env.cart_ready(uid="bob", shop="shopB")
    assert env.approve(conf, uid="bob").status_code == 200
    oid = store.orders_for(nid)[0]["order_id"]
    return nid, cid, conf, mid, oid


def test_403_cross_shop_identifiers(env, bob_records):
    nid, cid, conf, mid, oid = bob_records
    a, c = env.auth("alice"), env.client
    assert c.get(f"/negotiations/{nid}", headers=a).status_code == 403
    assert c.get(f"/mandates/{mid}", headers=a).status_code == 403
    assert c.post(f"/mandates/{mid}/revoke", headers=a).status_code == 403
    assert c.get(f"/orders/{oid}", headers=a).status_code == 403
    assert c.post(f"/orders/{oid}/cancel", headers=a).status_code == 403
    assert c.post(f"/payments/{oid}/proof", json={"utr": "123456789012", "amount_paise": 1}, headers=a).status_code == 403
    assert c.get(f"/confirm/{conf}", headers=a).status_code == 403
    assert c.post("/confirm", json={"confirmation_id": conf, "approved": False}, headers=a).status_code == 403
    assert c.get("/shops/shopB/overview", headers=a).status_code == 403
    assert c.post("/chat", json={"shop_id": "shopB", "message": "10 atta"}, headers=a).status_code == 403
    # the owner still can
    assert c.get(f"/orders/{oid}", headers=env.auth("bob")).status_code == 200


def test_403_other_owner_on_shared_demo_shop(env):
    nid, cid, conf, mid = env.cart_ready(uid="alice", shop="demo")
    b, c = env.auth("bob"), env.client
    assert c.get(f"/negotiations/{nid}", headers=b).status_code == 403
    assert c.get(f"/mandates/{mid}", headers=b).status_code == 403
    assert c.post(f"/mandates/{mid}/revoke", headers=b).status_code == 403
    assert c.get(f"/confirm/{conf}", headers=b).status_code == 403
    assert c.post("/confirm", json={"confirmation_id": conf, "approved": True}, headers=b).status_code == 403
    assert store.orders_for(nid) == []


def test_mandate_cannot_be_attached_to_another_shops_negotiation(env):
    victim = store.create_negotiation("shopB", "bob")
    r = env.client.post("/mandates", json={"kind": "intent", "body": env.mandate_body("demo"),
                                           "negotiation_id": victim["negotiation_id"]}, headers=env.auth("alice"))
    assert r.status_code == 200
    assert r.json()["negotiation_id"] != victim["negotiation_id"]
    assert store.negotiation(victim["negotiation_id"])["intent_mandate_id"] is None


def test_shop_lock_409_for_second_owner_then_stale_takeover(env):
    nid, *_ = env.cart_ready(uid="alice", shop="demo")
    r = env.client.post("/chat", json={"shop_id": "demo", "message": "10 atta"}, headers=env.auth("bob"))
    assert r.status_code == 409 and "Another owner is negotiating" in r.json()["detail"]
    r = env.client.post("/mandates", json={"kind": "intent", "body": env.mandate_body("demo")}, headers=env.auth("bob"))
    assert r.status_code == 409
    store._update("negotiations", nid, {"updated_at": "2020-01-01T00:00:00+00:00"})  # stale: no activity for 15 min
    r = env.client.post("/mandates", json={"kind": "intent", "body": env.mandate_body("demo")}, headers=env.auth("bob"))
    assert r.status_code == 200 and r.json()["negotiation_id"] != nid
