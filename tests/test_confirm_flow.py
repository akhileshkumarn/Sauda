"""Owner approval is enforced by the backend: atomic answer, cart-hash binding, all twelve rules re-run."""
import threading

from buyer_agent import store, trust


def _post_gate(env, nid):
    return [e["payload"] for e in env.ledger.chains[nid]
            if e["type"] == "gate.decision" and e["payload"].get("stage") == "post_confirmation"]


def test_approve_places_one_order_and_reruns_all_twelve_rules(env):
    nid, cid, conf, _ = env.cart_ready()
    r = env.approve(conf)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    os_ = store.orders_for(nid)
    assert len(os_) == 1 and os_[0]["payment_mandate_id"] and os_[0]["po_status"] == "accepted"
    gates = _post_gate(env, nid)
    assert gates and {x["rule"] for x in gates[0]["results"]} == {f"R{i}" for i in range(1, 13)}
    assert gates[0]["verdict"] == "ALLOW"
    assert len(env.sends) == 1


def test_double_approve_is_409_and_never_two_orders(env):
    nid, _, conf, _ = env.cart_ready()
    assert env.approve(conf).status_code == 200
    r = env.approve(conf)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "already_answered"
    assert len(store.orders_for(nid)) == 1 and len(env.sends) == 1


def test_approve_after_decline_is_409(env):
    nid, _, conf, _ = env.cart_ready()
    assert env.approve(conf, approved=False).json() == {"status": "declined"}
    r = env.approve(conf)
    assert r.status_code == 409
    assert store.orders_for(nid) == [] and env.sends == []


def test_concurrent_approves_create_one_order_and_one_po(env):
    nid, _, conf, _ = env.cart_ready()
    codes, barrier = [], threading.Barrier(4)

    def go():
        barrier.wait()
        codes.append(env.approve(conf).status_code)

    ts = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(codes) == [200, 409, 409, 409]
    assert len(store.orders_for(nid)) == 1 and len(env.sends) == 1


def test_expired_mandate_at_approval_is_denied_server_side(env, monkeypatch):
    nid, _, conf, mid = env.cart_ready()
    # the mandate expires between the confirmation being issued and the owner tapping approve
    rec = trust.get_mandate(mid)
    expired = rec.model_copy(update={"body": {**rec.body, "expires_at": "2020-01-01T00:00:00+05:30"}})
    real = trust.get_mandate
    monkeypatch.setattr(trust, "get_mandate", lambda m: expired if m == mid else real(m))
    r = env.approve(conf)
    assert r.status_code == 200 and r.json()["status"] == "denied" and "MANDATE_INVALID" in r.json()["reasons"]
    assert store.orders_for(nid) == [] and env.sends == []
    assert store.confirmation(conf)["status"] == "denied"
    assert env.approve(conf).status_code == 409


def test_revoked_mandate_at_approval_is_denied(env):
    nid, _, conf, mid = env.cart_ready()
    trust.mark_mandate(mid, "revoked")
    r = env.approve(conf)
    assert r.json()["status"] == "denied" and {"MANDATE_INVALID", "REVOKED"} <= set(r.json()["reasons"])
    assert store.orders_for(nid) == []


def test_revoke_route_then_approve_is_rejected(env):
    nid, _, conf, mid = env.cart_ready()
    assert env.client.post(f"/mandates/{mid}/revoke", headers=env.auth("alice")).status_code == 200
    r = env.approve(conf)
    assert r.status_code == 409 and store.orders_for(nid) == []  # negotiation cancelled -> confirmation stale


def test_kill_switch_at_approval_is_denied(env):
    nid, _, conf, _ = env.cart_ready()
    store.update_shop("demo", kill_switch=True)
    r = env.approve(conf)
    assert r.json()["status"] == "denied" and "REVOKED" in r.json()["reasons"]
    assert store.orders_for(nid) == []


def test_cart_changed_after_confirmation_fails_approval(env):
    nid, cid, conf, _ = env.cart_ready()
    cart = store.cart_draft(cid)
    cart["allocations"][0]["lines"][0]["unit_price_paise"] -= 1  # any change to what the owner saw
    store._set("cart_drafts", cid, cart)
    r = env.approve(conf)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "cart_changed"
    assert store.orders_for(nid) == [] and store.confirmation(conf)["status"] == "stale"


def test_place_order_denies_cart_that_differs_from_signed_cart_mandate(env):
    from buyer_agent.services import orders
    nid, cid, conf, _ = env.cart_ready()
    n = store.negotiation(nid)
    from buyer_agent.services.confirm import _cart_mandate_body
    cm = trust.create_mandate("cart", _cart_mandate_body(n, store.cart_draft(cid), {}), "alice")
    store.update_negotiation(nid, cart_mandate_id=cm.mandate_id)
    cart = store.cart_draft(cid)
    cart["allocations"][0]["lines"][0]["qty"] += 100
    store._set("cart_drafts", cid, cart)
    assert orders.place(nid, cid) == {"status": "denied", "reasons": ["CART_CHANGED"]}
    assert env.sends == []


def test_place_order_tool_without_approval_needs_confirmation(env):
    from buyer_agent.agent import tools
    nid, cid, conf, _ = env.cart_ready()
    res = tools.place_order(nid, cid)
    assert res["status"] == "confirmation_required" and "OWNER_APPROVAL" in res["reasons"]
    assert store.orders_for(nid) == [] and env.sends == []


def test_duplicate_place_order_is_r11_duplicate(env):
    from buyer_agent.agent import tools
    nid, cid, conf, _ = env.cart_ready()
    assert env.approve(conf).status_code == 200
    res = tools.place_order(nid, cid)
    assert res["status"] == "denied" and "DUPLICATE" in res["reasons"]  # (and MANDATE_INVALID: intent consumed)
    assert len(store.orders_for(nid)) == 1 and len(env.sends) == 1


def test_confirmation_for_new_cart_supersedes_old(env):
    from buyer_agent.services import confirm
    nid, cid, conf, _ = env.cart_ready()
    cart = store.cart_draft(cid)
    cart["allocations"][0]["lines"][0]["unit_price_paise"] -= 5
    store._set("cart_drafts", cid, cart)
    c2 = confirm.request(nid, cid, session_id="s", user_id="alice", mode="direct")
    assert c2["confirmation_id"] != conf and store.confirmation(conf)["status"] == "superseded"
    assert env.approve(conf).status_code == 409
    assert env.approve(c2["confirmation_id"]).json()["status"] == "approved"
