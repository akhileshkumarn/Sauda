"""Impact metrics (section 4), Plan B: savings baseline = opening quotes. Computed from the cart drafts
of ordered/confirmed negotiations and from ledger events (blocked attacks)."""
from __future__ import annotations

from .. import store

COUNTED = ("cart_ready", "awaiting_confirmation", "confirmed", "ordered")


def compute(shop_id: str) -> dict:
    shop = store.shop(shop_id)
    minutes = float(shop.get("minutes_per_supplier_call") or 6)
    saved = opening = 0
    lines = compliant = 0
    exchanges = blocked = 0
    orders_n = 0
    last = None
    negs = sorted(store.negotiations_for_shop(shop_id), key=lambda n: n.get("started_at") or "")
    realised = realised_opening = 0
    for n in negs:
        if n.get("status") not in COUNTED or not n.get("cart_draft_id"):
            continue
        cart = store.cart_draft(n["cart_draft_id"]) or {}
        saved += int(cart.get("savings_paise", 0))
        opening += int(cart.get("opening_cost_paise", 0))
        if n.get("status") == "ordered":
            # realised savings: only orders that were placed and not cancelled, per supplier allocation
            live = {o["supplier_id"] for o in store.orders_for(n["negotiation_id"]) if o.get("status") != "cancelled"}
            for a in cart.get("allocations", []):
                if a["supplier_id"] in live:
                    for l in a["lines"]:
                        q, p_ = int(l["qty"]), int(l["unit_price_paise"])
                        op = int(l.get("opening_price_paise") or p_)
                        realised += (op - p_) * q
                        realised_opening += op * q
        for a in cart.get("allocations", []):
            for l in a["lines"]:
                lines += 1
                compliant += 1 if l["unit_price_paise"] <= l["ceiling_paise"] else 0
        exchanges += int(cart.get("supplier_exchanges", 0))
        if n.get("status") == "ordered":
            orders_n += 1
        last = n["negotiation_id"]
    supplier_blocked = attack_box_blocked = 0
    for n in negs:
        for e in store.ledger_events(n["negotiation_id"]):
            p = e.get("payload") or {}
            if e.get("type") == "guard.verdict" and p.get("blocked"):
                supplier_blocked += 1
    # attack box events live on their own chain
    for e in store.ledger_events(f"attack-{shop_id}"):
        p = e.get("payload") or {}
        if e.get("type") == "attack.tested" and p.get("blocked"):
            attack_box_blocked += 1
    blocked = supplier_blocked + attack_box_blocked
    return {
        "shop_id": shop_id,
        "rupees_saved": saved,  # paise (money in paise everywhere)
        "rupees_saved_inr": round(saved / 100, 2),
        "savings_pct": round(saved * 100.0 / opening, 2) if opening else 0.0,
        "ceiling_compliance": round(compliant / lines, 4) if lines else 0.0,
        "time_saved_min": round(exchanges * minutes, 1),
        "attacks_blocked": blocked,
        "orders": orders_n,
        "last_negotiation_id": last,
        "baseline": "opening quotes (Plan B: no purchase history)",
        "baseline_label": "Savings vs the suppliers' opening quotes (partner supplier agents), not vs your past bills",
        "opening_cost_paise": opening,
        "realised_opening_paise": realised_opening,
        "realised_savings_paise": realised,
        "realised_savings_pct": round(realised * 100.0 / realised_opening, 2) if realised_opening else 0.0,
        "realised_basis": "placed orders that were not cancelled",
        "supplier_messages_blocked": supplier_blocked,
        "attack_box_blocked": attack_box_blocked,
        "time_saved_assumption_min_per_call": minutes,
    }
