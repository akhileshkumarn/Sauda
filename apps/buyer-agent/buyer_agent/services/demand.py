"""Demand planner (2.2), Plan B: owner's typed list -> GTIN lines (Gemini structured output over the
`products` catalog), festival uplift (stated assumption), reference ceilings (6.5)."""
from __future__ import annotations

import logging
import math
import re
from datetime import date, datetime, timedelta, timezone

from typing import Literal

from pydantic import BaseModel, Field

from .. import store
from ..deps import gemini_json

log = logging.getLogger("buyer_agent.demand")
IST = timezone(timedelta(hours=5, minutes=30))


class ReqLine(BaseModel):
    gtin: str
    qty: int | None = None  # what the owner said, in packs/units (dozen -> x12); null when no number was given
    owner_words: str = ""
    confidence: Literal["high", "low"] = "high"
    alternatives: list[str] = Field(default_factory=list)  # other plausible catalog gtins when confidence is low
    question: str | None = None  # short clarification question when confidence is low


class ParsedRequest(BaseModel):
    lines: list[ReqLine] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    stated_budget_rupees: int | None = None  # "keep under 8000" -> 8000; null if no budget was stated


def _catalog_text(prods: dict[str, dict]) -> str:
    return "\n".join(f"{g} | {p.get('name','')} | {p.get('brand','')} | {p.get('pack_size','')} | {p.get('category','')}"
                     for g, p in prods.items())


_WORD = re.compile(r"[a-z0-9]+")
DEFAULT_QTY = 10  # used only when the owner names an item without a number (qty_source="inferred")
NUM_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chheh": 6, "saat": 7,
    "aath": 8, "nau": 9, "das": 10, "gyarah": 11, "barah": 12, "baarah": 12, "pandrah": 15, "bees": 20,
    "pachees": 25, "pachchis": 25, "tees": 30, "chalis": 40, "chaalis": 40, "pachas": 50, "pachaas": 50, "sau": 100,
}
SYNONYMS = {"namak": "salt", "ata": "atta", "aata": "atta", "tel": "oil", "cheeni": "sugar", "chini": "sugar",
            "shakkar": "sugar", "chawal": "rice", "chai": "tea", "patti": "tea", "sabun": "soap", "soaps": "soap",
            "gud": "jaggery", "gur": "jaggery", "daal": "dal", "biscuit": "biscuits", "noodle": "noodles",
            "aashirvad": "aashirvaad", "ashirvad": "aashirvaad", "ashirwad": "aashirvaad"}
STOP = {"packet", "packets", "pack", "packs", "pkt", "pkts", "pcs", "pc", "piece", "pieces", "nos", "units", "unit",
        "of", "ka", "ki", "ke", "x", "please", "pls", "and", "aur", "bhi", "chahiye", "send", "need", "want", "restock",
        "order", "for", "the", "a", "an", "some", "more", "bags", "bag", "box", "boxes", "bottle", "bottles", "dozen"}
UNIT = r"(kg|kgs|kilo|kilos|g|gm|gms|gram|grams|ml|l|ltr|litre|litres|liter|liters)"
_UNIT_NORM = {"kg": "kg", "kgs": "kg", "kilo": "kg", "kilos": "kg", "g": "g", "gm": "g", "gms": "g", "gram": "g",
              "grams": "g", "ml": "ml", "l": "l", "ltr": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l"}
_BUDGET = [
    re.compile(r"(?:keep\s+(?:it\s+)?)?(?:under|below|within|upto|up\s+to|max(?:imum)?|budget(?:\s+(?:of|is))?|"
               r"not\s+more\s+than|less\s+than)\s*[:=]?\s*(?:₹|rs\.?|inr|rupees)?\s*([\d,]+(?:\.\d{1,2})?)\s*"
               r"(k|thousand|hazaar|hazar)?\b", re.I),
    re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d{1,2})?)\s*(k|thousand|hazaar|hazar)?\s*(?:budget|max|limit)\b", re.I),
    re.compile(r"([\d,]+(?:\.\d{1,2})?)\s*(k|thousand|hazaar|hazar)?\s*(?:₹|rs\.?|rupees|rupaye)?\s*"
               r"(?:ke\s+andar|se\s+kam|tak)\b", re.I),
]


