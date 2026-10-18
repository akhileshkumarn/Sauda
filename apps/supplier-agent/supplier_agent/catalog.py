"""UCP-style catalog built from the product master (data/products.csv).

The real file from workstream D wins; data/products.sample.csv is a dev fixture used only
when the real file is absent. PRODUCTS_CSV overrides both.
"""

from __future__ import annotations

import csv
import hashlib
import os
from functools import lru_cache
from pathlib import Path

from . import quote_engine as qe
from .profile import REPO_ROOT


def products_path() -> Path:
    env = os.environ.get("PRODUCTS_CSV")
    if env:
        return Path(env)
    real = REPO_ROOT / "data" / "products.csv"
    return real if real.exists() else REPO_ROOT / "data" / "products.sample.csv"


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gtin = (r.get("gtin") or "").strip()
            try:
                mrp = int(float(r.get("mrp_paise") or 0))
            except ValueError:
                continue
            if not gtin or mrp <= 0:
                continue
            rows[gtin] = {
                "gtin": gtin,
                "name": (r.get("name") or "").strip(),
                "brand": (r.get("brand") or "").strip(),
                "pack_size": (r.get("pack_size") or "").strip(),
                "category": (r.get("category") or "").strip().lower(),
                "mrp_paise": mrp,
                "mrp_source": (r.get("mrp_source") or "").strip(),
                "mrp_source_url": (r.get("mrp_source_url") or "").strip(),
                "image_url": (r.get("image_url") or "").strip(),
            }
    return rows


def products() -> dict[str, dict]:
    p = products_path()
    return _load(str(p), p.stat().st_mtime)


def stock_for(profile: dict, gtin: str) -> int:
    """Deterministic stock per (supplier, gtin)."""
    lo, hi = int(profile.get("stock_min", 100)), int(profile.get("stock_max", 500))
    h = int(hashlib.sha256(f"{profile['id']}:{gtin}".encode()).hexdigest()[:8], 16)
    return lo + h % max(1, hi - lo + 1)


def build_catalog(profile: dict) -> dict:
    items = []
    for gtin, row in products().items():
        items.append({
            "gtin": gtin,
            "name": row["name"],
            "brand": row["brand"],
            "pack": row["pack_size"],
            "category": row["category"],
            "mrp_paise": row["mrp_paise"],
            "mrp_source": row["mrp_source"],
            "offer_price_paise": qe.opening(profile, row),
            "moq": qe.moq(profile, row),
            "stock": stock_for(profile, gtin),
            "delivery_days": profile["delivery_days"],
            "payment_terms": profile["payment_terms"],
            "image_url": row["image_url"],
        })
    return {
        "supplier_id": profile["id"],
        "supplier_name": profile["name"],
        "currency": "INR",
        "price_unit": "paise",
        "source": products_path().name,
        "strategy": profile.get("strategy"),
        "terms": qe.terms(profile, 1),
        "items": items,
    }
