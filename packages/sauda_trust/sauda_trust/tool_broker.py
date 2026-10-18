"""Tool broker: every agent tool passes through here. Validates args (type hints, strict), builds the gate
context via a pluggable provider, evaluates the gate, writes `gate.decision` to the ledger, then executes
or raises ToolDenied."""
from __future__ import annotations

import functools
import inspect
import logging
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict, ValidationError, create_model

from .mandates import IntentMandate
from .policy_gate import Action, GateContext, GateReport, evaluate

log = logging.getLogger(__name__)


class ToolDenied(Exception):
    status = "denied"

    def __init__(self, reasons: list[str], report: GateReport | None = None):
        super().__init__(", ".join(reasons))
        self.reasons = list(reasons)
        self.report = report

    def to_dict(self) -> dict:
        return {"status": self.status, "reasons": self.reasons}


class ConfirmationRequired(ToolDenied):
    """Gate said CONFIRM and the owner has not confirmed (ctx.owner_confirmed is False)."""
    status = "confirmation_required"


@dataclass
class BrokerContext:
    action: Action
    mandate: IntentMandate
    ctx: GateContext
    negotiation_id: str


# provider(tool_name, validated_args) -> BrokerContext. Set once by the buyer agent at startup.
ContextProvider = Callable[[str, dict], BrokerContext]
_provider: ContextProvider | None = None
_ledger_append: Callable[..., Any] | None = None


def set_context_provider(fn: ContextProvider | None) -> None:
    global _provider
    _provider = fn


def set_ledger_append(fn: Callable[..., Any] | None) -> None:
    """Override the ledger writer (tests). Default: sauda_ledger.append."""
    global _ledger_append
    _ledger_append = fn


def _append(*a, **kw):
    if _ledger_append is not None:
        return _ledger_append(*a, **kw)
    from sauda_ledger import append

    return append(*a, **kw)


def _args_model(fn):
    hints = typing.get_type_hints(fn)
    fields = {}
    for name, p in inspect.signature(fn).parameters.items():
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) or name in ("tool_context",):
            continue
        ann = hints.get(name, Any)
        fields[name] = (ann, ... if p.default is p.empty else p.default)
    return create_model(f"{fn.__name__}_args", __config__=ConfigDict(extra="forbid", strict=False), **fields)


def broker(rules: list[str], *, provider: ContextProvider | None = None, return_denial: bool = False,
           name: str | None = None):
    """Wrap a tool. rules: gate rule ids to evaluate (e.g. ['R1','R12']). provider overrides the global
    context provider. return_denial=True returns ToolDenied.to_dict() instead of raising. name: tool name
    passed to the provider and logged (default: the function name)."""
    tool_name = name

    def deco(fn):
        model = _args_model(fn)
        sig = inspect.signature(fn)
        name = tool_name or fn.__name__

        def _gate(args, kwargs) -> dict:
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            raw = {k: v for k, v in bound.arguments.items() if k in model.model_fields}
            try:
                validated = model(**raw).model_dump()
            except ValidationError as e:
                raise ToolDenied(["GATE_ERROR"]) from e  # bad args never reach the gate
            prov = provider or _provider
            try:
                if prov is None:
                    raise RuntimeError("no context provider configured")
                bc = prov(name, validated)
                report = evaluate(bc.action, bc.mandate, bc.ctx, rules=rules)
            except ToolDenied:
                raise
            except Exception as e:
                log.exception("broker context failed for %s", name)
                raise ToolDenied(["GATE_ERROR"]) from e
            try:
                _append(bc.negotiation_id, "gate.decision", "gate", {"tool": name, "args": validated, **report.to_dict()})
            except Exception as e:  # no decision without a ledger record (fail closed)
                log.exception("ledger append failed for %s", name)
                raise ToolDenied(["GATE_ERROR"], report) from e
            if report.verdict == "DENY":
                raise ToolDenied(report.reasons, report)
            if report.verdict == "CONFIRM" and not bc.ctx.owner_confirmed:
                raise ConfirmationRequired(report.reasons, report)
            bound.arguments.update({k: v for k, v in validated.items() if k in bound.arguments})
            return bound

        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*args, **kwargs):
                try:
                    bound = _gate(args, kwargs)
                except ToolDenied as d:
                    if return_denial:
                        return d.to_dict()
                    raise
                return await fn(*bound.args, **bound.kwargs)

            awrapper.gate_rules = list(rules)
            return awrapper

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                bound = _gate(args, kwargs)
            except ToolDenied as d:
                if return_denial:
                    return d.to_dict()
                raise
            return fn(*bound.args, **bound.kwargs)

        wrapper.gate_rules = list(rules)
        return wrapper

    return deco
