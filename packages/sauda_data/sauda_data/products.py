"""Product master (6.1): Open Food Facts v2 lookups and the data/products.csv loader.

Product data: Open Food Facts (ODbL).
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import httpx

OFF_BASE = "https://world.openfoodfacts.org"
USER_AGENT = "Sauda/0.1 (+https://saudaai.web.app)"
CSV_COLUMNS = ["gtin", "name", "brand", "pack_size", "category", "mrp_paise",
               "mrp_source", "mrp_source_url", "image_url"]
DEFAULT_CSV = Path(__file__).resolve().parents[3] / "data" / "products.csv"

_UNIT = {"g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "gr": "g", "grm": "g",
         "kg": "kg", "kgs": "kg", "kilo": "kg", "kilogram": "kg",
         "ml": "ml", "l": "L", "lt": "L", "ltr": "L", "litre": "L", "liter": "L", "litres": "L"}
_QTY_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kgs?|kilo(?:gram)?|gms?|grams?|grm|gr|g|ml|ltr|lt|litres?|liter|l)\b", re.IGNORECASE)


def normalize_pack_size(quantity: str) -> str:
    """'45gm' -> '45 g', '1 Ltr' -> '1 L'. Returns '' when no recognisable size."""
    m = _QTY_RE.search(quantity or "")
    if not m:
        return ""
    num = m.group(1).replace(",", ".")
    num = num.rstrip("0").rstrip(".") if "." in num else num
    if float(num) <= 0:
        return ""
    return f"{num} {_UNIT[m.group(2).lower()]}"


def pack_grams(pack_size: str) -> float | None:
    """Mass (or ml treated as g, density ~1) of a normalised pack size; None if unparseable."""
    m = re.match(r"([\d.]+)\s*(g|kg|ml|L)$", (pack_size or "").strip())
    if not m:
        return None
    v = float(m.group(1))
    return v * {"g": 1, "kg": 1000, "ml": 1, "L": 1000}[m.group(2)]


def load_csv(path: str | Path = DEFAULT_CSV) -> list[dict]:
    """Load data/products.csv as a list of dicts (mrp_paise as int)."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["mrp_paise"] = int(r["mrp_paise"]) if r.get("mrp_paise") else None
    return rows


def to_firestore_doc(row: dict) -> dict:
    """Map a CSV row to the `products` document (Data model field names + provenance)."""
    return {
        "gtin": row["gtin"], "name": row["name"], "brand": row.get("brand", ""),
        "pack_size": row.get("pack_size", ""), "category": row.get("category", ""),
        "mrp_paise": row.get("mrp_paise"), "mrp_source": row.get("mrp_source", ""),
        "mrp_source_url": row.get("mrp_source_url", ""), "image_url": row.get("image_url", ""),
        "off_source_url": f"{OFF_BASE}/product/{row['gtin']}",
    }


def fetch_off_product(gtin: str, timeout: float = 30) -> dict | None:
    """GET /api/v2/product/{gtin}.json with retries; returns the OFF product dict or None."""
    url = f"{OFF_BASE}/api/v2/product/{gtin}.json"
    for _ in range(4):
        try:
            r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
            if r.status_code in (429, 502, 503, 504):
                continue
            data = r.json()
            return data.get("product") if data.get("status") == 1 else None
        except (httpx.HTTPError, ValueError):
            continue
    return None


def upsert_from_barcode(gtin: str, category: str = "", mrp_paise: int | None = None,
                        mrp_source: str = "manual", mrp_source_url: str = "", db=None) -> dict | None:
    """Look up a barcode on Open Food Facts and upsert the `products/{gtin}` doc. Returns the doc."""
    p = fetch_off_product(gtin)
    if not p:
        return None
    doc = to_firestore_doc({
        "gtin": gtin,
        "name": (p.get("product_name") or p.get("product_name_en") or "").strip(),
        "brand": (p.get("brands") or "").split(",")[0].strip(),
        "pack_size": normalize_pack_size(p.get("quantity") or ""),
        "category": category, "mrp_paise": mrp_paise, "mrp_source": mrp_source if mrp_paise else "",
        "mrp_source_url": mrp_source_url, "image_url": p.get("image_front_url") or "",
    })
    if db is None:
        from google.cloud import firestore
        db = firestore.Client()
    db.collection("products").document(gtin).set(doc, merge=True)
    return doc
