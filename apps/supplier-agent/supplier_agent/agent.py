"""Supplier agent: ADK Agent definition + deterministic A2A executor.

Design (documented deviation from a pure to_a2a(LlmAgent) setup): the numbers never depend on
the LLM. SupplierExecutor (an a2a-sdk AgentExecutor, plugged into ADK's to_a2a through
agent_executor_factory) parses the incoming A2A data part (RFQ / COUNTER / FINAL / PO), calls the
same tool functions the ADK Agent exposes (quote / revise / accept_po), and asks Gemini only for
one sentence of text. If Gemini fails or times out a template sentence is used. The hostile
profile's injection_text is appended to the text part from profile data, so it is reproducible.

Reply = one A2A Message (role agent) with parts [text, data]; the data part echoes
negotiation_id and nonce from the request.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from a2a.helpers.proto_helpers import new_data_part, new_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from google.adk.agents import Agent
from google.protobuf.json_format import MessageToDict

from . import catalog
from . import quote_engine as qe
from .profile import load_profile

log = logging.getLogger("supplier_agent")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

SUPPLIER_INSTRUCTION = (
    "You are the sales agent of an Indian FMCG distributor. Reply with one short, polite sentence "
    "of text summarising the offer produced by your tool (quote, revise or accept_po). Never "
    "invent prices, quantities, terms or account details; the tool output is the only source of "
    "numbers and it is sent separately as a JSON data part."
)


# --------------------------------------------------------------------------- normalisation
def _intify(v: Any) -> Any:
    """protobuf Struct carries numbers as float; turn integral floats back into int."""
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return {k: _intify(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_intify(x) for x in v]
    return v


def _infer_type(d: dict) -> str:
    t = str(d.get("type") or d.get("message_type") or "").upper()
    if t:
        return t
    if "order_id" in d:
        return "PO"
    if "round" in d or any("target_price_paise" in ln for ln in d.get("lines", [])):
        return "COUNTER"
    if "decision" in d:
        return "FINAL"
    return "RFQ"


def _echo(req: dict, profile: dict) -> dict:
    return {
        "negotiation_id": req.get("negotiation_id"),
        "nonce": req.get("nonce"),
        "supplier_id": profile["id"],
    }


# --------------------------------------------------------------------------- tools
def quote(rfq: dict) -> dict:
    """Answer an RFQ with a QUOTE (round 1) from the deterministic quote engine."""
    profile = load_profile()
    prods = catalog.products()
    lines, unavailable = [], []
    for ln in rfq.get("lines", []):
        gtin, qty = str(ln.get("gtin")), int(ln.get("qty") or 0)
        row = prods.get(gtin)
        if row is None:
            unavailable.append(gtin)
            continue
        lines.append({
            "gtin": gtin, "name": row["name"], "qty": qty,
            "unit_price_paise": qe.quote_price(profile, row, qty),
            "mrp_paise": row["mrp_paise"],
            "moq": qe.moq(profile, row),
            "available_qty": catalog.stock_for(profile, gtin),
        })
    return {"type": "QUOTE", **_echo(rfq, profile), "round": 1, "lines": lines,
            "unavailable": unavailable, **qe.terms(profile, 1)}


def revise(counter: dict) -> dict:
    """Answer a COUNTER with a REVISED offer; concessions follow the published schedule."""
    profile = load_profile()
    prods = catalog.products()
    rnd = max(2, min(int(counter.get("round") or 2), qe.MAX_ROUND))
    top_match = counter.get("match_price_paise")
    lines, unavailable = [], []
    for ln in counter.get("lines", []):
        gtin, qty = str(ln.get("gtin")), int(ln.get("qty") or 0)
        row = prods.get(gtin)
        if row is None:
            unavailable.append(gtin)
            continue
        match = ln.get("match_price_paise")
        if match is None and isinstance(top_match, dict):
            match = top_match.get(gtin)
        elif match is None and isinstance(top_match, (int, float)) and len(counter.get("lines", [])) == 1:
            match = top_match
        target = ln.get("target_price_paise")
        lines.append({
            "gtin": gtin, "name": row["name"], "qty": qty,
            "unit_price_paise": qe.concede(profile, row, rnd, target, qty, match),
            "mrp_paise": row["mrp_paise"],
            "moq": qe.moq(profile, row),
            "available_qty": catalog.stock_for(profile, gtin),
            "target_price_paise": target,
            "matched": match is not None and profile.get("match_tolerance_bps") is not None,
        })
    return {"type": "REVISED", **_echo(counter, profile), "round": rnd, "final": rnd >= qe.MAX_ROUND,
            "lines": lines, "unavailable": unavailable, **qe.terms(profile, rnd)}


def accept_po(po: dict) -> dict:
    """Acknowledge a PO. Lines priced below our floor are rejected, never silently accepted."""
    profile = load_profile()
    prods = catalog.products()
    rnd = qe.MAX_ROUND
    lines, rejected, total = [], [], 0
    for ln in po.get("lines", []):
        gtin, qty = str(ln.get("gtin")), int(ln.get("qty") or 0)
        row = prods.get(gtin)
        price = ln.get("unit_price_paise")
        if row is None:
            rejected.append({"gtin": gtin, "reason": "UNKNOWN_GTIN"})
            continue
        price = int(price) if price is not None else qe.scheduled(profile, row, rnd)
        if price < qe.floor(profile, row):
            rejected.append({"gtin": gtin, "reason": "BELOW_FLOOR"})
            continue
        lines.append({"gtin": gtin, "qty": qty, "unit_price_paise": price, "line_total_paise": price * qty})
        total += price * qty
    t = qe.terms(profile, rnd)
    status = "accepted" if lines and not rejected else ("partial" if lines else "rejected")
    return {"type": "PO_ACK", **_echo(po, profile), "order_id": po.get("order_id"),
            "cart_hash": po.get("cart_hash"), "status": status, "lines": lines, "rejected": rejected,
            "total_paise": total, "advance_paise": total * t["advance_pct"] // 100, **t}


def final_ack(final: dict) -> dict:
    profile = load_profile()
    return {"type": "FINAL", **_echo(final, profile), "decision": "acknowledged",
            "buyer_decision": final.get("decision"), "lines": final.get("lines", []),
            **qe.terms(profile, qe.MAX_ROUND)}


def build_reply(req: dict) -> dict:
    t = _infer_type(req)
    if t == "RFQ":
        return quote(req)
    if t == "COUNTER":
        return revise(req)
    if t == "PO":
        return accept_po(req)
    if t == "FINAL":
        return final_ack(req)
    return {"type": "ERROR", **_echo(req, load_profile()), "error": f"unsupported message type {t}"}


def build_agent() -> Agent:
    profile = load_profile()
    return Agent(name=profile["id"], model=GEMINI_MODEL, description=profile["description"],
                 instruction=SUPPLIER_INSTRUCTION, tools=[quote, revise, accept_po])


# --------------------------------------------------------------------------- text phrasing
def template_sentence(profile: dict, data: dict) -> str:
    n = len(data.get("lines", []))
    t = data.get("type")
    if t == "QUOTE":
        return f"{profile['name']} quotes {n} line(s), delivery in {data['delivery_days']} day(s), terms: {data['payment_terms']}."
    if t == "REVISED":
        return f"{profile['name']} revises {n} line(s) for round {data['round']}, terms: {data['payment_terms']}."
    if t == "PO_ACK":
        return f"{profile['name']} {data['status']} order {data.get('order_id')}, total Rs {data['total_paise'] / 100:.2f}."
    if t == "FINAL":
        return f"{profile['name']} acknowledges your final decision."
    return f"{profile['name']} could not process that message."


_client = None


def _genai():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                               location=os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1"))
    return _client


async def phrase(profile: dict, data: dict) -> str:
    fallback = template_sentence(profile, data)
    if os.environ.get("SUPPLIER_USE_LLM", "1") != "1":
        return fallback
    summary = {k: data.get(k) for k in ("type", "round", "delivery_days", "advance_pct", "payment_terms", "status", "total_paise")}
    summary.pop("total_paise", None)
    if data.get("total_paise") is not None:
        summary["total_rs"] = f"{data['total_paise'] / 100:.2f}"
    summary["lines"] = [{"name": ln.get("name"), "unit_price_rs": f"{(ln.get('unit_price_paise') or 0) / 100:.2f}"}
                        for ln in data.get("lines", [])]
    prompt = (f"You are {profile['name']}, a distributor. Write ONE plain sentence (max 30 words, no markdown) "
              f"to the shop owner describing this {data.get('type')} message (an offer, not a placed order "
              f"unless type is PO_ACK). Use only these facts:\n{json.dumps(summary)}")
    try:
        resp = await asyncio.wait_for(
            _genai().aio.models.generate_content(
                model=GEMINI_MODEL, contents=prompt,
                config={"system_instruction": SUPPLIER_INSTRUCTION, "temperature": 0.2, "max_output_tokens": 1024,
                        "thinking_config": {"thinking_level": "minimal"}}),
            timeout=float(os.environ.get("SUPPLIER_LLM_TIMEOUT_S", "8")))
        text = (resp.text or "").strip().replace("\n", " ")
        return text if len(text) >= 20 and text[-1] in ".!?" else fallback
    except Exception as e:  # noqa: BLE001 - phrasing is cosmetic; numbers are already fixed
        log.warning("gemini phrasing failed, using template: %s", e)
        return fallback


# --------------------------------------------------------------------------- A2A executor
def extract_request(message) -> dict:
    """Request JSON = first data part; else JSON found in a text part."""
    if message is None:
        return {}
    for p in message.parts:
        if p.HasField("data"):
            d = MessageToDict(p.data)
            if isinstance(d, dict):
                return _intify(d)
    for p in message.parts:
        if p.HasField("text"):
            s = p.text
            i, j = s.find("{"), s.rfind("}")
            if i != -1 and j > i:
                try:
                    return _intify(json.loads(s[i:j + 1]))
                except json.JSONDecodeError:
                    pass
    return {}


class SupplierExecutor(AgentExecutor):
    def __init__(self, runner=None):
        self.runner = runner  # ADK runner kept for parity with to_a2a; numbers never go through it

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        profile = load_profile()
        req = extract_request(context.message)
        if not req.get("nonce") and context.metadata:
            req["nonce"] = context.metadata.get("nonce")
        data = build_reply(req)
        text = await phrase(profile, data)
        inj = qe.injection(profile, int(data.get("round") or qe.MAX_ROUND))
        if inj:
            text = f"{text} {inj}"
        msg = new_message(parts=[new_text_part(text), new_data_part(data, media_type="application/json")],
                          context_id=context.context_id)
        await event_queue.enqueue_event(msg)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        return None
