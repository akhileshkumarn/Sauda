"""Agent tools. Every side-effect tool goes through sauda_trust.tool_broker.broker; place_order is the only
FunctionTool with require_confirmation (its gate runs before the pause and again on resume)."""
from __future__ import annotations

import contextvars
import logging
from typing import Callable

from google.adk.tools import FunctionTool
from sauda_trust import tool_broker
from sauda_trust.tool_broker import BrokerContext, broker

from .. import store, trust
from ..negotiation import loop
from ..negotiation.a2a import SupplierClient
from ..services import demand, orders

log = logging.getLogger("buyer_agent.tools")

# stream_id -> emitter(event_name, data) for one /chat request. Keyed per request (never per shop): two owners
# on the shared demo shop must never receive each other's events.
EMITTERS: dict[str, Callable[[str, dict], None]] = {}
CURRENT_STREAM: contextvars.ContextVar[str | None] = contextvars.ContextVar("sauda_stream_id", default=None)
ALL_RULES = [f"R{i}" for i in range(1, 13)]


def emit_for(_shop_id: str | None = None) -> Callable[[str, dict], None]:
    sid = CURRENT_STREAM.get()
    return (EMITTERS.get(sid) if sid else None) or (lambda name, data: None)


class SessionBinding(Exception):
    pass


def _bind(tool_context) -> dict:
    """Session state set by /chat for this turn: shop_id, owner_uid, stream_id. Also routes emits to this stream."""
    st = {}
    try:
        st = {k: tool_context.state.get(k) for k in ("shop_id", "owner_uid", "stream_id")} if tool_context is not None else {}
    except Exception:
        st = {}
    if st.get("stream_id"):
        CURRENT_STREAM.set(st["stream_id"])
    return st


def _check_negotiation(st: dict, nid: str) -> dict | None:
    """Model-chosen ids are never trusted: the negotiation must belong to this session's shop and owner."""
    if not st.get("shop_id"):
        return None  # direct (non-ADK) caller: ids come from server state, not a model
    n = store.negotiation(nid)
    if not n or n.get("shop_id") != st["shop_id"] or (n.get("owner_uid") and st.get("owner_uid")
                                                        and n["owner_uid"] != st["owner_uid"]):
        log.warning("tool call for a negotiation outside this session: %s", nid)
        return {"status": "denied", "reasons": ["NOT_THIS_SESSION"]}
    return None


# ---------------------------------------------------------------- broker context provider
def _mandate_for_negotiation(nid: str):
    n = store.negotiation(nid)
    if not n or not n.get("intent_mandate_id"):
        raise tool_broker.ToolDenied(["MANDATE_INVALID"])
    mrec = trust.get_mandate(n["intent_mandate_id"])
    if mrec is None:
        raise tool_broker.ToolDenied(["MANDATE_INVALID"])
    return n, mrec


def _owner_confirmed(cart_draft_id: str | None) -> bool:
    """True only if the owner approved a confirmation issued for exactly this cart (same cart hash)."""
    if not cart_draft_id:
        return False
    cart = store.cart_draft(cart_draft_id)
    if not cart or not cart.get("allocations"):
        return False
    chash = orders.cart_hash(cart)
    return any(c.get("status") == "approved" and c.get("cart_hash") == chash
               for c in store.confirmations_for_cart(cart_draft_id))


def _card_fps(sids: list[str]) -> dict[str, str]:
    out = {}
    for sid in sids:
        try:
            out[sid] = SupplierClient.load(sid).card_fingerprint
        except Exception:
            log.warning("card fetch failed for %s", sid)
    return out


def build_place_order_context(nid: str, cart_draft_id: str, owner_confirmed: bool | None = None) -> BrokerContext:
    n, mrec = _mandate_for_negotiation(nid)
    cart = store.cart_draft(cart_draft_id)
    if not cart or cart.get("negotiation_id") != nid:
        raise tool_broker.ToolDenied(["GATE_ERROR"])
    sids = [a["supplier_id"] for a in cart["allocations"]]
    ctx = trust.build_ctx(mrec, card_fingerprints=_card_fps(sids), guard_verdicts=orders.latest_guard_verdicts(nid),
                          seen_keys=orders.seen_keys(nid),
                          owner_confirmed=_owner_confirmed(cart_draft_id) if owner_confirmed is None else owner_confirmed)
    action = trust.Action(**orders.cart_action(nid, cart))
    return BrokerContext(action=action, mandate=mrec.intent(), ctx=ctx, negotiation_id=nid)


