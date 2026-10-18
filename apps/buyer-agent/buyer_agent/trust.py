"""Thin adapter over sauda_trust / sauda_ledger so the buyer agent has one place that touches them."""
from __future__ import annotations

import logging
from typing import Any

from sauda_trust import guard as _guard
from sauda_trust import mandates as _mandates
from sauda_trust import registry as _registry
from sauda_trust.policy_gate import Action, GateContext, GateReport, evaluate as _evaluate

from . import store
from .deps import settings

log = logging.getLogger("buyer_agent.trust")


def no_floats(v):
    """Ledger payloads carry only ints/strings/bools/lists/dicts so the browser can recompute the canonical
    hash (JS cannot reproduce Python float formatting). Integral floats -> int, others -> string."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else repr(v)
    if isinstance(v, dict):
        return {str(k): no_floats(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [no_floats(x) for x in v]
    if hasattr(v, "model_dump"):
        return no_floats(v.model_dump(mode="json"))
    if hasattr(v, "to_dict"):
        return no_floats(v.to_dict())
    return v


def ledger_append(nid: str, type_: str, actor: str, payload: dict):
    from sauda_ledger import append  # imported lazily so the app boots while T is still landing

    # payees are masked when written: /events serves these payloads verbatim to the public
    return append(nid, type_, actor, _registry.mask_payload(no_floats(payload)))


def _broker_append(nid, type_, actor, payload, *a, **kw):
    return ledger_append(nid, type_, actor, payload)


from sauda_trust import tool_broker as _tb  # noqa: E402

_tb.set_ledger_append(_broker_append)


def verify_chain(nid: str):
    from sauda_ledger import verify_chain as _vc

    return _vc(nid)


# ---------------------------------------------------------------- mandates
def get_mandate(mid: str):
    return _mandates.get(mid) if mid else None


def intent_of(mrec) -> Any:
    return mrec.intent()


def create_mandate(kind: str, body: dict, owner_uid: str):
    return _mandates.create(kind, body, owner_uid)


def mark_mandate(mid: str, status: str) -> None:
    _mandates.mark(mid, status)


def mandate_status(mid: str) -> str | None:
    m = get_mandate(mid)
    return m.status if m else None


# ---------------------------------------------------------------- registry / guard
def supplier(sid: str):
    return _registry.get_supplier(sid)


def card_fingerprint(card: dict) -> str:
    return _registry.card_fingerprint(card)


def verify_card(sid: str, card: dict) -> bool:
    return _registry.verify_card(sid, card, quarantine_on_mismatch=False)


def quarantine(sid: str, reason: str, nid: str | None = None) -> None:
    try:
        _registry.quarantine(sid, reason, negotiation_id=nid)
    except Exception:
        log.exception("quarantine failed")


def screen(text: str, direction: str = "inbound", max_advance_pct: float = 20):
    return _guard.screen(text, direction, use_model_armor=settings().use_model_armor, max_advance_pct=max_advance_pct)


def verdict_dict(v) -> dict:
    d = v.model_dump() if hasattr(v, "model_dump") else dict(v)
    d.pop("raw", None)  # keep ledger payloads small; categories and source are the evidence
    return d


# ---------------------------------------------------------------- gate
def build_ctx(mrec, *, supplier_ids: list[str] | None = None, card_fingerprints: dict | None = None,
              guard_verdicts: dict | None = None, seen_keys: set | None = None, forecast: dict | None = None,
              reference_prices: dict | None = None, owner_confirmed: bool = False) -> GateContext:
    body = mrec.body
    sids = supplier_ids if supplier_ids is not None else list(body.get("allowed_supplier_ids", []))
    regs = {}
    for sid in sids:
        try:
            s = supplier(sid)
            if s is not None:
                regs[sid] = s.model_dump()
        except Exception:
            log.exception("registry read failed for %s", sid)
    shop = store.shop(body.get("shop_id", ""))
    return GateContext(
        mandate_id=mrec.mandate_id,
        mandate_status=mrec.status,
        signature_valid=mrec.signature_valid(),
        kill_switch=bool(shop.get("kill_switch")),
        suppliers=regs,
        card_fingerprints=card_fingerprints or {},
        guard_verdicts=guard_verdicts or {},
        seen_idempotency_keys=seen_keys or set(),
        forecast=forecast if forecast is not None else {l["gtin"]: l["qty"] for l in body.get("lines", [])},
        reference_prices=reference_prices or {},
        owner_confirmed=owner_confirmed,
    )


def gate(action: dict | Action, mrec, ctx: GateContext, rules: list[str] | None = None,
         nid: str | None = None, extra: dict | None = None) -> GateReport:
    report = _evaluate(action, mrec.intent(), ctx, rules=rules)
    if nid:
        payload = {**report.to_dict(), **(extra or {})}
        try:
            ledger_append(nid, "gate.decision", "gate", payload)
        except Exception:
            log.exception("ledger append gate.decision failed")
            raise
    return report


__all__ = ["Action", "GateContext", "GateReport"]
