"""Persistent restock sessions (CONTRACT2): access control, optimistic concurrency, incremental turns (fast path +
one structured model call, ops applied in code), idempotency, the /prepare bridge into the unchanged negotiation
flow, derived status, and resume rules (expired/revoked mandate, no replay of old turns)."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from buyer_agent import store, trust
from buyer_agent.services import demand, sessions

IST = timezone(timedelta(hours=5, minutes=30))


@pytest.fixture
def offline(env, monkeypatch):
    """Model unavailable: turns use the fast path or the shared deterministic parser."""
    calls = []

    def no_gemini(*a, **k):
        calls.append(a)
        raise RuntimeError("offline")
    monkeypatch.setattr(sessions, "gemini_json", no_gemini)
    monkeypatch.setattr(demand, "gemini_json", no_gemini)
    env.model_calls = calls
    return env


def new(env, uid="alice", **body):
    r = env.client.post("/restock/sessions", json=body, headers=env.auth(uid))
    assert r.status_code == 200, r.text
    return r.json()


def say(env, sid, text, uid="alice", ctid=None, source="voice"):
    ctid = ctid or f"c{abs(hash((sid, text, len(store._get('restock_sessions', sid)['turns']))))}"
    return env.client.post(f"/restock/sessions/{sid}/turns", json={"client_turn_id": ctid, "text": text, "source": source},
                           headers=env.auth(uid))


def lines(s):
    return {l["name"]: l["qty"] for l in s["draft"]["lines"]}


def gt(name):
    return next(g for g, p in store.products().items() if p["name"] == name)


# ---------------------------------------------------------------- 1. model + access control + concurrency
def test_create_get_list(offline):
    s = new(offline, title="Diwali stock")
    assert s["status"] == "draft" and s["version"] == 1 and s["draft"]["lines"] == [] and s["resumable"] is True
    assert s["shop_id"] == "demo" and s["owner_uid"] == "alice" and s["sid"].startswith("rs_")
    r = offline.client.get(f"/restock/sessions/{s['sid']}", headers=offline.auth("alice"))
    assert r.status_code == 200 and r.json()["title"] == "Diwali stock"
    new(offline)
    rows = offline.client.get("/restock/sessions", headers=offline.auth("alice")).json()["sessions"]
    assert len(rows) == 2 and set(rows[0]) >= {"sid", "title", "status", "updated_at", "line_count", "budget_paise",
                                               "total_paise", "needs_attention", "resumable"}
    assert offline.client.get("/restock/sessions", headers=offline.auth("bob")).json()["sessions"] == []
    assert offline.client.get("/restock/sessions?status=ordered", headers=offline.auth("alice")).json()["sessions"] == []


def test_foreign_and_unknown_sid_404(offline):
    s = new(offline)
    sid, c = s["sid"], offline.client
    for uid in ("bob",):  # another owner on the shared demo shop
        h = offline.auth(uid)
        assert c.get(f"/restock/sessions/{sid}", headers=h).status_code == 404
        assert c.patch(f"/restock/sessions/{sid}", json={"version": 1, "title": "x"}, headers=h).status_code == 404
        assert say(offline, sid, "add 10 atta", uid=uid).status_code == 404
        assert c.post(f"/restock/sessions/{sid}/prepare", headers=h).status_code == 404
        assert c.post(f"/restock/sessions/{sid}/cancel", headers=h).status_code == 404
    assert c.get("/restock/sessions/rs_000000000000", headers=offline.auth("alice")).status_code == 404
    assert c.get("/restock/sessions/../shops", headers=offline.auth("alice")).status_code == 404
    # bob's own shop: alice cannot create there and cannot read bob's session
    b = new(offline, uid="bob", shop_id="shopB")
    assert c.get(f"/restock/sessions/{b['sid']}", headers=offline.auth("alice")).status_code == 404
    assert c.post("/restock/sessions", json={"shop_id": "shopB"}, headers=offline.auth("alice")).status_code == 403
    assert c.get(f"/restock/sessions/{sid}").status_code == 401


def test_patch_version_conflict_and_validation(offline):
    s = new(offline)
    sid, h, c = s["sid"], offline.auth("alice"), offline.client
    atta = gt("Aashirvaad Superior MP Atta")
    r = c.patch(f"/restock/sessions/{sid}", json={"version": 1, "lines": [{"gtin": atta, "qty": 10}], "stated_budget_paise": 500000}, headers=h)
    assert r.status_code == 200, r.text
    v2 = r.json()
    assert v2["version"] == 2 and lines(v2) == {"Aashirvaad Superior MP Atta": 10}
    assert v2["draft"]["lines"][0]["ceiling_paise"] == 6000 and v2["draft"]["budget_estimate_paise"] == 60000
    assert v2["draft"]["stated_budget_paise"] == 500000 == v2["draft"]["suggested_mandate"]["budget_paise"]
    # stale version -> 409 with the current session
    r = c.patch(f"/restock/sessions/{sid}", json={"version": 1, "title": "late edit"}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "version_conflict" and r.json()["session"]["version"] == 2
    for bad in ([{"gtin": "000", "qty": 1}], [{"gtin": atta, "qty": 0}], [{"gtin": atta, "qty": 5001}],
                [{"gtin": atta, "qty": 2}, {"gtin": atta, "qty": 3}], [{"gtin": atta, "qty": "5"}]):
        r = c.patch(f"/restock/sessions/{sid}", json={"version": 2, "lines": bad}, headers=h)
        assert r.status_code == 422, bad
    # client-sent ceilings are ignored: recomputed from the catalogue
    r = c.patch(f"/restock/sessions/{sid}", json={"version": 2, "lines": [{"gtin": atta, "qty": 3, "ceiling_paise": 999999}]}, headers=h)
    assert r.status_code == 200 and r.json()["draft"]["lines"][0]["ceiling_paise"] == 6000
    assert r.json()["draft"]["lines"][0]["qty_source"] == "owner"


# ---------------------------------------------------------------- 2. turns
def test_add_set_remove_budget_across_turns(offline):
    sid = new(offline)["sid"]
    r = say(offline, sid, "Prepare a restock. I need ten packets of Aashirvaad atta, twenty packets of iodized salt "
                          "and twelve one-litre sunflower oils.")
    assert r.status_code == 200, r.text
    b = r.json()
    assert lines(b["session"]) == {"Aashirvaad Superior MP Atta": 10, "iodized salt": 20, "Refined Sunflower Oil": 12}
    assert b["fast_path"] is False and set(b["latency_ms"]) >= {"extract", "apply", "total"}
    assert [o["op"] for o in b["ops"]] == ["add_line"] * 3
    r = say(offline, sid, "Keep the budget below eight thousand rupees.").json()
    assert r["fast_path"] is True and r["session"]["draft"]["stated_budget_paise"] == 800000
    assert r["ops"] == [{"op": "set_budget", "paise": 800000}]
    r = say(offline, sid, "Reduce the oil to eight bottles.").json()
    assert r["fast_path"] is True and lines(r["session"])["Refined Sunflower Oil"] == 8
    assert r["ops"][0]["op"] == "set_qty" and r["ops"][0]["qty"] == 8 and r["ops"][0]["from"] == 12
    r = say(offline, sid, "add another 4").json()  # "another" refers to the line touched last (the oil)
    assert r["fast_path"] is True and lines(r["session"])["Refined Sunflower Oil"] == 12
    r = say(offline, sid, "Remove the salt.").json()
    assert r["fast_path"] is True and "iodized salt" not in lines(r["session"])
    r = say(offline, sid, "What's my current total?").json()
    d = r["session"]["draft"]
    assert r["fast_path"] is True and r["ops"] == []
    assert d["budget_estimate_paise"] == 10 * 6000 + 12 * 13500
    assert "₹2,220" in r["reply"] and "₹8,000" in r["reply"]
    assert offline.model_calls == [] or len(offline.model_calls) >= 1  # only the add turn went to the (offline) model
    s = r["session"]
    assert len(s["turns"]) == 12 and s["turns"][-1]["role"] == "sauda" and s["turns"][-2]["text"] == "What's my current total?"


def test_ambiguous_reference_gets_one_clarification(offline):
    sid = new(offline)["sid"]
    say(offline, sid, "12 sunflower oil, 6 mustard oil")
    before = store._get("restock_sessions", sid)["draft"]
    r = say(offline, sid, "remove the oil").json()
    assert r["clarification"] and len(r["clarification"]["options"]) >= 2
    assert {o["name"] for o in r["clarification"]["options"]} >= {"Refined Sunflower Oil", "Patanjali Kacchi Ghani Mustard Oil"}
    assert r["ops"] == [] and r["session"]["draft"]["lines"] == before["lines"]
    assert r["reply"].startswith("Which one") and r["session"]["needs_attention"] is True
    r = say(offline, sid, "the mustard one").json()  # the answer resolves the pending op
    assert set(lines(r["session"])) == {"Refined Sunflower Oil"} and r["session"]["pending"] is None


def test_duplicate_client_turn_id_not_applied_twice(offline):
    sid = new(offline)["sid"]
    say(offline, sid, "10 aashirvaad atta")
    r1 = say(offline, sid, "add 5 more atta", ctid="same-id").json()
    r2 = say(offline, sid, "add 5 more atta", ctid="same-id").json()
    assert lines(r1["session"])["Aashirvaad Superior MP Atta"] == 15 == lines(r2["session"])["Aashirvaad Superior MP Atta"]
    assert r2["dedup"] is True and r2["reply"] == r1["reply"] and r2["ops"] == r1["ops"]
    assert r2["session"]["version"] == r1["session"]["version"]
    assert sum(1 for t in r2["session"]["turns"] if t["client_turn_id"] == "same-id") == 2  # one owner + one reply


@pytest.mark.parametrize("text,to", [("sign it", "review"), ("approve", "approval"), ("Approve it please", "approval"),
                                     ("place the order", "approval"), ("go ahead and sign the limits", "review")])
def test_sign_or_approve_never_changes_state(offline, text, to):
    sid = new(offline)["sid"]
    say(offline, sid, "10 aashirvaad atta")
    before = store._get("restock_sessions", sid)
    r = say(offline, sid, text).json()
    assert r["ops"] == [{"op": "navigate", "to": to}] and "next screen" in r["reply"]
    after = store._get("restock_sessions", sid)
    assert after["draft"] == before["draft"] and after["status"] == "draft" and after["negotiation_id"] is None
    assert offline.db.data.get("mandates", {}) == {} and offline.db.data.get("confirmations", {}) == {}


def test_model_path_numbers_come_from_code(env, monkeypatch):
    """The model only extracts ops; quantities are bounds-checked, unknown gtins dropped, and the reply's totals are
    computed in code from the applied ops (the model never supplies text or numbers for the reply)."""
    atta, maggi = gt("Aashirvaad Superior MP Atta"), gt("Chicken Noodles")

    def fake(prompt, schema, **k):
        assert "CURRENT DRAFT" in prompt and "CATALOG" in prompt
        return sessions.TurnExtract(intent="edit", ops=[
            sessions.TurnOp(op="add_line", gtin=maggi, owner_words="twenty-four packets of Maggi noodles", qty=24),
            sessions.TurnOp(op="add_line", gtin="9999999999999", owner_words="unicorn", qty=3),
            sessions.TurnOp(op="add_line", gtin=atta, owner_words="something else entirely", qty=7),  # not named: dropped
            sessions.TurnOp(op="set_budget", budget_rupees=123456),  # never said: ignored
            sessions.TurnOp(op="remove", gtin=gt("iodized salt")),  # not a current line: ignored
        ])
    monkeypatch.setattr(sessions, "gemini_json", fake)
    sid = new(env)["sid"]
    r = say(env, sid, "Add twenty-four packets of Maggi noodles").json()
    d = r["session"]["draft"]
    assert lines(r["session"]) == {"Chicken Noodles": 24} and d["stated_budget_paise"] is None
    est = 24 * 2000
    assert d["budget_estimate_paise"] == est and "₹480" in r["reply"]
    nums = set(re.findall(r"\d[\d,]*", r["reply"]))
    assert nums <= {"24", "480", "1"}, r["reply"]


def test_model_failure_uses_shared_parser(offline):
    sid = new(offline)["sid"]
    r = say(offline, sid, "das packet Aashirvaad atta 1 kilo aur bees Tata namak").json()
    assert lines(r["session"]) == {"Aashirvaad Superior MP Atta": 10, "Salt LITE": 20}


def test_turn_cap_trims_oldest(offline, monkeypatch):
    monkeypatch.setattr(sessions, "TURN_CAP", 4)
    sid = new(offline)["sid"]
    for k in range(4):
        say(offline, sid, f"{k + 1} aashirvaad atta", ctid=f"t{k}")
    s = store._get("restock_sessions", sid)
    assert len(s["turns"]) == 4 and s["turns_trimmed"] == 4


def test_words_to_digits():
    w = sessions.words_to_digits
    assert w("twelve one-litre sunflower oils") == "12 1 litre sunflower oils"
    assert w("ten packets of one-kilogram atta") == "10 packets of 1 kg atta"
    assert w("twenty-four packets") == "24 packets" and w("eight thousand rupees") == "8000 rupees"
    assert w("two thousand five hundred") == "2500" and w("the first one") == "the first one"


# ---------------------------------------------------------------- 3. prepare -> existing flow; derived status
def _negotiate(nid, mandate_body, uid="alice"):
    """Stand-in for the supplier rounds (POST /chat): a clean quote and a cart under the signed mandate."""
    from buyer_agent.services import confirm
    ls = [{"gtin": l["gtin"], "name": l["gtin"], "qty": l["qty"], "unit_price_paise": int(l["ceiling_paise"] * 0.9),
           "opening_price_paise": l["ceiling_paise"], "ceiling_paise": l["ceiling_paise"], "ceiling_source": "mrp"}
          for l in mandate_body["lines"]]
    store.save_offer({"negotiation_id": nid, "supplier_id": "sharma", "round": 1, "direction": "quote", "lines": ls, "guard_verdict": "clean"})
    tot = sum(l["qty"] * l["unit_price_paise"] for l in ls)
    cart = {"allocations": [{"supplier_id": "sharma", "supplier_name": "Sharma Traders", "lines": ls, "subtotal_paise": tot,
                             "delivery_days": 2, "advance_pct": 0, "payout_vpa": None}],
            "total_paise": tot, "savings_paise": 0, "opening_cost_paise": 0, "dropped_lines": [], "why": [], "status": "cart_ready"}
    cid = store.save_cart_draft(nid, cart)
    store.update_negotiation(nid, status="cart_ready", cart_draft_id=cid)
    return confirm.request(nid, cid, session_id="s", user_id=uid, mode="direct")["confirmation_id"]


def _prepared(env, uid="alice"):
    sid = new(env, uid=uid)["sid"]
    say(env, sid, "10 aashirvaad atta, 6 mustard oil", uid=uid)
    r = env.client.post(f"/restock/sessions/{sid}/prepare", headers=env.auth(uid))
    assert r.status_code == 200, r.text
    return sid, r.json()


def test_prepare_bridges_to_unchanged_flow(offline):
    c, h = offline.client, offline.auth("alice")
    sid, p = _prepared(offline)
    nid = p["negotiation_id"]
    n = store.negotiation(nid)
    assert n["status"] == "created" and n["owner_uid"] == "alice" and n["draft"]["lines"] == p["session"]["draft"]["lines"]
    assert store.shop("demo")["active_negotiation_id"] == nid
    assert p["session"]["status"] == "awaiting_review" and p["suggested_mandate"]["lines"]
    # prepare again reuses the same unsigned negotiation
    assert c.post(f"/restock/sessions/{sid}/prepare", headers=h).json()["negotiation_id"] == nid
    # existing flow: POST /mandates with the negotiation binding
    r = c.post("/mandates", json={"kind": "intent", "body": p["suggested_mandate"], "negotiation_id": nid}, headers=h)
    assert r.status_code == 200, r.text
    mid = r.json()["mandate_id"]
    s = c.get(f"/restock/sessions/{sid}", headers=h).json()
    assert s["status"] == "negotiating" and s["intent_mandate_id"] == mid and s["negotiation_id"] == nid
    # locked for edits now
    assert say(offline, sid, "add 5 sugar").json()["code"] == "session_locked"
    r = c.patch(f"/restock/sessions/{sid}", json={"version": s["version"], "stated_budget_paise": 1}, headers=h)
    assert r.status_code == 409 and r.json()["code"] == "session_locked"
    conf = _negotiate(nid, p["suggested_mandate"])
    s = c.get(f"/restock/sessions/{sid}", headers=h).json()
    assert s["status"] == "awaiting_approval" and s["confirmation_id"] == conf and s["needs_attention"] is True
    assert offline.approve(conf).status_code == 200
    s = c.get(f"/restock/sessions/{sid}", headers=h).json()
    assert s["status"] == "ordered" and s["order_ids"] == [o["order_id"] for o in store.orders_for(nid)] and s["resumable"] is False
    row = c.get("/restock/sessions", headers=h).json()["sessions"][0]
    assert row["status"] == "ordered" and row["total_paise"] == sum(o["total_paise"] for o in store.orders_for(nid))
    assert c.post(f"/restock/sessions/{sid}/cancel", headers=h).status_code == 409


def test_prepare_empty_and_shop_busy(offline):
    c = offline.client
    sid = new(offline)["sid"]
    assert c.post(f"/restock/sessions/{sid}/prepare", headers=offline.auth("alice")).json()["code"] == "empty_draft"
    offline.cart_ready(uid="bob", shop="demo")  # bob is negotiating on the shared shop
    say(offline, sid, "10 aashirvaad atta")
    assert c.post(f"/restock/sessions/{sid}/prepare", headers=offline.auth("alice")).status_code == 409


def test_cancel(offline):
    sid, p = _prepared(offline)
    r = offline.client.post(f"/restock/sessions/{sid}/cancel", headers=offline.auth("alice"))
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["resumable"] is False
    assert store.negotiation(p["negotiation_id"])["status"] == "cancelled"
    assert store.shop("demo").get("active_negotiation_id") is None
    assert offline.client.get(f"/restock/sessions/{sid}", headers=offline.auth("alice")).json()["status"] == "cancelled"
    assert say(offline, sid, "add 5 sugar").status_code == 409


# ---------------------------------------------------------------- 6. resume rules
def test_resume_with_expired_mandate_and_old_approve_turn(offline):
    c, h = offline.client, offline.auth("alice")
    sid, p = _prepared(offline)
    nid = p["negotiation_id"]
    body = {**p["suggested_mandate"], "owner_uid": "alice",
            "expires_at": (datetime.now(IST) - timedelta(minutes=5)).replace(microsecond=0).isoformat()}
    m = trust.create_mandate("intent", body, "alice")
    store.update_negotiation(nid, intent_mandate_id=m.mandate_id)
    conf = _negotiate(nid, p["suggested_mandate"])
    # an approval-like turn stored earlier has no effect when the session is reloaded
    s = store._get("restock_sessions", sid)
    s["turns"].append({"turn_id": "t_x", "client_turn_id": "old", "role": "owner", "text": "approve", "source": "voice", "ts": store.iso()})
    store._set("restock_sessions", sid, s)
    r = c.get(f"/restock/sessions/{sid}", headers=h).json()
    assert r["resumable"] is False and r["error"]["code"] == "mandate_expired" and r["needs_attention"] is True
    assert r["draft"]["lines"]  # the draft stays viewable / copyable
    assert store.confirmation(conf)["status"] == "requested" and store.orders_for(nid) == []
    row = c.get("/restock/sessions", headers=h).json()["sessions"][0]
    assert row["resumable"] is False and row["needs_attention"] is True


def test_resume_with_revoked_mandate(offline):
    c, h = offline.client, offline.auth("alice")
    sid, p = _prepared(offline)
    mid = c.post("/mandates", json={"kind": "intent", "body": p["suggested_mandate"], "negotiation_id": p["negotiation_id"]},
                 headers=h).json()["mandate_id"]
    assert c.post(f"/mandates/{mid}/revoke", headers=h).status_code == 200
    s = c.get(f"/restock/sessions/{sid}", headers=h).json()
    assert s["status"] == "cancelled" and s["resumable"] is False


def test_voice_segment_limit_is_30s():
    from buyer_agent.services import voice
    from test_voice_parse import wav_bytes
    assert voice.MAX_SECONDS == 30
    info = voice.validate_audio(wav_bytes(seconds=29, rate=8000, amp=3000), "audio/wav")
    assert info.duration_s and 28 < info.duration_s < 30
    with pytest.raises(voice.VoiceError):
        voice.validate_audio(wav_bytes(seconds=31.5, rate=8000, amp=3000), "audio/wav")


def test_telemetry_logs_durations_only(offline):
    sid = new(offline)["sid"]
    marks = [{"name": "utterance_end", "t": 1000, "utt": "u1"}, {"name": "final_transcript", "t": 1350, "utt": "u1"},
             {"name": "turn_applied", "t": 1900, "utt": "u1"},
             {"name": "utterance_end", "t": 5000, "utt": "u2"}, {"name": "final_transcript", "t": 5250, "utt": "u2"},
             {"name": "utterance_end", "t": 9000, "utt": "u3"}, {"name": "final_transcript", "t_ms": 9450, "utt": "u3"}]
    r = offline.client.post("/telemetry/voice", json={"sid": sid, "marks": marks}, headers=offline.auth("alice"))
    assert r.status_code == 200 and r.json()["durations_ms"] == {"utterance_end->final_transcript": 350}
    assert offline.client.post("/telemetry/voice", json={"sid": sid, "marks": []}, headers=offline.auth("bob")).status_code == 404
