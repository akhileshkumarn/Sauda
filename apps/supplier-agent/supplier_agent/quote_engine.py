"""Deterministic quote engine (SPEC 3.6 / 11.3). Pure functions over (profile, catalog row).

All prices are integer paise derived from the row's mrp_paise. Nothing here ever returns a
price below floor(). Rounds: the RFQ answer (QUOTE) is round 1; the first COUNTER is round 2,
the second round 3 (a COUNTER carrying round < 2 is treated as round 2).
"""

from __future__ import annotations

MAX_ROUND = 3


def _pct_off(mrp: int, bps: int) -> int:
    return mrp * (10000 - int(bps)) // 10000


def floor(profile: dict, row: dict) -> int:
    return _pct_off(row["mrp_paise"], profile["floor_discount_bps"])


def opening(profile: dict, row: dict) -> int:
    return max(floor(profile, row), _pct_off(row["mrp_paise"], profile["opening_discount_bps"]))


def moq(profile: dict, row: dict) -> int:
    return int(profile.get("moq_by_category", {}).get(row.get("category", ""), profile.get("moq_default", 1)))


def scheduled(profile: dict, row: dict, rnd: int) -> int:
    """Price the concession schedule allows at round rnd (round 1 = opening)."""
    steps = max(0, int(rnd) - 1)
    bps = profile["opening_discount_bps"] + steps * profile["concession_bps_per_round"]
    return max(floor(profile, row), _pct_off(row["mrp_paise"], bps))


def _volume(profile: dict, row: dict, price: int, qty: int) -> int:
    mult = profile.get("volume_discount_moq_multiple")
    if mult and qty >= mult * moq(profile, row):
        price -= row["mrp_paise"] * int(profile.get("volume_discount_bps", 0)) // 10000
    return max(floor(profile, row), price)


def quote_price(profile: dict, row: dict, qty: int) -> int:
    return _volume(profile, row, opening(profile, row), qty)


def concede(profile: dict, row: dict, rnd: int, target: int | None, qty: int = 0,
            match_price: int | None = None) -> int:
    """REVISED unit price at round rnd given the buyer's target (and Sharma's match hint).

    Monotone: never above the previous round's price, never below floor.
    """
    rnd = max(2, min(int(rnd), MAX_ROUND))
    fl = floor(profile, row)
    prev = scheduled(profile, row, rnd - 1)
    price = scheduled(profile, row, rnd)
    if target is not None:
        price = min(prev, max(price, int(target)))  # take the buyer's target if it beats our schedule
    tol = profile.get("match_tolerance_bps")
    if tol is not None and match_price is not None:
        mp = int(match_price)
        if mp * 10000 >= price * (10000 - int(tol)):  # best offer within 2% of ours -> match it
            price = min(price, mp)
    return max(fl, _volume(profile, row, price, qty))


def payout_vpa(profile: dict, rnd: int) -> str:
    if profile.get("round2_vpa") and rnd >= int(profile.get("vpa_switch_round", 2)):
        return profile["round2_vpa"]
    return profile["payout_vpa"]


def terms(profile: dict, rnd: int = 1) -> dict:
    return {
        "advance_pct": int(profile["advance_pct"]),
        "credit_days": int(profile.get("credit_days", 0)),
        "payment_terms": profile["payment_terms"],
        "delivery_days": int(profile["delivery_days"]),
        "payout_vpa": payout_vpa(profile, rnd),
        "validity_s": int(profile.get("validity_s", 3600)),
    }


def injection(profile: dict, rnd: int) -> str | None:
    text = profile.get("injection_text")
    if text and rnd >= int(profile.get("inject_from_round", 1)):
        return text
    return None
