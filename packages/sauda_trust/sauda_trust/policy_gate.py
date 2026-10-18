"""Policy gate: twelve deterministic rules (SPEC 11.1). Pure: no I/O; everything arrives via GateContext.
Any exception -> DENY with GATE_ERROR (fail closed)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .mandates import IntentMandate

Verdict = Literal["ALLOW", "CONFIRM", "DENY"]
ALL_RULES = [f"R{i}" for i in range(1, 13)]
IST = timezone(timedelta(hours=5, minutes=30))
COMMIT_ACTIONS = ("place_order", "issue_payment_mandate")


@dataclass
class RuleResult:
    rule: str
    verdict: Verdict
    reason: str
    detail: dict = field(default_factory=dict)


@dataclass
class GateReport:
    verdict: Verdict
    results: list[RuleResult]
    action: str
    mandate_id: str

    @property
    def reasons(self) -> list[str]:
        return sorted({r.reason for r in self.results if r.verdict != "ALLOW"})

    def to_dict(self) -> dict:
        return {**asdict(self), "reasons": self.reasons}

    dict = to_dict  # loop code calls report.dict()


class OfferLine(BaseModel):
    model_config = ConfigDict(extra="allow")
    gtin: str
    qty: int | None = None  # None -> the mandate line's qty
    unit_price_paise: int


class ActionItem(BaseModel):
    """One supplier's terms: a quote (action 'offer') or one allocation of a cart."""
    model_config = ConfigDict(extra="allow")
    supplier_id: str
    lines: list[OfferLine] = Field(default_factory=list)
    subtotal_paise: int | None = None
    delivery_days: int | None = None
    advance_pct: float = 0
    payout_vpa: str | None = None


class Action(BaseModel):
    """kind: offer | cart | place_order | issue_payment_mandate | draft_order | run_negotiation | explain_cart.
    Single-supplier terms may be given at top level (supplier_id, lines, ...) or as allocations."""
    model_config = ConfigDict(extra="allow")
    kind: str
    negotiation_id: str | None = None
    allocations: list[ActionItem] = Field(default_factory=list)
    supplier_id: str | None = None
    lines: list[OfferLine] = Field(default_factory=list)
    subtotal_paise: int | None = None
    delivery_days: int | None = None
    advance_pct: float = 0
    payout_vpa: str | None = None
    payee_vpa: str | None = None  # Payment Mandate payee (R8)
    amount_paise: int | None = None
    idempotency_key: str | None = None

    def items(self) -> list[ActionItem]:
        if self.allocations:
            return list(self.allocations)
        if self.supplier_id:
            return [ActionItem(supplier_id=self.supplier_id, lines=self.lines, subtotal_paise=self.subtotal_paise,
                               delivery_days=self.delivery_days, advance_pct=self.advance_pct,
                               payout_vpa=self.payout_vpa or self.payee_vpa)]
        return []


