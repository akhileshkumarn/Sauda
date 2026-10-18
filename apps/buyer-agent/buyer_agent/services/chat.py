"""/chat orchestration: runs one ADK turn on the agent loop and turns ADK events + tool emits into the SSE
protocol (SM-5). A deterministic fallback router guarantees the same flow if the model skips a tool."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncIterator

from .. import store, trust
from ..deps import settings
from . import confirm

log = logging.getLogger("buyer_agent.chat")
RESTOCK_RE = re.compile(r"restock|order|\b\d+\s+[a-z]", re.I)
NEGOTIATE_RE = re.compile(r"negotiat|signed|go ahead|start|proceed|quote", re.I)


def _ev(name: str, data: dict) -> dict:
    return {"event": name, "data": data}


async def stream(shop_id: str, owner_uid: str, message: str, session_id: str | None = None,
                 preferred_supplier_id: str | None = None, mandate_id: str | None = None) -> AsyncIterator[dict]:
    from ..agent import root, tools

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def push(item: dict) -> None:
        loop.call_soon_threadsafe(q.put_nowait, item)

    seen: set[str] = set()

    def emit(name: str, data: dict) -> None:
        seen.add(name)
        push(_ev(name, data))

    import uuid

    stream_id = uuid.uuid4().hex  # emitters are per request: two owners on one shop never share a stream
    tools.EMITTERS[stream_id] = emit
    tools.CURRENT_STREAM.set(stream_id)  # asyncio.to_thread copies this context into the direct-mode tool calls
    if mandate_id:  # "Start negotiation" button: bind the chat to the negotiation of that signed mandate
        n0 = store.negotiation_for_mandate(mandate_id)
        if n0 and n0.get("shop_id") == shop_id and n0.get("owner_uid") in (None, owner_uid):
            store.update_shop(shop_id, active_negotiation_id=n0["negotiation_id"])
    shop = store.shop(shop_id)
    nid = shop.get("active_negotiation_id")
    session_id = session_id or f"{shop_id}:main"
    state = {"shop_id": shop_id, "owner_uid": owner_uid, "last_owner_message": message, "negotiation_id": nid or "",
             "stream_id": stream_id}
    n = store.negotiation(nid) if nid else None
    ctx_line = (f"[session context] shop_id={shop_id} negotiation_id={nid or 'none'} "
                f"negotiation_status={(n or {}).get('status', 'none')} mandate_signed={bool((n or {}).get('intent_mandate_id'))}")
    turn_text = f"{ctx_line}\n\nOwner: {message}"

    DONE = object()
    use_adk = settings().agent_mode == "adk"
    if use_adk:
        fut = root.run_turn(owner_uid, session_id, turn_text, state, push)
        fut.add_done_callback(lambda f: loop.call_soon_threadsafe(q.put_nowait, {"done": DONE, "error": f.exception()}))
    else:
        loop.call_soon(q.put_nowait, {"done": DONE, "error": None})

    adk_failed = None
    try:
        while True:
            item = await q.get()
            if item.get("done") is DONE:
                adk_failed = item.get("error")
                break
            if "adk_event" in item:
                for out in _translate(item["adk_event"], session_id, owner_uid):
                    seen.add(out["event"])
                    yield out
            else:
                seen.add(item.get("event", ""))
                yield item
        if adk_failed:
            log.error("ADK turn failed: %r", adk_failed)
            yield _ev("agent.tool", {"name": "adk", "status": f"agent error, deterministic fallback: {type(adk_failed).__name__}"})

        # ---- deterministic fallback (same tools, same gate) ----
        drain = []
        cur_nid = store.shop(shop_id).get("active_negotiation_id")
        cur = store.negotiation(cur_nid) if cur_nid else None
        if "draft" not in seen and "cart" not in seen and RESTOCK_RE.search(message) and not NEGOTIATE_RE.search(message) and not mandate_id:
            await asyncio.to_thread(tools.create_draft, shop_id, message, owner_uid)
            cur_nid = store.shop(shop_id).get("active_negotiation_id")
            cur = store.negotiation(cur_nid)
            emit("agent.text", {"text": _draft_text(cur)})
        elif cur and cur.get("intent_mandate_id") and cur.get("status") in ("created",) and "cart" not in seen:
            res = await asyncio.to_thread(tools.run_negotiation, cur_nid)
            emit("agent.text", {"text": _cart_text(res)})
            cur = store.negotiation(cur_nid)
        if cur and cur.get("status") == "cart_ready" and cur.get("cart_draft_id") and "confirmation.request" not in seen:
            c = await asyncio.to_thread(confirm.request, cur_nid, cur["cart_draft_id"], session_id=session_id, user_id=owner_uid, mode="direct")
            emit("confirmation.request", {"confirmation_id": c["confirmation_id"], "cart_draft_id": cur["cart_draft_id"]})
        await asyncio.sleep(0.05)  # let call_soon_threadsafe callbacks enqueue
        while not q.empty():
            item = q.get_nowait()
            if "event" in item:
                drain.append(item)
        for item in drain:
            yield item
        cur = store.negotiation(cur_nid) if cur_nid else None
        yield _ev("done", {"negotiation_id": cur_nid, "status": (cur or {}).get("status")})
    except Exception as e:  # noqa: BLE001
        log.exception("chat stream failed")
        yield _ev("error", {"code": type(e).__name__, "message": "Something went wrong on our side; please try again."})
    finally:
        tools.EMITTERS.pop(stream_id, None)


def _translate(ev, session_id: str, owner_uid: str) -> list[dict]:
    out: list[dict] = []
    try:
        for fc in ev.get_function_calls() or []:
            if fc.name == "adk_request_confirmation":
                args = fc.args or {}
                orig = args.get("originalFunctionCall") or args.get("original_function_call") or {}
                oargs = orig.get("args") or {}
                nid, cid = oargs.get("negotiation_id"), oargs.get("cart_draft_id")
                if nid and cid:
                    c = confirm.request(nid, cid, session_id=session_id, user_id=owner_uid, invocation_id=ev.invocation_id,
                                        function_call_id=fc.id, mode="adk")
                    out.append(_ev("confirmation.request", {"confirmation_id": c["confirmation_id"], "cart_draft_id": cid}))
            else:
                out.append(_ev("agent.tool", {"name": fc.name, "status": "called"}))
        for fr in ev.get_function_responses() or []:
            if fr.name in ("draft_order", "adk_request_confirmation"):
                continue  # draft_order already streamed agent.tool {status: done, result}
            resp = fr.response or {}
            st = resp.get("status") if isinstance(resp, dict) else None
            out.append(_ev("agent.tool", {"name": fr.name, "status": st or "returned",
                                          **({"reasons": resp.get("reasons")} if isinstance(resp, dict) and resp.get("reasons") else {})}))
        if ev.content and ev.content.parts and not getattr(ev, "partial", False) and (ev.author != "user"):
            text = "".join(p.text for p in ev.content.parts if getattr(p, "text", None) and not getattr(p, "thought", False))
            if text.strip():
                try:
                    v = trust.screen(text, "outbound")
                    # fail closed: a Model Armor block or outage withholds the reply (regex-only hits on
                    # owner-facing text are allowed: the agent legitimately describes blocked terms)
                    if v.blocked and v.source in ("model_armor", "timeout"):
                        text = "(reply withheld by Guard)"
                except Exception:
                    text = "(reply withheld by Guard)"
                out.append(_ev("agent.text", {"text": text}))
    except Exception:
        log.exception("translate failed")
    # attach the confirmation pseudo-name so the fallback knows it was emitted
    return out


def _draft_text(n: dict | None) -> str:
    if not n or not n.get("draft"):
        return "I could not draft an order from that message."
    d = n["draft"]
    lines = ", ".join(f"{l['qty']} x {l['name']}" for l in d["lines"])
    return (f"Draft ready: {lines}. Suggested budget ₹{d['suggested_budget_paise'] / 100:,.0f}. "
            f"{d.get('assumption', '')} Please review the items and sign your spending limits.")


def _cart_text(res: dict) -> str:
    if res.get("status") not in ("cart_ready",):
        return f"Negotiation ended: {res.get('status')} {res.get('reasons') or res.get('error') or ''}".strip()
    sup = "; ".join(f"{a['supplier']} {a['lines']} lines ₹{a['subtotal_rupees']:,.2f}" for a in res["allocations"])
    blocked = f" {res['blocked_supplier_messages']} supplier message(s) blocked: unsafe payment terms or injection." if res.get("blocked_supplier_messages") else ""
    return (f"Cart ready: ₹{res['total_rupees']:,.2f} total, ₹{res['savings_rupees']:,.2f} saved vs opening quotes "
            f"({res.get('savings_pct')}%). {sup}.{blocked} Please review and approve.")