def parse_budget_paise(text: str) -> tuple[int | None, str]:
    """Stated budget in integer paise ("keep under ₹8,000" -> 800000) and the text with that phrase removed."""
    from decimal import Decimal, InvalidOperation

    for rx in _BUDGET:
        m = rx.search(text or "")
        if not m:
            continue
        try:
            rupees = Decimal(m.group(1).replace(",", ""))
        except InvalidOperation:
            continue
        if (m.group(2) or "").lower() in ("k", "thousand", "hazaar", "hazar"):
            rupees *= 1000
        paise = int(rupees * 100)
        if paise > 0:
            return paise, (text[:m.start()] + " " + text[m.end():]).strip()
    return None, text


def _pack_key(s: str) -> str:
    m = re.search(r"(\d+(?:\.\d+)?)\s*" + UNIT + r"\b", (s or "").lower())
    return f"{float(m.group(1)):g}{_UNIT_NORM[m.group(2)]}" if m else ""


def _chunk_qty(chunk: str) -> tuple[int | None, str, list[str]]:
    """(owner qty or None, pack hint, item words) for one 'qty item' / 'item qty' chunk."""
    t = chunk.lower()
    pack = _pack_key(t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*" + UNIT + r"\b", " ", t)  # pack sizes are not quantities
    words = _WORD.findall(t)
    words = [str(NUM_WORDS[w]) if w in NUM_WORDS and not w.isdigit() else w for w in words]
    qty = None
    for k, w in enumerate(words):
        if w.isdigit():
            n = int(w)
            if k + 1 < len(words) and words[k + 1] == "dozen":
                n *= 12
            qty = n if qty is None else qty
    if qty is None and "dozen" in words:
        qty = 12
    items = [SYNONYMS.get(w, w) for w in words if not w.isdigit() and w not in STOP and len(w) >= 3]
    return qty, pack, items


def _score(items: list[str], pack: str, p: dict) -> float:
    import difflib

    name_toks = set(_WORD.findall(f"{p.get('name','')} {p.get('brand','')}".lower()))
    cat = (p.get("category") or "").lower()
    cat_toks = {cat, cat.rstrip("s")}
    score = 0.0
    for w in items:
        best = max((difflib.SequenceMatcher(None, w, t).ratio() for t in name_toks), default=0.0)
        best = best if best >= 0.85 else 0.0
        if w in cat_toks or w.rstrip("s") in cat_toks:
            best = max(best, 0.6) + (0.5 if best >= 0.85 else 0.0)  # category word, stronger if also in the name
        score += best
    if score and pack and _pack_key(p.get("pack_size", "")) == pack:
        score += 0.5
    return score


def _fallback_parse(text: str, prods: dict[str, dict]) -> ParsedRequest:
    """Deterministic parser, used when Gemini is unavailable: handles 'qty item' and 'item qty', dozens,
    Hindi/English number words, pack sizes ('1 kilo' is a pack, not a quantity), and a stated budget."""
    budget, body = parse_budget_paise(text)
    out = ParsedRequest(stated_budget_rupees=(budget // 100) if budget else None)
    body = body.split(":", 1)[1] if re.match(r"^[^,\n]{0,40}:", body) else body
    for chunk in re.split(r",|;|\n|\band\b|\baur\b|\bplus\b|&", body, flags=re.I):
        chunk = chunk.strip()
        if not chunk:
            continue
        qty, pack, items = _chunk_qty(chunk)
        if not items:  # e.g. "10 packets of 1": a quantity with no product named
            if re.search(r"\d", chunk):
                out.unmatched.append(chunk)
            continue
        ranked = sorted(((_score(items, pack, p), g) for g, p in prods.items()), key=lambda x: -x[0])
        ranked = [r for r in ranked if r[0] > 0]
        if not ranked:
            if qty is not None:  # a preamble like "prepare tomorrow's restock" is not an item
                out.unmatched.append(chunk)
            continue
        best_s, best = ranked[0]
        close = [g for sc, g in ranked[1:] if sc >= 0.85 * best_s]
        low = bool(close)
        alts = (close or [g for _, g in ranked[1:]])[:4] if low else []
        out.lines.append(ReqLine(gtin=best, qty=qty, owner_words=chunk, confidence="low" if low else "high",
                                 alternatives=alts,
                                 question=(f"Which one did you mean by \"{chunk}\"?" if low else None)))
    return out


def names_product(owner_words: str, product: dict) -> bool:
    """Do the owner's words actually name this product (a name/brand/category token, fuzzy, synonyms)? Guards
    against the model inventing a line for a fragment like "10 packets of 1". Non-Latin script (e.g. Devanagari
    from voice) cannot be checked token-wise here and is trusted to the model."""
    w = (owner_words or "").strip()
    if not w or re.search(r"[^\x00-\x7f₹•]", w):
        return True
    _, pack, items = _chunk_qty(w)
    return bool(items) and _score(items, pack, product) > 0


def _drop_unnamed(parsed: ParsedRequest, prods: dict[str, dict]) -> ParsedRequest:
    keep = []
    for l in parsed.lines:
        if names_product(l.owner_words, prods[l.gtin]):
            keep.append(l)
        else:
            parsed.unmatched.append(l.owner_words)
    parsed.lines = keep
    return parsed


def parse_request(text: str, prods: dict[str, dict]) -> ParsedRequest:
    from ..agent.prompts import PARSE_REQUEST_PROMPT

    try:
        parsed = gemini_json(PARSE_REQUEST_PROMPT.format(catalog=_catalog_text(prods), request=text[:2000]), ParsedRequest)
        parsed.lines = [l for l in parsed.lines if l.gtin in prods and (l.qty is None or l.qty > 0)]
        for l in parsed.lines:
            l.alternatives = [g for g in dict.fromkeys(l.alternatives) if g in prods and g != l.gtin][:4]
        _drop_unnamed(parsed, prods)
        if parsed.lines or parsed.unmatched:
            return parsed
    except Exception:
        log.exception("Gemini request parse failed; using keyword fallback")
    return _fallback_parse(text, prods)


def _uplift(category: str, today: date) -> tuple[float, dict | None]:
    try:
        from sauda_data import calendar as cal

        fest = cal.window_for(today)
        if fest:
            return cal.uplift(category, fest["date"]), fest
    except Exception:
        log.exception("calendar uplift failed")
    return 1.0, None


def _ceiling(product: dict) -> dict:
    try:
        from sauda_data import price_refs

        c = price_refs.ceiling_for(product, _refs())
        if c:
            return c
    except Exception:
        log.exception("ceiling_for failed")
    return {"ceiling_paise": int(product.get("mrp_paise") or 0), "ceiling_source": "mrp", "source": "mrp",
            "source_url": product.get("mrp_source_url", ""), "as_of": ""}


_refs_cache = None
_refs_ts = 0.0
REFS_TTL_S = 1800  # the price-refresh job updates Firestore daily; pick that up without a restart


def _refs():
    global _refs_cache, _refs_ts
    import time

    if _refs_cache is None or time.time() - _refs_ts > REFS_TTL_S:
        try:
            from sauda_data import price_refs

            from ..deps import db

            fresh = price_refs.load_price_refs(db())
            if fresh or _refs_cache is None:
                _refs_cache, _refs_ts = fresh, time.time()
        except Exception:
            log.exception("price_refs load failed; keeping previous values")
            if _refs_cache is None:
                _refs_cache = {}
    return _refs_cache


def _brief(p: dict) -> dict:
    return {"gtin": str(p.get("gtin")), "name": display_name(p), "brand": p.get("brand"), "pack_size": p.get("pack_size")}


def build_draft(shop_id: str, request_text: str, festival: str | None = None) -> dict:
    """Owner's words -> draft lines. qty is what the owner said (qty_source="owner"); only an item named without
    a number gets an inferred default. Festival uplift is a per-line suggestion, never applied silently."""
    prods = store.products()
    if not prods:
        raise RuntimeError("products collection is empty (run the seed)")
    parsed = parse_request(request_text, prods)
    stated_budget, _ = parse_budget_paise(request_text)
    if stated_budget is None and parsed.stated_budget_rupees and parsed.stated_budget_rupees > 0:
        stated_budget = int(parsed.stated_budget_rupees) * 100
    today = datetime.now(IST).date()
    merged: dict[str, ReqLine] = {}
    for rl in parsed.lines:  # one line per gtin (the mandate allows each gtin once)
        if rl.gtin in merged:
            m = merged[rl.gtin]
            m.qty = (m.qty or 0) + (rl.qty or 0) or None
            m.owner_words = f"{m.owner_words}; {rl.owner_words}".strip("; ")
        else:
            merged[rl.gtin] = rl.model_copy()
    lines, clarifications = [], []
    for rl in merged.values():
        line, clar = draft_line(rl, prods, today)
        lines.append(line)
        if clar:
            clarifications.append(clar)
    return finalize_draft(shop_id, lines, clarifications, parsed.unmatched, stated_budget, festival, today)


def draft_line(rl: ReqLine, prods: dict[str, dict], today: date | None = None, qty_source: str | None = None) -> tuple[dict, dict | None]:
    """One draft line (ceiling from the catalogue + reference prices, uplift only as a suggestion) and its
    clarification when the match is low-confidence. Shared by the /chat draft and the restock-session turns."""
    today = today or datetime.now(IST).date()
    p = {**prods[rl.gtin], "gtin": rl.gtin}
    factor, fest = _uplift(p.get("category", ""), today)
    owner_qty = int(rl.qty) if rl.qty and rl.qty > 0 else None
    qty = owner_qty or DEFAULT_QTY
    suggested = int(math.ceil(qty * factor)) if factor > 1 else None
    if suggested is not None and suggested <= qty:
        suggested = None
    pct = round((factor - 1) * 100)
    suggestion_reason = (f"+{pct}% {fest['name']} uplift for {p.get('category')} is a stated assumption, not your "
                         f"history: {qty} -> {suggested}. Accept it only if you expect the extra demand."
                         if suggested and fest else None)
    c = _ceiling(p)
    low = rl.confidence == "low"
    alts = [_brief({**prods[g], "gtin": g}) for g in rl.alternatives if g in prods] if low else []
    if low and not alts:  # model said "unsure" without options: offer the same category
        alts = [_brief({**q, "gtin": g}) for g, q in prods.items()
                if g != rl.gtin and q.get("category") == p.get("category")][:4]
    reason = (f"You asked for {owner_qty}." if owner_qty else
              f"No quantity given; default {qty} (edit it).")
    line = {
        "gtin": rl.gtin, "name": display_name(p), "brand": p.get("brand"), "pack_size": p.get("pack_size"),
        "category": p.get("category"), "qty": qty, "qty_source": qty_source or ("owner" if owner_qty else "inferred"),
        "requested_qty": owner_qty, "suggested_qty": suggested, "suggestion_reason": suggestion_reason,
        "forecast_qty": qty, "uplift_factor": factor, "last_paid_paise": None, "mrp_paise": p.get("mrp_paise"),
        "ceiling_paise": int(c["ceiling_paise"]), "ceiling_source": c.get("ceiling_source"),
        "ceiling_source_detail": c.get("source"), "ceiling_source_url": c.get("source_url"), "ceiling_as_of": c.get("as_of"),
        "confidence": "low" if low else "high", "owner_words": rl.owner_words, "alternatives": alts,
        "reason": reason, "festival": (fest or {}).get("name"), "festival_window_start": (fest or {}).get("window_start"),
    }
    clar = None
    if low:
        clar = {"owner_words": rl.owner_words, "gtin": rl.gtin,
                "question": rl.question or f"Which product did you mean by \"{rl.owner_words}\"?",
                "options": [_brief(p)] + alts}
    return line, clar


def finalize_draft(shop_id: str, lines: list[dict], clarifications: list[dict], unmatched: list[str],
                   stated_budget: int | None, festival: str | None = None, today: date | None = None) -> dict:
    """Budget estimate (sum of qty x ceiling, rounded up to the rupee), suggested mandate, notes. Integer paise."""
    today = today or datetime.now(IST).date()
    estimate = sum(int(l["qty"]) * int(l["ceiling_paise"]) for l in lines)
    estimate = int(math.ceil(estimate / 100.0) * 100)
    fest_used = None
    for l in lines:
        if l.get("festival") and l.get("festival_window_start"):
            fest_used = {"name": l["festival"], "window_start": l["festival_window_start"]}
            break
    budget = stated_budget if stated_budget else estimate
    deliver_by = (fest_used and (date.fromisoformat(fest_used["window_start"]) - timedelta(days=1))) or (today + timedelta(days=5))
    if deliver_by < today + timedelta(days=2):
        deliver_by = today + timedelta(days=5)
    expires = datetime.now(IST) + timedelta(hours=24)
    notes = []
    if stated_budget and stated_budget < estimate:
        notes.append(f"Your budget ₹{stated_budget / 100:,.0f} is below the ceiling estimate ₹{estimate / 100:,.0f}; "
                     "suppliers usually quote under ceiling, but some lines may be dropped.")
    return {
        "shop_id": shop_id,
        "festival": (fest_used or {}).get("name") or festival,
        "lines": lines,
        "unmatched": unmatched,
        "clarifications": clarifications,
        "stated_budget_paise": stated_budget,
        "budget_estimate_paise": estimate,
        "suggested_budget_paise": budget,
        "budget_notes": notes,
        "suggested_mandate": {
            "kind": "intent", "shop_id": shop_id, "budget_paise": budget,
            "allowed_supplier_ids": ["metro", "sharma", "quickstock"],
            "lines": [{"gtin": l["gtin"], "qty": l["qty"], "ceiling_paise": l["ceiling_paise"], "ceiling_source": l["ceiling_source"]} for l in lines],
            "max_advance_pct": 20, "deliver_by": deliver_by.isoformat(), "autonomy_tier": 2,
            "expires_at": expires.replace(microsecond=0).isoformat(),
        },
        "assumption": ("Quantities are what you asked for. Festival uplift (+30% sweets/snacks/oil/ghee, +10% staples) "
                       "is only a suggestion per line (stated assumption, no purchase history)."),
    }


# ---------------------------------------------------------------- mandate validation (POST /mandates)
MAX_QTY = 5000
MAX_EXPIRY = timedelta(days=7)


class MandateInvalid(ValueError):
    pass


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def reference_ceiling(product: dict) -> int:
    return int(_ceiling(product)["ceiling_paise"])


def validate_intent(b: dict, supplier_exists=None) -> None:
    """Server-side checks on an Intent Mandate body before it is signed. Raises MandateInvalid(readable message)."""
    prods = store.products()
    lines = b.get("lines")
    if not isinstance(lines, list) or not lines:
        raise MandateInvalid("lines: at least one line is required")
    if len(lines) > 60:
        raise MandateInvalid("lines: at most 60 lines")
    seen = set()
    for k, l in enumerate(lines, 1):
        if not isinstance(l, dict):
            raise MandateInvalid(f"line {k}: must be an object")
        g = str(l.get("gtin") or "")
        if g not in prods:
            raise MandateInvalid(f"line {k}: gtin {g or '(missing)'} is not in the catalogue")
        if g in seen:
            raise MandateInvalid(f"line {k}: {prods[g].get('name', g)} appears twice")
        seen.add(g)
        q = l.get("qty")
        if not _is_int(q) or not 1 <= q <= MAX_QTY:
            raise MandateInvalid(f"line {k} ({prods[g].get('name', g)}): qty must be a whole number 1 to {MAX_QTY}")
        cp = l.get("ceiling_paise")
        if not _is_int(cp) or cp <= 0:
            raise MandateInvalid(f"line {k} ({prods[g].get('name', g)}): ceiling_paise must be a whole number of paise above 0")
        ref = reference_ceiling({**prods[g], "gtin": g})
        if ref <= 0 or cp > ref:
            raise MandateInvalid(f"line {k} ({prods[g].get('name', g)}): ceiling ₹{cp / 100:,.2f} is above the reference "
                                 f"ceiling ₹{ref / 100:,.2f} (MRP or mandi x1.10)")
    bp = b.get("budget_paise")
    if not _is_int(bp) or bp <= 0:
        raise MandateInvalid("budget_paise must be a whole number of paise above 0")
    adv = b.get("max_advance_pct")
    if isinstance(adv, bool) or not isinstance(adv, (int, float)) or not (0 <= adv <= 100):
        raise MandateInvalid("max_advance_pct must be a number from 0 to 100")
    tier = b.get("autonomy_tier", 2)
    if not _is_int(tier) or tier not in (1, 2):
        raise MandateInvalid("autonomy_tier must be 1 or 2 (every order needs your approval in this build)")
    sids = b.get("allowed_supplier_ids")
    if not isinstance(sids, list) or not sids or not all(isinstance(x, str) for x in sids) or len(set(sids)) != len(sids):
        raise MandateInvalid("allowed_supplier_ids must be a non-empty list of distinct supplier ids")
    if supplier_exists is not None:
        unknown = [x for x in sids if not supplier_exists(x)]
        if unknown:
            raise MandateInvalid(f"allowed_supplier_ids: not in the supplier registry: {', '.join(unknown)}")
    now = datetime.now(IST)
    try:
        deliver_by = date.fromisoformat(str(b.get("deliver_by"))[:10])
    except ValueError:
        raise MandateInvalid("deliver_by must be a date YYYY-MM-DD")
    if deliver_by < now.date():
        raise MandateInvalid("deliver_by is in the past")
    try:
        exp = datetime.fromisoformat(str(b.get("expires_at")).replace("Z", "+00:00"))
    except ValueError:
        raise MandateInvalid("expires_at must be an ISO 8601 date-time")
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=IST)
    if exp <= now:
        raise MandateInvalid("expires_at must be in the future")
    if exp > now + MAX_EXPIRY + timedelta(minutes=5):
        raise MandateInvalid("expires_at must be at most 7 days from now")

def display_name(p: dict) -> str:
    """Catalogue name with the brand in front when the name lacks it ("Salt LITE" -> "Tata Salt LITE")."""
    name = (p.get("name") or "").strip()
    brand = (p.get("brand") or "").strip()
    if brand and brand.lower() not in name.lower():
        return f"{brand.title() if (brand.isupper() or brand.islower()) else brand} {name}".strip()
    return name