def context_provider(tool_name: str, args: dict) -> BrokerContext:
    if tool_name in ("run_negotiation", "explain_cart"):
        nid = args["negotiation_id"]
        n, mrec = _mandate_for_negotiation(nid)
        ctx = trust.build_ctx(mrec)
        return BrokerContext(action=trust.Action(kind=tool_name, negotiation_id=nid), mandate=mrec.intent(), ctx=ctx, negotiation_id=nid)
    if tool_name == "place_order":
        return build_place_order_context(args["negotiation_id"], args["cart_draft_id"])
    if tool_name == "issue_payment_mandate":
        o = store.order(args["order_id"])
        if o is None:
            raise tool_broker.ToolDenied(["GATE_ERROR"])
        nid = o["negotiation_id"]
        n, mrec = _mandate_for_negotiation(nid)
        act = orders.payment_action(o)
        seen = {act["idempotency_key"]} if o.get("payment_mandate_id") else set()
        ctx = trust.build_ctx(mrec, supplier_ids=[o["supplier_id"]], seen_keys=seen,
                              owner_confirmed=_owner_confirmed(o.get("cart_draft_id")))
        return BrokerContext(action=trust.Action(**act), mandate=mrec.intent(), ctx=ctx, negotiation_id=nid)
    raise tool_broker.ToolDenied(["GATE_ERROR"])


tool_broker.set_context_provider(context_provider)


def _state(tool_context, key, default=None):
    try:
        return tool_context.state.get(key, default)
    except Exception:
        return default


# ---------------------------------------------------------------- tools
def draft_order(shop_id: str, festival: str | None = None, tool_context=None) -> dict:
    """Draft a restock order from the owner's latest message (Plan B: typed list + festival uplift).

    Args:
      shop_id: the shop id from the session context.
      festival: optional festival name, e.g. "Diwali".
    """
    # Read-only and pre-mandate: no mandate exists yet, so R1/R12 cannot apply (documented deviation).
    st = _bind(tool_context)
    text = _state(tool_context, "last_owner_message", "") or ""
    owner_uid = _state(tool_context, "owner_uid", "unknown")
    return create_draft(st.get("shop_id") or shop_id, text, owner_uid, festival)  # session shop wins over the model's


def create_draft(shop_id: str, text: str, owner_uid: str, festival: str | None = None) -> dict:
    emit = emit_for(shop_id)
    emit("agent.tool", {"name": "draft_order", "status": "running"})
    d = demand.build_draft(shop_id, text, festival)
    n = store.create_negotiation(shop_id, owner_uid, draft=d)
    store.update_shop(shop_id, active_negotiation_id=n["negotiation_id"])
    out = {"status": "drafted", "negotiation_id": n["negotiation_id"], "draft_id": n["negotiation_id"], **d,
           "budget_paise": d["suggested_budget_paise"], "deliver_by": d["suggested_mandate"]["deliver_by"],
           "allowed_supplier_ids": d["suggested_mandate"]["allowed_supplier_ids"], "assumptions": [d["assumption"]]}
    emit("draft", out)
    emit("agent.tool", {"name": "draft_order", "status": "done", "result": out})
    return {k: v for k, v in out.items() if k != "suggested_mandate"}


def run_negotiation(negotiation_id: str, preferred_supplier_id: str | None = None, tool_context=None) -> dict:
    """Negotiate with the approved suppliers under the signed mandate and return the cart draft.

    Args:
      negotiation_id: the negotiation id from the session context.
      preferred_supplier_id: optional (unused tonight).
    """
    deny = _check_negotiation(_bind(tool_context), negotiation_id)
    return deny or _run_negotiation(negotiation_id, preferred_supplier_id)


@broker(rules=["R1", "R2", "R12"], return_denial=True, name="run_negotiation")
def _run_negotiation(negotiation_id: str, preferred_supplier_id: str | None = None) -> dict:
    n = store.negotiation(negotiation_id)
    emit = emit_for(n["shop_id"])
    emit("agent.tool", {"name": "run_negotiation", "status": "running"})
    if n.get("cart_draft_id") and n.get("status") in ("cart_ready", "awaiting_confirmation"):
        cart = store.cart_draft(n["cart_draft_id"])
    else:
        try:
            cart = loop.run(negotiation_id, emit)
        except loop.Revoked:
            return {"status": "denied", "reasons": ["REVOKED"]}
        except loop.NegotiationError as e:
            return {"status": "failed", "error": str(e)}
    emit("cart", cart)
    emit("agent.tool", {"name": "run_negotiation", "status": "done"})
    return summarize_cart(cart)


def summarize_cart(cart: dict) -> dict:
    return {
        "status": cart.get("status"), "cart_draft_id": cart.get("cart_draft_id"), "negotiation_id": cart.get("negotiation_id"),
        "total_rupees": cart["total_paise"] / 100, "savings_rupees": cart["savings_paise"] / 100, "savings_pct": cart.get("savings_pct"),
        "allocations": [{"supplier": a["supplier_name"], "lines": len(a["lines"]), "subtotal_rupees": a["subtotal_paise"] / 100} for a in cart["allocations"]],
        "dropped_lines": cart.get("dropped_lines", []), "why": [w["text"] for w in cart.get("why", [])],
        "blocked_supplier_messages": cart.get("blocked_messages", 0), "gate_verdict": cart.get("gate_report", {}).get("verdict"),
        "rounds": cart.get("rounds"),
    }


