"""Festival calendar (6.4). Plan B: uplift factors are a stated ASSUMPTION, not shop history."""
from __future__ import annotations

from datetime import date, timedelta

ASSUMPTION_NOTE = ("Assumption (Plan B, no purchase history): Diwali week uplift +30% for sweets, snacks, "
                   "oil and ghee; +10% for staples.")
FESTIVALS = [
    {"festival_id": "diwali-2026", "name": "Diwali", "date": "2026-11-08",
     "window_start": "2026-11-01", "window_end": "2026-11-08", "region": "all-India"},
]
# category -> multiplicative factor during the festival window
UPLIFT = {
    "sweets": 1.30, "snacks": 1.30, "biscuits": 1.30, "noodles": 1.30, "oil": 1.30, "ghee": 1.30,
    "sugar": 1.10, "rice": 1.10, "atta": 1.10, "dal": 1.10, "salt": 1.10, "spices": 1.10, "tea": 1.10,
    "soaps": 1.00,
}


def calendar_docs() -> list[dict]:
    return [{**f, "uplift": UPLIFT, "uplift_basis": "assumption", "note": ASSUMPTION_NOTE} for f in FESTIVALS]


def uplift(category: str, on: date | str) -> float:
    """Demand multiplier for `category` on date `on` (1.0 outside any festival window)."""
    d = date.fromisoformat(on) if isinstance(on, str) else on
    for f in FESTIVALS:
        if date.fromisoformat(f["window_start"]) <= d <= date.fromisoformat(f["window_end"]):
            return UPLIFT.get(category, 1.0)
    return 1.0


def window_for(on: date | str, days_ahead: int = 21) -> dict | None:
    """The festival whose window starts within `days_ahead` of `on` (for 'restock for Diwali' drafts)."""
    d = date.fromisoformat(on) if isinstance(on, str) else on
    for f in FESTIVALS:
        if d <= date.fromisoformat(f["window_end"]) and date.fromisoformat(f["window_start"]) <= d + timedelta(days=days_ahead):
            return f
    return None
