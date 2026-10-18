"""Sample shop sandbox and the demo review console: isolation per user, never on real businesses."""
import pytest
from test_verify_routes import OP, auth, mk, tn  # noqa: F401  (tn: shared route fixture)


@pytest.fixture
def sb(tn):  # noqa: F811
    from buyer_agent import trust_network_discovery as d

    d._hits.clear()
    assert tn.client.post("/tn/fixtures/seed", headers=OP).status_code == 200
    return tn


def start(env, uid, first="Asha"):
    r = env.client.post("/tn/sandbox/start", json={"first_name": first}, headers=auth(uid))
    assert r.status_code == 200, r.text
    return r.json()


def test_sandbox_is_idempotent_labelled_and_partially_verified(sb):
    a = start(sb, "judge1", "Priya Sharma")
    b = start(sb, "judge1", "Someone Else")
    biz = a["business"]
    assert a["created"] is True and b["created"] is False and b["business"]["bid"] == biz["bid"]
    assert biz["display_name"] == "Sample Kirana · Priya" and biz["is_fixture"] and biz["sandbox"]
    assert biz["address"]["pin"] == "500016" and biz["members"] == ["judge1"]
    assert a["status_text"] == "Partially verified (sample)"
    assert biz["summary"]["category"] not in ("identity_confirmed", "evidence_reviewed", "ready_for_counterparty_review")
    checks = sb.client.get(f"/tn/businesses/{biz['bid']}/checks", headers=auth("judge1")).json()
    assert checks and all(c["source_kind"] in ("simulated_fixture", "self_declared") for c in checks)
    assert all("simulated" in c["summary"] for c in checks if c["source_kind"] == "simulated_fixture")
    # another user cannot read it and gets their own
    assert sb.client.get(f"/tn/businesses/{biz['bid']}", headers=auth("judge2")).status_code == 404
    assert start(sb, "judge2")["business"]["bid"] != biz["bid"]
    assert "tn.sandbox.created" in sb.ledger.types(f"biz-{biz['bid']}")


def test_sandbox_can_discover_connect_and_switch_roles_but_is_never_listed_to_others(sb):
    bid = start(sb, "judge1")["business"]["bid"]
    r = sb.client.get(f"/tn/discover?bid={bid}", headers=auth("judge1")).json()
    assert r["viewer_needs_profile"] is False and r["viewer"]["sandbox"] is True and r["results"]
    c = sb.client.post("/tn/connect", json={"from_bid": bid, "to_bid": "fx_seller_annapurna"}, headers=auth("judge1"))
    assert c.status_code == 200 and c.json()["relationship"]["is_fixture"] is True
    biz = sb.client.get(f"/tn/businesses/{bid}", headers=auth("judge1")).json()
    p = sb.client.patch(f"/tn/businesses/{bid}", json={"version": biz["version"], "roles": ["buyer", "seller"]}, headers=auth("judge1"))
    assert p.status_code == 200, p.text
    lst = sb.client.put(f"/tn/businesses/{bid}/listing", headers=auth("judge1"), json={
        "version": p.json()["version"], "listed": True, "categories": ["staples"],
        "service_area": {"kind": "pan_india"}})
    assert lst.status_code == 200, lst.text
    for viewer in ("judge2", "nobody"):
        seen = sb.client.get("/tn/discover?scope=india&verified_only=false", headers=auth(viewer)).json()["results"]
        assert bid not in {x["bid"] for x in seen}
    other = start(sb, "judge2")["business"]["bid"]
    r = sb.client.post("/tn/connect", json={"from_bid": other, "to_bid": bid}, headers=auth("judge2"))
    assert r.status_code == 404


