"""P0-2: chat events are routed per request, never per shop: two owners never receive each other's events."""
import asyncio

from buyer_agent import store
from buyer_agent.agent import tools
from buyer_agent.services import chat, demand


def test_two_owners_same_shop_never_share_events(env, monkeypatch):
    monkeypatch.setattr(demand, "gemini_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))

    async def collect(uid, msg):
        return [ev async for ev in chat.stream("demo", uid, msg)]

    async def both():
        return await asyncio.gather(collect("alice", "restock 10 aashirvaad atta"), collect("bob", "restock 12 oil"))

    a, b = asyncio.run(both())
    for evs, uid, word in ((a, "alice", "Atta"), (b, "bob", "Oil")):
        drafts = [e["data"] for e in evs if e["event"] == "draft"]
        assert len(drafts) == 1, [e["event"] for e in evs]
        assert store.negotiation(drafts[0]["negotiation_id"])["owner_uid"] == uid
        assert all(word.lower() in l["name"].lower() for l in drafts[0]["lines"])
    assert tools.EMITTERS == {}


def test_emit_for_routes_by_stream_not_shop():
    got = {"x": [], "y": []}
    tools.EMITTERS.update({"x": lambda n, d: got["x"].append(n), "y": lambda n, d: got["y"].append(n)})
    try:
        import contextvars
        for sid in ("x", "y"):
            ctx = contextvars.copy_context()
            ctx.run(lambda s=sid: (tools.CURRENT_STREAM.set(s), tools.emit_for("demo")("draft", {})))
        tools.emit_for("demo")("draft", {})  # no stream bound: dropped, never broadcast to a shop
        assert got == {"x": ["draft"], "y": ["draft"]}
    finally:
        tools.EMITTERS.clear()


def test_model_supplied_ids_for_other_sessions_are_refused(env):
    nid, cid, conf, mid = env.cart_ready(uid="bob", shop="shopB")

    class TC:
        state = {"shop_id": "demo", "owner_uid": "alice", "stream_id": None}

    for res in (tools.run_negotiation(nid, tool_context=TC()), tools.explain_cart(nid, tool_context=TC()),
                tools.place_order(nid, cid, tool_context=TC())):
        assert res == {"status": "denied", "reasons": ["NOT_THIS_SESSION"]}
    d = tools.draft_order("shopB", tool_context=type("T", (), {"state": {**TC.state, "last_owner_message": "10 atta"}})())
    assert store.negotiation(d["negotiation_id"])["shop_id"] == "demo"  # session shop wins over the model's arg
