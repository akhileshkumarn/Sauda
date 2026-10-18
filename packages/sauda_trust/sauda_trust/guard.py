"""Guard: Model Armor screening of supplier text (inbound) and owner-facing text (outbound), with a regex
fallback. Fail closed: a Model Armor timeout or error counts as blocked."""
from __future__ import annotations

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from . import settings

log = logging.getLogger(__name__)
Direction = Literal["inbound", "outbound"]


class GuardVerdict(BaseModel):
    blocked: bool
    source: Literal["model_armor", "regex", "timeout"]
    categories: list[str] = Field(default_factory=list)
    raw: dict = Field(default_factory=dict)
    direction: Direction = "inbound"


_INJECTION = [
    re.compile(r"\bSYSTEM\s*:", re.IGNORECASE),
    re.compile(r"\bignore\b.{0,60}?\b(cap|caps|budget|limit|limits|ceiling|instructions?|rules?|mandate)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\b(disregard|override|forget)\b.{0,40}?\b(previous|prior|above|all)\b.{0,20}?\b(instructions?|rules?)\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bthe owner has (raised|approved|increased|authori[sz]ed)\b", re.IGNORECASE),
]
_BANK_CHANGE = [
    re.compile(r"\b(new|changed|updated|different|alternate)\s+(bank|account|a/c|upi|vpa|payee|payment)(\s+(details?|id|number|handle|address|account))?\b", re.IGNORECASE),
    re.compile(r"\b(bank|account|upi|vpa|payment|payee)\s*(details?|id|number|handle)?\s+(have|has)?\s*(been\s+)?(changed|updated)\b", re.IGNORECASE),
    re.compile(r"\b(pay|send|transfer)\b.{0,30}?\b(to|on)\b\s+(this|our|the)\s+new\b", re.IGNORECASE | re.DOTALL),
]
_ADVANCE_PCT = re.compile(r"\b(\d{1,3})\s*%\s*(?:of\s+the\s+\w+\s+)?(?:advance|upfront|up-front|prepayment|in advance)", re.IGNORECASE)
_ADVANCE_DEMAND = re.compile(
    r"\b(pay|send|transfer)\b.{0,25}?\b(the\s+)?(advance|upfront|full amount|deposit)\b.{0,15}?\b(now|immediately|today|first|before)\b",
    re.IGNORECASE | re.DOTALL,
)


def regex_screen(text: str, direction: Direction = "inbound", max_advance_pct: float = 20) -> list[str]:
    cats: list[str] = []
    if any(p.search(text) for p in _INJECTION):
        cats.append("prompt_injection")
    if direction == "inbound":  # owner-facing text legitimately describes blocked terms
        if any(p.search(text) for p in _BANK_CHANGE):
            cats.append("bank_detail_change")
        if any(float(m.group(1)) > max_advance_pct for m in _ADVANCE_PCT.finditer(text)) or _ADVANCE_DEMAND.search(text):
            cats.append("advance_payment_demand")
    return cats


def _model_armor(text: str, direction: Direction, timeout: float) -> tuple[bool, list[str], dict]:
    from google.cloud import modelarmor_v1 as ma
    from google.protobuf.json_format import MessageToDict

    s = settings.get_settings()
    client = settings.modelarmor_client()
    if direction == "inbound":
        req = ma.SanitizeUserPromptRequest(name=s.model_armor_template, user_prompt_data=ma.DataItem(text=text))
        resp = client.sanitize_user_prompt(request=req, timeout=timeout, retry=None)
    else:
        req = ma.SanitizeModelResponseRequest(name=s.model_armor_template, model_response_data=ma.DataItem(text=text))
        resp = client.sanitize_model_response(request=req, timeout=timeout, retry=None)
    raw = MessageToDict(type(resp).pb(resp), preserving_proto_field_name=True)
    result = raw.get("sanitization_result", {})
    blocked = result.get("filter_match_state") == "MATCH_FOUND"
    cats: list[str] = []
    for name, fr in (result.get("filter_results") or {}).items():
        for v in fr.values() if isinstance(fr, dict) else []:
            if isinstance(v, dict) and v.get("match_state") == "MATCH_FOUND":
                cats.append(name)
                break
    return blocked, cats, raw


def screen(text: str, direction: Direction = "inbound", *, use_model_armor: bool = True, max_advance_pct: float = 20,
           model_armor_fn=None) -> GuardVerdict:
    """model_armor_fn: override of the Model Armor call (the attack box's guard_timeout scenario injects one that
    times out, so the real fail-closed path below runs without touching the shared client)."""
    rx = regex_screen(text or "", direction, max_advance_pct)
    if not use_model_armor and model_armor_fn is None:
        return GuardVerdict(blocked=bool(rx), source="regex", categories=rx, direction=direction)
    try:
        blocked, cats, raw = (model_armor_fn or _model_armor)(text or "", direction, settings.get_settings().model_armor_timeout_s)
    except Exception as e:  # timeout or any error -> blocked (fail closed)
        log.warning("Model Armor unavailable (%s); failing closed", type(e).__name__)
        return GuardVerdict(blocked=True, source="timeout", categories=sorted(set(rx + ["model_armor_unavailable"])),
                            raw={"error": type(e).__name__, "regex": rx}, direction=direction)
    if blocked:
        return GuardVerdict(blocked=True, source="model_armor", categories=sorted(set(cats + rx)), raw=raw, direction=direction)
    if rx:
        return GuardVerdict(blocked=True, source="regex", categories=rx, raw=raw, direction=direction)
    return GuardVerdict(blocked=False, source="model_armor", categories=[], raw=raw, direction=direction)
