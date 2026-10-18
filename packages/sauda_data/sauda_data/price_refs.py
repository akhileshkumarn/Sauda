"""Reference prices (6.2) from data.gov.in mandi data and the reference ceiling rule (6.5).

Resource 9ef84268-d588-465a-a308-a864a43d0070: Current Daily Price of Various Commodities from
Various Markets (Mandi). Prices are Rs per quintal; Rs/quintal == paise/kg (x100 / 100).
"""
from __future__ import annotations

import os
import re
import statistics
import time
from datetime import datetime

import httpx

import logging

log = logging.getLogger("sauda_data.price_refs")
# httpx logs full request URLs at INFO, and data.gov.in takes the API key as a query parameter
logging.getLogger("httpx").setLevel(logging.WARNING)

from .products import USER_AGENT

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
API_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
SOURCE_URL = "https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi"
RETAILER_MARGIN = 0.10

# our commodity key -> exact mandi commodity name
COMMODITIES: dict[str, str] = {
    "rice": "Rice",
    "wheat": "Wheat",
    "atta": "Wheat Atta",
    "tur_dal": "Red gram split/Arhar dal/Tur dal",
    "moong_dal": "Green Gram Dal(Moong Dal)",
    "chana_dal": "Bengal Gram Dal(Chana Dal)",
    "urad_dal": "Black Gram Dal(Urd Dal)",
    "masoor_dal": "Masur Dal",
    "sugar": "Sugar",
    "jaggery": "Gur(Jaggery)",
    "mustard_oil": "Mustard Oil",
    "coconut_oil": "Coconut Oil",
    "ghee": "Ghee",
    "onion": "Onion",
    "potato": "Potato",
    "dry_chillies": "Dry Chillies",
    "coriander_seed": "Corriander seed",
}
# product category -> commodity key used for a loose-staple ceiling
CATEGORY_COMMODITY = {
    "rice": "rice", "atta": "atta", "dal": "tur_dal", "sugar": "sugar", "oil": "mustard_oil",
    "ghee": "ghee", "spices": "dry_chillies",
}
DISTRICT_VARIANTS = {
    "bengaluru urban": ["Bengaluru", "Bangalore", "Bengaluru Urban", "Bangalore Urban"],
    "bengaluru": ["Bengaluru", "Bangalore", "Bengaluru Urban", "Bangalore Urban"],
    "bangalore": ["Bengaluru", "Bangalore", "Bengaluru Urban", "Bangalore Urban"],
}


def _api_key() -> str:
    key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not key:
        raise RuntimeError("DATA_GOV_IN_API_KEY not set")
    return key