class GateContext(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    now: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mandate_id: str = ""
    mandate_status: str | None = None  # from mandates/{id}.status
    signature_valid: bool = False  # mandates.verify(body, signed) computed by the caller
    kill_switch: bool = False
    # supplier_id -> registry record (dict or registry.Supplier): status, fingerprint, payout_vpa
    suppliers: dict[str, Any] = Field(default_factory=dict)
    # supplier_id -> sha256(canonical(card)) of the card actually fetched this run
    card_fingerprints: dict[str, str] = Field(default_factory=dict)
    # supplier_id -> guard verdict for the message that produced the offer (GuardVerdict, dict, or bool blocked)
    guard_verdicts: dict[str, Any] = Field(default_factory=dict)
    seen_idempotency_keys: set[str] = Field(default_factory=set)
    forecast: dict[str, float] = Field(default_factory=dict)  # gtin -> forecast qty
    reference_prices: dict[str, float] = Field(default_factory=dict)  # gtin -> reference unit price (paise)
    owner_confirmed: bool = False  # True when re-run after the owner approved the confirmation


def _get(rec: Any, key: str):
    if rec is None:
        return None
    return rec.get(key) if isinstance(rec, dict) else getattr(rec, key, None)


def _parse_dt(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=IST)


def _now(ctx: GateContext) -> datetime:
    return ctx.now if ctx.now.tzinfo else ctx.now.replace(tzinfo=UTC)


def _lines(item: ActionItem, m: IntentMandate) -> list[tuple[str, int, int]]:
    mq = {l.gtin: l.qty for l in m.lines}
    return [(l.gtin, l.qty if l.qty is not None else mq.get(l.gtin, 0), l.unit_price_paise) for l in item.lines]


def _subtotal(item: ActionItem, m: IntentMandate) -> int:
    if item.subtotal_paise is not None:
        return item.subtotal_paise
    return sum(q * p for _, q, p in _lines(item, m))


def _ok(rule: str, **detail) -> RuleResult:
    return RuleResult(rule, "ALLOW", "OK", detail)


# ------------------------------------------------------------------ rules
def r1(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    ok_status = ("active", "consumed") if a.kind == "issue_payment_mandate" else ("active",)
    problems = []
    if not c.signature_valid:
        problems.append("signature_invalid")
    if c.mandate_status not in ok_status:
        problems.append(f"status_{c.mandate_status}")
    if _now(c) >= _parse_dt(m.expires_at):
        problems.append("expired")
    if problems:
        return RuleResult("R1", "DENY", "MANDATE_INVALID", {"problems": problems})
    return _ok("R1")


def r2(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    items = a.items()
    bad = {}
    if not items:  # pre-negotiation: at least one allowed supplier must be allowlisted
        live = [s for s in m.allowed_supplier_ids if _get(c.suppliers.get(s), "status") == "allowlisted"]
        if not live:
            return RuleResult("R2", "DENY", "SUPPLIER_UNKNOWN", {"allowlisted": []})
        return _ok("R2", allowlisted=live, skipped=[s for s in m.allowed_supplier_ids if s not in live])
    for it in items:
        sid = it.supplier_id
        rec = c.suppliers.get(sid)
        if sid not in m.allowed_supplier_ids:
            bad[sid] = "not_in_mandate"
        elif rec is None:
            bad[sid] = "not_registered"
        elif _get(rec, "status") != "allowlisted":
            bad[sid] = f"status_{_get(rec, 'status')}"
        elif not c.card_fingerprints.get(sid) or c.card_fingerprints.get(sid) != _get(rec, "fingerprint"):
            bad[sid] = "fingerprint_mismatch"
    if bad:
        return RuleResult("R2", "DENY", "SUPPLIER_UNKNOWN", {"suppliers": bad})
    return _ok("R2")


def r3(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    # A stated subtotal can never understate the lines it covers: count whichever is larger.
    total = sum(max(_subtotal(it, m), sum(q * p for _, q, p in _lines(it, m))) for it in a.items())
    if a.amount_paise is not None:
        total = max(total, a.amount_paise)
    if total > m.budget_paise:
        return RuleResult("R3", "DENY", "OVER_BUDGET", {"total_paise": total, "budget_paise": m.budget_paise})
    return _ok("R3", total_paise=total, budget_paise=m.budget_paise)


def r4(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    ceil = {l.gtin: l.ceiling_paise for l in m.lines}
    over = []
    bad = []
    for it in a.items():
        for gtin, q, price in _lines(it, m):
            if gtin in ceil and (price <= 0 or q <= 0):  # zero/negative money or qty would shrink the total (R3)
                bad.append({"supplier_id": it.supplier_id, "gtin": gtin, "unit_price_paise": price, "qty": q})
                continue
            if gtin not in ceil or price > ceil[gtin]:
                over.append({"supplier_id": it.supplier_id, "gtin": gtin, "unit_price_paise": price,
                             "ceiling_paise": ceil.get(gtin)})
    if bad:
        return RuleResult("R4", "DENY", "INVALID_AMOUNT", {"lines": bad, "over_ceiling": over})
    if over:
        return RuleResult("R4", "DENY", "OVER_CEILING", {"lines": over})
    return _ok("R4")


def r5(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    # written as "not within [0, max]" so NaN or a negative advance also fails
    over = {it.supplier_id: it.advance_pct for it in a.items() if not (0 <= it.advance_pct <= m.max_advance_pct)}
    if over:
        return RuleResult("R5", "DENY", "ADVANCE_TOO_HIGH", {"advance_pct": over, "max_advance_pct": m.max_advance_pct})
    return _ok("R5")


def r6(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    deliver_by = date.fromisoformat(m.deliver_by[:10])
    today = _now(c).astimezone(IST).date()
    late = {}
    for it in a.items():
        if it.delivery_days is None or today + timedelta(days=it.delivery_days) > deliver_by:
            late[it.supplier_id] = it.delivery_days
    if late:
        return RuleResult("R6", "CONFIRM", "LATE_DELIVERY", {"delivery_days": late, "deliver_by": m.deliver_by})
    return _ok("R6")


def r7(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    qty: dict[str, int] = {}
    flags = []
    for it in a.items():
        for gtin, q, price in _lines(it, m):
            qty[gtin] = qty.get(gtin, 0) + q
            ref = c.reference_prices.get(gtin)
            if ref and price < 0.5 * ref:
                flags.append({"gtin": gtin, "supplier_id": it.supplier_id, "check": "price_too_low",
                              "unit_price_paise": price, "reference_paise": ref})
    for gtin, q in qty.items():
        f = c.forecast.get(gtin)
        if f is not None and q > f * 1.5:
            flags.append({"gtin": gtin, "check": "qty_above_forecast", "qty": q, "forecast": f})
    if flags:
        return RuleResult("R7", "CONFIRM", "ANOMALY", {"flags": flags})
    return _ok("R7")


def r8(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    bad = {}
    if a.kind == "issue_payment_mandate":
        items = a.items()
        if not a.payee_vpa or not items:
            return RuleResult("R8", "DENY", "PAYEE_MISMATCH", {"payee_vpa": a.payee_vpa, "problem": "missing"})
        for it in items:
            reg = _get(c.suppliers.get(it.supplier_id), "payout_vpa")
            if not reg or a.payee_vpa != reg:
                bad[it.supplier_id] = {"claimed": a.payee_vpa, "registered": reg}
    else:
        for it in a.items():
            reg = _get(c.suppliers.get(it.supplier_id), "payout_vpa")
            claimed = it.payout_vpa
            if not reg or (claimed is not None and claimed != reg):
                bad[it.supplier_id] = {"claimed": claimed, "registered": reg}
    if bad:
        return RuleResult("R8", "DENY", "PAYEE_MISMATCH", {"suppliers": bad})
    return _ok("R8")


def _blocked(v: Any) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    b = _get(v, "blocked")
    return None if b is None else bool(b)


def r9(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    bad = {}
    for it in a.items():
        b = _blocked(c.guard_verdicts.get(it.supplier_id))
        if b is not False:  # missing verdict counts as blocked (fail closed)
            bad[it.supplier_id] = "missing" if b is None else "blocked"
    if bad:
        return RuleResult("R9", "DENY", "GUARD_BLOCKED", {"suppliers": bad})
    return _ok("R9")


def r10(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    if a.kind in COMMIT_ACTIONS and m.autonomy_tier < 3:
        if c.owner_confirmed:
            return _ok("R10", owner_confirmed=True)
        return RuleResult("R10", "CONFIRM", "OWNER_APPROVAL", {"autonomy_tier": m.autonomy_tier})
    return _ok("R10")


def r11(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    if not a.idempotency_key:
        return RuleResult("R11", "DENY", "DUPLICATE", {"problem": "missing_idempotency_key"})
    if a.idempotency_key in c.seen_idempotency_keys:
        return RuleResult("R11", "DENY", "DUPLICATE", {"idempotency_key": a.idempotency_key})
    return _ok("R11")


def r12(a: Action, m: IntentMandate, c: GateContext) -> RuleResult:
    if c.kill_switch or c.mandate_status == "revoked":
        return RuleResult("R12", "DENY", "REVOKED", {"kill_switch": c.kill_switch, "mandate_status": c.mandate_status})
    return _ok("R12")


RULES: dict[str, Callable[[Action, IntentMandate, GateContext], RuleResult]] = {
    "R1": r1, "R2": r2, "R3": r3, "R4": r4, "R5": r5, "R6": r6,
    "R7": r7, "R8": r8, "R9": r9, "R10": r10, "R11": r11, "R12": r12,
}


def aggregate(results: list[RuleResult]) -> Verdict:
    vs = {r.verdict for r in results}
    return "DENY" if "DENY" in vs else "CONFIRM" if "CONFIRM" in vs else "ALLOW"


def evaluate(action: Action | dict, mandate: IntentMandate | dict, ctx: GateContext | dict,
             rules: list[str] | None = None) -> GateReport:
    kind = _get(action, "kind") or "unknown"
    mid = _get(ctx, "mandate_id") or _get(mandate, "mandate_id") or ""
    try:
        a = action if isinstance(action, Action) else Action(**action)
        m = mandate if isinstance(mandate, IntentMandate) else IntentMandate(**mandate)
        c = ctx if isinstance(ctx, GateContext) else GateContext(**ctx)
        mid = c.mandate_id or m.mandate_id or ""
        selected = list(rules) if rules else ALL_RULES
        results: list[RuleResult] = []
        for rid in selected:
            fn = RULES.get(rid)
            if fn is None:
                results.append(RuleResult(rid, "DENY", "GATE_ERROR", {"error": "unknown_rule"}))
                continue
            try:
                results.append(fn(a, m, c))
            except Exception as e:
                results.append(RuleResult(rid, "DENY", "GATE_ERROR", {"error": f"{type(e).__name__}: {e}"}))
        if not results:
            results.append(RuleResult("GATE", "DENY", "GATE_ERROR", {"error": "no_rules"}))
        return GateReport(aggregate(results), results, a.kind, mid)
    except Exception as e:
        return GateReport("DENY", [RuleResult("GATE", "DENY", "GATE_ERROR", {"error": f"{type(e).__name__}: {e}"})],
                          str(kind), str(mid))
