"""One-off: fetch the data.gov.in All India Pincode Directory into data/pincodes/pincodes.csv.

data.gov.in rejects requests from cloud IPs (403), so this runs from a developer machine and the compact
CSV (pincode, district, state) is committed. Needs DATA_GOV_IN_API_KEY in .env (never printed).

Usage: uv run python scripts/fetch_pincodes.py [--page-size 5000]
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "pincodes"
# "All India Pincode Directory till last month", Department of Posts, Ministry of Communications
RESOURCE_ID = "5c2f62fe-5afa-4119-a499-fec9d604d5bd"
API_URL = f"https://api.data.gov.in/resource/{RESOURCE_ID}"
CATALOG_URL = "https://www.data.gov.in/catalog/all-india-pincode-directory"

# the API key travels as a query parameter; keep httpx from logging request URLs
logging.getLogger("httpx").setLevel(logging.WARNING)


def load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def _get(client: httpx.Client, params: dict, tries: int = 10) -> dict:
    for i in range(tries):
        try:
            r = client.get(API_URL, params=params)
            if r.status_code == 200:
                return r.json()
            err = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            err = type(e).__name__
        print(f"  retry {i + 1} ({err})", file=sys.stderr)
        time.sleep(min(60, 5 * (i + 1)))
    raise RuntimeError(f"data.gov.in request failed after {tries} tries ({err})")


def clean(s: str | None) -> str:
    return " ".join((s or "").replace(" ", " ").split()).upper()


def fetch(page_size: int) -> tuple[set[tuple[str, str, str]], dict]:
    key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not key:
        sys.exit("DATA_GOV_IN_API_KEY is not set")
    rows: set[tuple[str, str, str]] = set()
    meta: dict = {}
    # data.gov.in throttles the default python-httpx User-Agent; identify the project instead
    with httpx.Client(timeout=120, headers={"User-Agent": "Sauda/0.1 (+https://saudaai.web.app)"}) as client:
        offset, total = 0, None
        while total is None or offset < total:
            d = _get(client, {"api-key": key, "format": "json", "limit": page_size, "offset": offset,
                                "fields": "pincode,district,statename"})
            if total is None:
                total = int(d.get("total") or 0)
                meta = {"title": d.get("title"), "total": total, "updated_date": d.get("updated_date"),
                        "org": d.get("org")}
            recs = d.get("records") or []
            if not recs:
                break
            for r in recs:
                pin = str(r.get("pincode") or "").split(".")[0].strip()
                if len(pin) == 6 and pin.isdigit():
                    rows.add((pin, clean(r.get("district")), clean(r.get("statename"))))
            offset += len(recs)
            print(f"  fetched {offset}/{total}", file=sys.stderr)
    meta["records_read"] = offset
    return rows, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page-size", type=int, default=2000)
    a = ap.parse_args()
    load_env()
    rows, meta = fetch(a.page_size)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with (OUT_DIR / "pincodes.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pincode", "district", "state"])
        w.writerows(sorted(rows))
    fetched_at = datetime.now(UTC).date().isoformat()
    print(f"resource={RESOURCE_ID} title={meta.get('title')!r} updated={meta.get('updated_date')} "
          f"records_read={meta.get('records_read')} unique_rows={len(rows)} "
          f"unique_pins={len({r[0] for r in rows})} fetched={fetched_at}")


if __name__ == "__main__":
    main()