def _fetch_all(filters: dict[str, str], page: int = 1000, max_pages: int = 30) -> list[dict]:
    """Paginate with offset until a short page (works with capped sample keys too)."""
    out: list[dict] = []
    offset = 0
    for _ in range(max_pages):
        params = {"api-key": _api_key(), "format": "json", "limit": page, "offset": offset}
        params.update({f"filters[{k}]": v for k, v in filters.items()})
        recs = None
        for attempt in range(4):
            try:
                r = httpx.get(API_URL, params=params, timeout=60, headers={"User-Agent": USER_AGENT})
                r.raise_for_status()
                recs = r.json().get("records", [])
                break
            except httpx.HTTPStatusError as e:
                # data.gov.in answers 403 to cloud data-centre IPs; log the status only, never the URL (it carries the key)
                log.warning("data.gov.in HTTP %s (attempt %d)", e.response.status_code, attempt + 1)
                time.sleep(1.5 * (attempt + 1))
            except (httpx.HTTPError, ValueError) as e:
                log.warning("data.gov.in request failed: %s (attempt %d)", type(e).__name__, attempt + 1)
                time.sleep(1.5 * (attempt + 1))
        if not recs:
            break
        out.extend(recs)
        offset += len(recs)
        if len(recs) < page and len(recs) != 10:  # a 10-row page may be a sample-key cap: keep going
            break
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def _iso(d: str) -> str:
    try:
        return datetime.strptime(d, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return d or ""


def _aggregate(key: str, recs: list[dict], scope: str, state: str, district: str) -> dict:
    modal = [float(r["modal_price"]) for r in recs if float(r.get("modal_price") or 0) > 0]
    mins = [float(r["min_price"]) for r in recs if float(r.get("min_price") or 0) > 0]
    maxs = [float(r["max_price"]) for r in recs if float(r.get("max_price") or 0) > 0]
    as_of = max((_iso(r.get("arrival_date")) for r in recs), default="")
    label = {"district": f"district {district}", "state": f"state {state} (district had no rows)",
             "india": "all-India (district and state had no rows)"}[scope]
    return {
        "commodity": key,
        "mandi_commodity": COMMODITIES[key],
        "district": district if scope == "district" else "",
        "state": state if scope in ("district", "state") else "",
        "scope": scope,
        "modal_price_paise_per_kg": int(round(statistics.median(modal))),
        "min": int(round(statistics.median(mins))) if mins else None,
        "max": int(round(statistics.median(maxs))) if maxs else None,
        "n_records": len(recs),
        "markets": sorted({r.get("market", "") for r in recs})[:20],
        "source": f"data.gov.in mandi modal price, median across markets, {label}",
        "source_url": SOURCE_URL,
        "as_of": as_of,
    }


def fetch_mandi(state: str = "Karnataka", district: str = "Bengaluru Urban",
                commodities: list[str] | None = None) -> list[dict]:
    """Return one `price_refs` doc per commodity key: district rows, else state, else all-India.

    Money is paise per kg. Each doc records its scope in `scope` and `source`.
    """
    keys = commodities or list(COMMODITIES)
    variants = {v.lower() for v in DISTRICT_VARIANTS.get(district.lower(), [district])}
    state_recs = _fetch_all({"state.keyword": state})
    out: list[dict] = []
    for key in keys:
        name = COMMODITIES[key].lower()
        rows = [r for r in state_recs if r.get("commodity", "").lower() == name]
        drows = [r for r in rows if r.get("district", "").lower() in variants]
        if drows:
            out.append(_aggregate(key, drows, "district", state, district))
        elif rows:
            out.append(_aggregate(key, rows, "state", state, district))
        else:
            india = [r for r in _fetch_all({"commodity.keyword": COMMODITIES[key]})
                     if r.get("commodity", "").lower() == name]
            if india:
                out.append(_aggregate(key, india, "india", state, district))
    return out


def doc_id(ref: dict) -> str:
    return "__".join([ref["commodity"], _slug(ref.get("state")) or "india",
                      _slug(ref.get("district")) or "all"])


SCOPE_RANK = {"district": 0, "state": 1, "india": 2}
MAX_LOCAL_AGE_DAYS = 7  # a local price older than this loses to a fresher wider-scope one


def _age_days(as_of: str | None, today=None) -> int:
    from datetime import date

    try:
        return ((today or date.today()) - date.fromisoformat((as_of or "")[:10])).days
    except ValueError:
        return 10**6


def pick_ref(candidates: list[dict], today=None) -> dict | None:
    """Most local scope wins while it is fresh (<= MAX_LOCAL_AGE_DAYS); otherwise the freshest record wins.
    Mandis do not report every day (Sundays, holidays), so yesterday's Bengaluru price beats today's all-India one."""
    if not candidates:
        return None
    fresh = [c for c in candidates if _age_days(c.get("as_of"), today) <= MAX_LOCAL_AGE_DAYS]
    if fresh:
        return min(fresh, key=lambda c: (SCOPE_RANK.get(c.get("scope"), 9), _age_days(c.get("as_of"), today)))
    return max(candidates, key=lambda c: (c.get("as_of") or "", -SCOPE_RANK.get(c.get("scope"), 9)))


def load_price_refs(db=None) -> dict[str, dict]:
    """Read `price_refs` from Firestore keyed by commodity (see pick_ref for which scope wins)."""
    if db is None:
        from google.cloud import firestore
        db = firestore.Client()
    by_key: dict[str, list[dict]] = {}
    for d in db.collection("price_refs").stream():
        ref = d.to_dict()
        by_key.setdefault(ref["commodity"], []).append(ref)
    return {k: r for k, v in by_key.items() if (r := pick_ref(v)) is not None}


def is_loose(product: dict) -> bool:
    return bool(product.get("loose")) or not (product.get("brand") or "").strip()


def ceiling_for(product: dict, refs: dict[str, dict] | None = None,
                last_paid_paise: int | None = None) -> dict | None:
    """Reference ceiling rule (6.5).

    Loose staple: modal mandi paise/kg in the shop's district x 1.10, scaled to pack size.
    Branded pack: min(MRP, last paid x 1.10); under Plan B there is no last paid, so MRP.
    Returns {ceiling_paise, ceiling_source, source, source_url, as_of} or None.
    """
    from .products import pack_grams

    if is_loose(product):
        key = product.get("commodity") or CATEGORY_COMMODITY.get(product.get("category", ""))
        ref = (refs or {}).get(key) if key else None
        grams = pack_grams(product.get("pack_size", "1 kg")) or 1000
        if ref:
            ceiling = int(round(ref["modal_price_paise_per_kg"] * (1 + RETAILER_MARGIN) * grams / 1000))
            return {"ceiling_paise": ceiling, "ceiling_source": "mandi_modal_x1.10",
                    "source": ref["source"], "source_url": ref["source_url"], "as_of": ref["as_of"]}
    mrp = product.get("mrp_paise")
    if not mrp:
        return None
    if last_paid_paise:
        lp = int(round(last_paid_paise * 1.10))
        if lp < mrp:
            return {"ceiling_paise": lp, "ceiling_source": "last_paid_x1.10", "source": "purchase history",
                    "source_url": "", "as_of": ""}
    return {"ceiling_paise": int(mrp), "ceiling_source": "mrp",
            "source": product.get("mrp_source", "mrp"), "source_url": product.get("mrp_source_url", ""),
            "as_of": ""}