def explain_cart(negotiation_id: str, tool_context=None) -> dict:
    """Explain the current cart: who won which lines and why, what was blocked.

    Args:
      negotiation_id: the negotiation id.
    """
    deny = _check_negotiation(_bind(tool_context), negotiation_id)
    return deny or _explain_cart(negotiation_id)


@broker(rules=["R1", "R12"], return_denial=True, name="explain_cart")
def _explain_cart(negotiation_id: str) -> dict:
    n = store.negotiation(negotiation_id)
    cart = store.cart_draft(n.get("cart_draft_id")) if n else None
    if not cart:
        return {"status": "no_cart"}
    blocked = [{"supplier_id": o["supplier_id"], "round": o["round"], "categories": o.get("guard_categories", [])}
               for o in store.offers_for(negotiation_id) if o.get("guard_verdict") == "blocked"]
    return {**summarize_cart(cart), "blocked": blocked}


def _require_confirmation(negotiation_id: str, cart_draft_id: str, tool_context=None, **_) -> bool:
    """Gate pass before the pause (all twelve rules, owner not yet confirmed). DENY -> no pause: the tool
    body then runs and the broker denies. Otherwise pause for the owner."""
    try:
        if _check_negotiation(_bind(tool_context), negotiation_id):
            return False  # not this session's negotiation: the tool body denies it
        if _owner_confirmed(cart_draft_id):
            return False  # resume after approval: the broker re-runs all twelve rules with owner_confirmed
        bc = build_place_order_context(negotiation_id, cart_draft_id, owner_confirmed=False)
        if bc.ctx.seen_idempotency_keys and bc.action.idempotency_key in bc.ctx.seen_idempotency_keys:
            return False  # already placed: let the idempotent body answer
        from sauda_trust.policy_gate import evaluate

        rep = evaluate(bc.action, bc.mandate, bc.ctx, rules=ALL_RULES)
        trust.ledger_append(negotiation_id, "gate.decision", "gate", {"tool": "place_order", "stage": "pre_confirmation", **rep.to_dict()})
        n = store.negotiation(negotiation_id)
        emit_for(n["shop_id"])("gate.report", {"action": "place_order", "verdict": rep.verdict, "results": rep.to_dict()["results"], "reasons": rep.reasons})
        store.update_negotiation(negotiation_id, pre_confirmation_gate=rep.to_dict())
        if rep.verdict == "DENY":
            return False
        return not _owner_confirmed(cart_draft_id)
    except Exception:
        log.exception("pre-confirmation gate failed")
        return True  # fail closed: ask the owner (the body is gated again anyway)


def place_order(negotiation_id: str, cart_draft_id: str, tool_context=None) -> dict:
    """Place the purchase orders for the cart draft. Requires the owner's approval on the confirmation screen.

    Args:
      negotiation_id: the negotiation id.
      cart_draft_id: the cart_draft_id returned by run_negotiation.
    """
    deny = _check_negotiation(_bind(tool_context), negotiation_id)
    return deny or _place_order(negotiation_id, cart_draft_id)


@broker(rules=ALL_RULES, return_denial=True, name="place_order")
def _place_order(negotiation_id: str, cart_draft_id: str) -> dict:
    return orders.place(negotiation_id, cart_draft_id)


def issue_payment_mandate_impl(order_id: str) -> dict:
    o = store.order(order_id)
    owner = (store.negotiation(o["negotiation_id"]) or {}).get("owner_uid", "unknown") if o else "unknown"
    v = orders.issue_payment(order_id, owner)
    return {"status": "issued" if v.get("payment_mandate_id") else v.get("status", "failed"), "order_id": order_id, "payment_mandate_id": v.get("payment_mandate_id"),
            "upi_link": v.get("upi_link")}


def issue_payment_mandate(order_id: str, tool_context=None) -> dict:
    """Issue the signed Payment Mandate (UPI, payee = the supplier's registered VPA) for one order.

    Args:
      order_id: an order id returned by place_order.
    """
    st = _bind(tool_context)
    o = store.order(order_id)
    if o and st.get("shop_id"):
        deny = _check_negotiation(st, o["negotiation_id"])
        if deny:
            return deny
    return _issue_payment_mandate(order_id)


@broker(rules=["R1", "R8", "R11", "R12"], return_denial=True, name="issue_payment_mandate")
def _issue_payment_mandate(order_id: str) -> dict:
    return issue_payment_mandate_impl(order_id)


place_order_tool = FunctionTool(place_order, require_confirmation=_require_confirmation)
TOOLS = [draft_order, run_negotiation, explain_cart, place_order_tool, issue_payment_mandate]
