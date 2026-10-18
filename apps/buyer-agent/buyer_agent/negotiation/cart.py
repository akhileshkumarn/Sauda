"""Cart optimizer (2.5): per-line lowest landed cost under MOQ and availability (11.4 step 4)."""
from __future__ import annotations

SMALL_SUPPLIER_LINES = 3
SMALL_SUPPLIER_WIN_PCT = 5.0


def _price_map(quote: dict) -> dict[str, dict]:
    return {str(l["gtin"]): l for l in quote.get("lines", [])}


def allocate(offers: dict[str, dict], mandate_body: dict, opening: dict[str, dict[str, int]] | None = None,
             names: dict[str, str] | None = None, product_names: dict[str, str] | None = None,
             preferred: str | None = None) -> dict:
    """offers: supplier_id -> latest gate-ALLOWed quote. opening: supplier_id -> {gtin: round-1 price}.
    Returns a CartDraft dict (allocations, total_paise, savings_paise, dropped_lines, why)."""
    opening = opening or {}
    names = names or {}
    product_names = product_names or {}
    pm = {sid: _price_map(q) for sid, q in offers.items()}
    mlines = mandate_body.get("lines", [])

    def candidates(gtin: str, qty: int) -> list[tuple[int, str]]:
        out = []
        for sid, lines in pm.items():
            l = lines.get(gtin)
            if not l:
                continue
            if int(l.get("moq") or 1) > qty:
                continue
            avail = l.get("available_qty")
            if avail is not None and int(avail) < qty:
                continue
            out.append((int(l["unit_price_paise"]), sid))
        # equal price: the shop's usual distributor wins the tie (respect existing relationships)
        return sorted(out, key=lambda x: (x[0], 0 if x[1] == preferred else 1, x[1]))

    choice: dict[str, str] = {}
    cands: dict[str, list[tuple[int, str]]] = {}
    dropped = []
    for ml in mlines:
        gtin, qty = str(ml["gtin"]), int(ml["qty"])
        c = [x for x in candidates(gtin, qty) if x[0] <= int(ml["ceiling_paise"])]
        cands[gtin] = c
        if not c:
            dropped.append({"gtin": gtin, "name": product_names.get(gtin, gtin), "qty": qty,
                            "reason": "no offer at or below ceiling with enough stock/MOQ"})
            continue
        choice[gtin] = c[0][1]

    # 11.4.4: a supplier with fewer than 3 lines is dropped unless it wins by more than 5%
    changed = True
    while changed:
        changed = False
        counts: dict[str, int] = {}
        for sid in choice.values():
            counts[sid] = counts.get(sid, 0) + 1
        for sid, n in sorted(counts.items(), key=lambda x: x[1]):
            if n >= SMALL_SUPPLIER_LINES or len(counts) == 1:
                continue
            movable = {}
            for gtin, s in choice.items():
                if s != sid:
                    continue
                best = cands[gtin][0][0]
                alt = next((x for x in cands[gtin] if x[1] != sid and counts.get(x[1], 0) >= 1), None)
                if alt is None or (alt[0] - best) * 100.0 / best > SMALL_SUPPLIER_WIN_PCT:
                    movable = None
                    break
                movable[gtin] = alt[1]
            if movable:
                choice.update(movable)
                changed = True
                break

    allocations: dict[str, dict] = {}
    total = savings = opening_cost = 0
    why = []
    mline_by = {str(m["gtin"]): m for m in mlines}
    for gtin, sid in choice.items():
        ml = mline_by[gtin]
        qty = int(ml["qty"])
        l = pm[sid][gtin]
        price = int(l["unit_price_paise"])
        open_p = int(opening.get(sid, {}).get(gtin, price))
        a = allocations.setdefault(sid, {
            "supplier_id": sid, "supplier_name": names.get(sid, sid), "lines": [], "subtotal_paise": 0,
            "delivery_days": offers[sid].get("delivery_days"), "advance_pct": offers[sid].get("advance_pct", 0),
            "payout_vpa": offers[sid].get("payout_vpa"),
        })
        a["lines"].append({"gtin": gtin, "name": product_names.get(gtin, l.get("name", gtin)), "qty": qty,
                           "unit_price_paise": price, "opening_price_paise": open_p,
                           "ceiling_paise": int(ml["ceiling_paise"]), "ceiling_source": ml.get("ceiling_source")})
        a["subtotal_paise"] += price * qty
        total += price * qty
        opening_cost += open_p * qty
        savings += (open_p - price) * qty
        others = [f"{names.get(s, s)} ₹{p / 100:.2f}" for p, s in cands[gtin] if s != sid]
        why.append({
            "gtin": gtin, "supplier_id": sid,
            "text": (f"{product_names.get(gtin, gtin)}: {names.get(sid, sid)} at ₹{price / 100:.2f}/unit "
                     f"(opened at ₹{open_p / 100:.2f}, ceiling ₹{int(ml['ceiling_paise']) / 100:.2f})"
                     + (f"; other offers: {', '.join(others)}" if others else "; only clean offer")),
        })
    lines_n = len(mlines)
    compliant = sum(1 for a in allocations.values() for l in a["lines"] if l["unit_price_paise"] <= l["ceiling_paise"])
    return {
        "allocations": list(allocations.values()),
        "total_paise": total,
        "savings_paise": savings,
        "opening_cost_paise": opening_cost,
        "savings_pct": round(savings * 100.0 / opening_cost, 2) if opening_cost else 0.0,
        "ceiling_compliance": round(compliant / lines_n, 4) if lines_n else 0.0,
        "dropped_lines": dropped,
        "why": why,
    }
