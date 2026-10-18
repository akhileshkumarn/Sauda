"""Fetch mandi reference prices (6.2) and write them to Firestore `price_refs` (idempotent).

Usage: uv run python scripts/fetch_price_refs.py [--state Karnataka] [--district "Bengaluru Urban"] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "sauda_data"))
from sauda_data.price_refs import doc_id, fetch_mandi


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def fetch_and_write(state: str, district: str, db=None, dry_run: bool = False) -> list[dict]:
    refs = fetch_mandi(state, district)
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "price_refs.json").write_text(json.dumps(refs, indent=1, ensure_ascii=False))
    if not dry_run:
        if db is None:
            from google.cloud import firestore
            db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        for ref in refs:
            db.collection("price_refs").document(doc_id(ref)).set(ref)
    return refs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="Karnataka")
    ap.add_argument("--district", default="Bengaluru Urban")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    load_env()
    refs = fetch_and_write(a.state, a.district, dry_run=a.dry_run)
    print(f"{'commodity':14s} {'scope':9s} {'modal/kg':>9s} {'min':>7s} {'max':>7s} {'n':>4s} as_of")
    for r in refs:
        print(f"{r['commodity']:14s} {r['scope']:9s} {r['modal_price_paise_per_kg']/100:9.2f} "
              f"{(r['min'] or 0)/100:7.2f} {(r['max'] or 0)/100:7.2f} {r['n_records']:4d} {r['as_of']}")


if __name__ == "__main__":
    main()