def test_sandbox_delete_removes_everything_and_restarts_fresh(sb):
    bid = start(sb, "judge1")["business"]["bid"]
    sb.client.post("/tn/connect", json={"from_bid": bid, "to_bid": "fx_seller_annapurna"}, headers=auth("judge1"))
    assert sb.client.delete("/tn/sandbox", headers=auth("judge2")).json()["existed"] is False  # cannot delete someone else's
    d = sb.client.delete("/tn/sandbox", headers=auth("judge1")).json()
    assert d["existed"] and d["removed"] >= 3
    assert sb.client.get(f"/tn/businesses/{bid}", headers=auth("judge1")).status_code == 404
    assert not [r for r in sb.db.data.get("tn_relationships", {}).values() if bid in (r["buyer_bid"], r["seller_bid"])]
    assert not [c for c in sb.db.data.get("tn_checks", {}).values() if c["business_id"] == bid]
    assert sb.client.get("/tn/sandbox", headers=auth("judge1")).json()["exists"] is False
    assert start(sb, "judge1")["created"] is True
    assert sb.client.post("/tn/sandbox/delete", headers=auth("judge1")).json()["existed"] is True  # POST alias
    assert sb.client.get("/tn/businesses/fx_seller_annapurna", headers=OP).status_code == 200  # fixtures untouched


def test_demo_review_lists_only_demo_data(sb):
    real = mk(sb, "alice", legal_name="Ravi Store").json()["bid"]
    sb.client.post(f"/tn/businesses/{real}/verify", json={"consents": {"gst": True}}, headers=auth("alice"))
    mine = start(sb, "judge1")["business"]["bid"]
    theirs = start(sb, "judge2")["business"]["bid"]
    me = sb.client.get("/review/me", headers=auth("judge1")).json()
    assert me["reviewer"] is False and me["demo"] is True
    q = sb.client.get("/review/queue", headers=auth("judge1")).json()
    bids = {t["bid"] for t in q}
    assert real not in bids and theirs not in bids and mine in bids and "fx_buyer_srilakshmi" in bids
    assert all(t["demo"] for t in q)
    rq = {t["bid"] for t in sb.client.get("/review/queue", headers=auth("rita")).json()}
    assert {real, mine, theirs} <= rq  # real reviewers see everything


def test_non_reviewer_can_never_act_on_real_businesses(sb):
    real = mk(sb, "alice", legal_name="Ravi Store").json()["bid"]
    sb.client.post(f"/tn/businesses/{real}/verify", json={"consents": {"gst": True}}, headers=auth("alice"))
    tid = f"rv_{real}"
    assert sb.client.get(f"/review/tasks/{tid}", headers=auth("judge1")).status_code == 403
    body = {"action": "approve_identity", "scope": "identity", "reason": "looks fine to me"}
    assert sb.client.post(f"/review/tasks/{tid}/decision", json=body, headers=auth("judge1")).status_code == 403
    assert sb.client.post(f"/review/tasks/{tid}/decision", json=body, headers=auth("alice")).status_code == 403  # not even the owner
    other = start(sb, "judge2")["business"]["bid"]
    assert sb.client.post(f"/review/tasks/rv_{other}/decision", json=body, headers=auth("judge1")).status_code == 403
    assert not [c for c in sb.db.data["tn_checks"].values() if c["business_id"] == real and c["source_kind"] == "human_review"]
    assert sb.client.post(f"/review/tasks/{tid}/decision", json=body, headers=auth("rita")).status_code == 200


def test_demo_decisions_are_labelled_and_need_a_reason(sb):
    bid = start(sb, "judge1")["business"]["bid"]
    tid = f"rv_{bid}"
    t = sb.client.get(f"/review/tasks/{tid}", headers=auth("judge1")).json()
    assert t["demo"] is True and t["demo_note"]
    assert sb.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity"},
                          headers=auth("judge1")).status_code == 422
    r = sb.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity",
                                                              "reason": "Sample: name variant is the same shop"}, headers=auth("judge1"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["demo"] and j["label"] == "Demo reviewer action" and j["task"]["decisions"][-1]["demo"] is True
    assert j["task"]["status"] == "approved"
    assert j["checks"][0]["source_kind"] == "simulated_fixture" and "not a real verification" in j["checks"][0]["summary"]
    assert "tn.review.demo_decision" in sb.ledger.types(f"biz-{bid}")
    # shared fixtures: recorded only, task stays open for the next visitor
    f = sb.client.post("/review/tasks/rv_fx_buyer_srilakshmi/decision", json={"action": "approve_identity", "scope": "identity",
                                                                               "reason": "Trying the demo review"}, headers=auth("judge1"))
    assert f.status_code == 200 and f.json()["task"]["status"] == "open" and not f.json()["checks"]
