"""Seed Firestore for the Plan B demo (idempotent; re-running overwrites).

Collections: shops, products (data/products.csv), price_refs (data.gov.in mandi), calendar.
Does NOT seed suppliers (scripts/register_suppliers.py owns the registry).

Usage: uv run python scripts/seed.py [--skip-price-refs]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "sauda_data"))
sys.path.insert(0, str(ROOT / "scripts"))
from fetch_price_refs import fetch_and_write, load_env
from sauda_data.calendar import calendar_docs
from sauda_data.price_refs import ceiling_for, doc_id
from sauda_data.products import load_csv, to_firestore_doc

DEMO_SHOP = {
    "shop_id": "demo",
    "owner_uid": None,
    "name": "Lakshmi Kirana Stores",
    "language": "en",
    "district": "Bengaluru Urban",
    "state": "Karnataka",
    "monthly_purchase_paise": 15000000,
    "minutes_per_supplier_call": 6,
    "preferred_supplier_id": None,
    "disclosure": "Demo shop: product set and prices are real; the owner is a team member; "
                  "demand uplift is a stated assumption.",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-price-refs", action="store_true", help="reuse data/price_refs.json instead of the API")
    a = ap.parse_args()
    load_env()
    from google.cloud import firestore

    db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    counts = {}

    shop_id = os.environ.get("DEMO_SHOP_ID", "demo") or "demo"
    db.collection("shops").document(shop_id).set({**DEMO_SHOP, "shop_id": shop_id})
    counts["shops"] = 1

    rows = [r for r in load_csv(ROOT / "data" / "products.csv") if r.get("mrp_paise")]
    batch, n = db.batch(), 0
    for r in rows:
        batch.set(db.collection("products").document(r["gtin"]), to_firestore_doc(r))
        n += 1
        if n % 400 == 0:
            batch.commit()
            batch = db.batch()
    batch.commit()
    counts["products"] = n

    if a.skip_price_refs and (ROOT / "data" / "price_refs.json").exists():
        refs = json.loads((ROOT / "data" / "price_refs.json").read_text())
        for ref in refs:
            db.collection("price_refs").document(doc_id(ref)).set(ref)
    else:
        refs = fetch_and_write(DEMO_SHOP["state"], DEMO_SHOP["district"], db=db)
    counts["price_refs"] = len(refs)

    cal = calendar_docs()
    for c in cal:
        db.collection("calendar").document(c["festival_id"]).set(c)
    counts["calendar"] = len(cal)

    print("Seeded Firestore project", db.project)
    for k, v in counts.items():
        live = sum(1 for _ in db.collection(k).select([]).stream())
        print(f"  {k:11s} written={v:3d}  in_collection={live}")

    by_commodity = {r["commodity"]: r for r in refs}
    print("\nSample ceilings (rule 6.5):")
    samples = rows[:3] + [
        {"name": "Loose sona masoori rice", "brand": "", "category": "rice", "pack_size": "25 kg", "loose": True},
        {"name": "Loose toor dal", "brand": "", "category": "dal", "pack_size": "1 kg", "loose": True},
    ]
    for p in samples:
        c = ceiling_for(p, by_commodity)
        if c:
            print(f"  {p['name'][:34]:34s} {p['pack_size']:>7s} -> Rs {c['ceiling_paise']/100:8.2f} "
                  f"[{c['ceiling_source']}] {c['as_of']}")


if __name__ == "__main__":
    main()
