"""Deterministic Negotiator (LLD-2, 11.4). The model never sets a number: targets come from the schedule,
every inbound message is screened by Guard, every offer is gated, and R12 is checked before each round."""
from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Callable

from pydantic import BaseModel, ConfigDict, Field

from .. import store, trust
from .a2a import SpoofSuspected, SupplierClient, SupplierUnavailable
from .cart import allocate

log = logging.getLogger("buyer_agent.negotiator")
MAX_ROUNDS = 3
OFFER_RULES = ["R2", "R4", "R5", "R6", "R7", "R8", "R9"]
CART_RULES = ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R12"]
Emit = Callable[[str, dict], None]


class Revoked(Exception):
    pass


class NegotiationError(Exception):
    pass


MAX_UNIT_PRICE_PAISE = 10_000_000  # ₹1 lakh per unit: anything above is not a kirana price


class QuoteLine(BaseModel):
    model_config = ConfigDict(extra="ignore")
    gtin: str
    unit_price_paise: int = Field(gt=0, le=MAX_UNIT_PRICE_PAISE)
    moq: int = Field(default=1, ge=1)
    available_qty: int | None = Field(default=None, ge=0)
    name: str | None = None


class Quote(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lines: list[QuoteLine] = Field(default_factory=list)
    delivery_days: int | None = Field(default=None, ge=0, le=365)
    advance_pct: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    payout_vpa: str | None = None
    validity_s: int | None = None
    payment_terms: str | None = None
    round: int | None = None
    final: bool = False


class Unparseable(Exception):
    pass


def parse_quote(reply) -> Quote:
    """The QUOTE/REVISED data part is parsed by Pydantic (strict shape, bounded money, extra fields ignored).
    Prices are never extracted from free text by a model: a reply without a valid structured data part is
    marked unparseable and gets no allocation."""
    try:
        q = Quote.model_validate(reply.data or {})
    except Exception as e:
        raise Unparseable(f"invalid data part: {type(e).__name__}") from e
    if not q.lines:
        raise Unparseable("no structured quote lines")
    return q


def _screen_text(reply) -> str:
    d = reply.data or {}
    extra = [str(d.get(k)) for k in ("payment_terms", "note", "message", "bundle_note", "text") if d.get(k)]
    return "\n".join([reply.text or ""] + extra)


class Negotiator:
    def __init__(self, emit: Emit | None = None):
        self.emit = emit or (lambda name, data: None)

    def _check_active(self, nid: str, mrec) -> None:
        cur = trust.get_mandate(mrec.mandate_id)
        shop = store.shop(cur.shop_id if cur else "")
        if cur is None or cur.status != "active" or shop.get("kill_switch"):
            if cur is not None:
                ctx = trust.build_ctx(cur)
                rep = trust.gate({"kind": "run_negotiation", "negotiation_id": nid}, cur, ctx, rules=["R1", "R12"], nid=nid)
                self.emit("gate.report", {"action": "run_negotiation", "verdict": rep.verdict, "results": rep.to_dict()["results"]})
            store.update_negotiation(nid, status="cancelled", ended_at=store.iso())
            raise Revoked("mandate is not active (revoked, expired or kill switch)")

    def run(self, nid: str) -> dict:
        n = store.negotiation(nid)
        if not n or not n.get("intent_mandate_id"):
            raise NegotiationError("negotiation has no signed intent mandate")
        mrec = trust.get_mandate(n["intent_mandate_id"])
        if mrec is None:
            raise NegotiationError("intent mandate not found")
        body = mrec.body
        self._check_active(nid, mrec)
        prods = store.products()
        pnames = {g: p.get("name", g) for g, p in prods.items()}
        mlines = {str(l["gtin"]): l for l in body["lines"]}
        refs = {g: float(prods.get(g, {}).get("mrp_paise") or l["ceiling_paise"]) for g, l in mlines.items()}

        # ---- load suppliers (card fetch + fingerprint, R2) ----
        clients: dict[str, SupplierClient] = {}
        for sid in body.get("allowed_supplier_ids", [])[:3]:
            try:
                clients[sid] = SupplierClient.load(sid)
            except SupplierUnavailable as e:
                log.warning("%s", e)
                self.emit("agent.tool", {"name": "supplier.load", "status": f"{sid} unreachable"})
        fps = {sid: c.card_fingerprint for sid, c in clients.items()}
        names = {sid: c.name for sid, c in clients.items()}
        for sid, c in list(clients.items()):
            if not c.verified:
                ctx = trust.build_ctx(mrec, card_fingerprints=fps)
                rep = trust.gate({"kind": "offer", "negotiation_id": nid, "supplier_id": sid}, mrec, ctx, rules=["R2"],
                                 nid=nid, extra={"supplier_id": sid, "round": 0})
                self.emit("gate.report", {"action": "offer", "supplier_id": sid, "verdict": rep.verdict,
                                          "results": rep.to_dict()["results"], "reasons": rep.reasons})
                del clients[sid]
        store.update_negotiation(nid, supplier_ids=list(clients), status="rfq_sent")
        if not clients:
            store.update_negotiation(nid, status="failed", ended_at=store.iso())
            raise NegotiationError("no verified supplier reachable")

        deliver_by = body["deliver_by"]
        rfq = {
            "type": "RFQ",
            "lines": [{"gtin": g, "qty": int(l["qty"])} for g, l in mlines.items()],
            "deliver_by": deliver_by,
            "max_advance_pct": body["max_advance_pct"],
            "respond_by": store.iso(store.now() + timedelta(seconds=60)),
        }
        rfq_text = (f"Request for quotation from Sauda (buyer agent) for {len(mlines)} lines, "
                    f"deliver by {deliver_by}, max advance {body['max_advance_pct']}%. Please quote per line.")

        clean: dict[str, dict] = {}       # sid -> latest gate-allowed quote (dict)
        opening: dict[str, dict[str, int]] = {}
        prev_prices: dict[str, dict[str, int]] = {}
        hostile: dict[str, int] = {}      # sid -> guard-blocked/denied message count
        active = dict(clients)
        target: dict[str, int] = {}
        exchanges = 0
        blocked_total = 0
        last_round = 0

        for rnd in range(1, MAX_ROUNDS + 1):
            self._check_active(nid, mrec)  # R12 before every round
            store.update_negotiation(nid, round=rnd, status="quoting")
            last_round = rnd
            if not active:
                break
            # ---- build outbound messages ----
            outbound: dict[str, tuple[dict, str, str]] = {}
            for sid in active:
                if rnd == 1:
                    data, text, kind = rfq, rfq_text, "rfq.sent"
                else:
                    src = clean.get(sid)
                    gtins = [l["gtin"] for l in src["lines"]] if src else list(mlines)
                    lines = []
                    for g in gtins:
                        if g not in target:
                            continue
                        lines.append({"gtin": g, "qty": int(mlines[g]["qty"]), "target_price_paise": self._counter_price(g, rnd, clean, target, mlines)})
                    if not lines:
                        continue
                    data = {"type": "COUNTER", "round": rnd, "lines": lines,
                            "bundle_note": f"Festival order of {len(lines)} lines; we can confirm today at these targets."}
                    text = f"Counter-offer round {rnd} from Sauda for {len(lines)} lines (target prices in the data part)."
                    kind = "counter.sent"
                nonce = uuid.uuid4().hex
                trust.ledger_append(nid, kind, "buyer", {"supplier_id": sid, "round": rnd, "nonce": nonce, "message": data})
                if kind == "counter.sent":
                    store.save_offer({"negotiation_id": nid, "supplier_id": sid, "round": rnd, "direction": "counter",
                                      "lines": data["lines"], "guard_verdict": "n/a"})
                outbound[sid] = (data, text, nonce)
            if not outbound:
                break
            # ---- send in parallel ----
            results: dict[str, object] = {}
            with ThreadPoolExecutor(max_workers=len(outbound)) as ex:
                futs = {sid: ex.submit(active[sid].send, nid, d, t, nonce) for sid, (d, t, nonce) in outbound.items()}
                for sid, f in futs.items():
                    try:
                        results[sid] = f.result()
                    except Exception as e:  # noqa: BLE001
                        results[sid] = e
            changed = False
            for sid, res in results.items():
                exchanges += 1
                if isinstance(res, SpoofSuspected):
                    trust.ledger_append(nid, "supplier.spoof_suspected", "buyer", {"supplier_id": sid, "round": rnd, "error": str(res)})
                    trust.quarantine(sid, "NONCE_NOT_ECHOED", nid)
                    active.pop(sid, None)
                    clean.pop(sid, None)
                    continue
                if isinstance(res, Exception):
                    log.warning("supplier %s failed round %s: %s", sid, rnd, res)
                    self.emit("agent.tool", {"name": "a2a.send", "status": f"{sid} unreachable in round {rnd}"})
                    active.pop(sid, None)
                    continue
                reply = res
                raw_hash = store.sha256_json({"text": reply.text, "data": reply.data})
                direction = "quote" if rnd == 1 else ("final" if reply.data.get("final") or str(reply.data.get("type", "")).upper() == "FINAL" else "revised")
                trust.ledger_append(nid, "offer.received", sid, {"supplier_id": sid, "round": rnd, "direction": direction,
                                                                  "raw_message_hash": raw_hash, "text": reply.text, "data": reply.data})
                verdict = trust.screen(_screen_text(reply), "inbound", max_advance_pct=float(body["max_advance_pct"]))
                vd = trust.verdict_dict(verdict)
                trust.ledger_append(nid, "guard.verdict", "guard", {"supplier_id": sid, "round": rnd, "text": reply.text, **vd})
                self.emit("guard.verdict", {"supplier_id": sid, "round": rnd, "blocked": verdict.blocked,
                                            "categories": vd.get("categories", []), "source": vd.get("source")})
                # Quote parsing: data part via Pydantic; the Gemini fallback only ever sees screened-clean text.
                unparseable = False
                try:
                    quote = parse_quote(reply)
                except Unparseable as e:
                    quote, unparseable = Quote(), True
                    trust.ledger_append(nid, "offer.unparseable", "buyer", {"supplier_id": sid, "round": rnd,
                                                                             "raw_message_hash": raw_hash, "problem": str(e)})
                    self.emit("agent.tool", {"name": "offer.parse", "status": f"{sid} round {rnd}: unparseable offer ignored"})
                qd = quote.model_dump()
                offer_lines = [{"gtin": l.gtin, "qty": int(mlines.get(l.gtin, {}).get("qty", 0)), "unit_price_paise": l.unit_price_paise,
                                "moq": l.moq, "available_qty": l.available_qty} for l in quote.lines if l.gtin in mlines]
                store.save_offer({"negotiation_id": nid, "supplier_id": sid, "round": rnd, "direction": direction,
                                  "lines": offer_lines, "delivery_days": quote.delivery_days, "advance_pct": quote.advance_pct,
                                  "payout_vpa": quote.payout_vpa, "guard_verdict": "blocked" if verdict.blocked else "clean",
                                  "guard_categories": vd.get("categories", []), "raw_message_hash": raw_hash,
                                  "text": reply.text, **({"parse_status": "unparseable"} if unparseable else {})})
                if unparseable:
                    clean.pop(sid, None)
                    continue
                ctx = trust.build_ctx(mrec, card_fingerprints=fps, guard_verdicts={sid: vd}, reference_prices=refs)
                action = {"kind": "offer", "negotiation_id": nid, "supplier_id": sid,
                          "lines": [{"gtin": l["gtin"], "qty": l["qty"], "unit_price_paise": l["unit_price_paise"]} for l in offer_lines],
                          "delivery_days": quote.delivery_days, "advance_pct": quote.advance_pct, "payout_vpa": quote.payout_vpa}
                rep = trust.gate(action, mrec, ctx, rules=OFFER_RULES, nid=nid, extra={"supplier_id": sid, "round": rnd})
                self.emit("gate.report", {"action": "offer", "supplier_id": sid, "round": rnd, "verdict": rep.verdict,
                                          "results": rep.to_dict()["results"], "reasons": rep.reasons})
                self.emit("offer", {"supplier_id": sid, "supplier_name": names.get(sid, sid), "round": rnd, "direction": direction,
                                    "lines": [{**l, "name": pnames.get(l["gtin"], l["gtin"])} for l in offer_lines],
                                    "delivery_days": quote.delivery_days, "advance_pct": quote.advance_pct,
                                    "guard_blocked": verdict.blocked, "gate_verdict": rep.verdict, "reasons": rep.reasons})
                if verdict.blocked or rep.verdict == "DENY":
                    blocked_total += 1
                    hostile[sid] = hostile.get(sid, 0) + 1
                    clean.pop(sid, None)
                    if verdict.blocked and hostile[sid] >= 2:
                        trust.quarantine(sid, "GUARD_BLOCKED_TWICE", nid)  # SM-2
                        active.pop(sid, None)
                    elif hostile[sid] >= 2 or rnd >= 2:
                        active.pop(sid, None)
                    continue
                prices = {l["gtin"]: l["unit_price_paise"] for l in offer_lines}
                if rnd == 1:
                    opening[sid] = prices
                if prices != prev_prices.get(sid):
                    changed = True
                prev_prices[sid] = prices
                clean[sid] = {**qd, "lines": offer_lines}
                if quote.final:
                    active.pop(sid, None)
            if rnd == 1:
                target = self._targets(clean, mlines)
            elif not changed:
                break  # converged

        preferred = store.shop(body["shop_id"]).get("preferred_supplier_id") or "sharma"
        cart = allocate(clean, body, opening, names, pnames, preferred=preferred)
        cart.update({"intent_mandate_id": mrec.mandate_id, "shop_id": body["shop_id"], "rounds": last_round,
                     "supplier_exchanges": exchanges, "blocked_messages": blocked_total})
        if not cart["allocations"]:
            store.update_negotiation(nid, status="failed", ended_at=store.iso())
            raise NegotiationError("no clean offer at or below ceiling")
        ctx = trust.build_ctx(mrec, card_fingerprints=fps,
                              guard_verdicts={sid: {"blocked": False} for sid in clean}, reference_prices=refs)
        action = {"kind": "cart", "negotiation_id": nid, "allocations": [
            {"supplier_id": a["supplier_id"], "lines": [{"gtin": l["gtin"], "qty": l["qty"], "unit_price_paise": l["unit_price_paise"]} for l in a["lines"]],
             "subtotal_paise": a["subtotal_paise"], "delivery_days": a["delivery_days"], "advance_pct": a["advance_pct"],
             "payout_vpa": a["payout_vpa"]} for a in cart["allocations"]]}
        rep = trust.gate(action, mrec, ctx, rules=CART_RULES, nid=nid, extra={"stage": "cart"})
        cart["gate_report"] = rep.to_dict()
        cart["status"] = "cart_ready" if rep.verdict != "DENY" else "denied"
        cid = store.save_cart_draft(nid, cart)
        trust.ledger_append(nid, "cart.assembled", "buyer", {
            "cart_draft_id": cid, "total_paise": cart["total_paise"], "savings_paise": cart["savings_paise"],
            "allocations": [{"supplier_id": a["supplier_id"], "subtotal_paise": a["subtotal_paise"], "lines": len(a["lines"])} for a in cart["allocations"]],
            "dropped_lines": cart["dropped_lines"], "why": [w["text"] for w in cart["why"]], "gate_verdict": rep.verdict})
        self.emit("gate.report", {"action": "cart", "verdict": rep.verdict, "results": rep.to_dict()["results"], "reasons": rep.reasons})
        store.update_negotiation(nid, status="cart_ready" if rep.verdict != "DENY" else "failed", cart_draft_id=cid,
                                 stats={"rounds": last_round, "exchanges": exchanges, "blocked": blocked_total})
        return cart

    # ---- concession schedule 11.4 (Plan B: last paid = best clean opening quote) ----
    @staticmethod
    def _targets(clean: dict[str, dict], mlines: dict[str, dict]) -> dict[str, int]:
        out = {}
        for g, ml in mlines.items():
            best = min((l["unit_price_paise"] for q in clean.values() for l in q["lines"] if l["gtin"] == g), default=None)
            if best is None:
                continue
            out[g] = int(min(int(ml["ceiling_paise"]), best * 0.95))
        return out

    @staticmethod
    def _counter_price(g: str, rnd: int, clean: dict, target: dict, mlines: dict) -> int:
        t = target[g]
        ceiling = int(mlines[g]["ceiling_paise"])
        if rnd == 2:
            return int(min(ceiling, t * 0.97))  # opening counter = target - 3%
        best = min((l["unit_price_paise"] for q in clean.values() for l in q["lines"] if l["gtin"] == g), default=t)
        return int(min(ceiling, (best + t) / 2))  # round 3: midpoint of best quote and target


def run(nid: str, emit: Emit | None = None) -> dict:
    return Negotiator(emit).run(nid)
