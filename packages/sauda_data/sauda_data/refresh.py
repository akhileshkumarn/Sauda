"""Daily refresh of mandi reference prices (Cloud Run job `price-refresh`, triggered by Cloud Scheduler).

  python -m sauda_data.refresh [--state Karnataka] [--district "Bengaluru Urban"] [--dry-run]

Each (commodity, scope) is its own document and is only overwritten by a record at least as recent, so a quiet
market day never erases the last good district price; `price_refs.pick_ref` then decides which scope the buyer
uses (local while fresh, else the freshest). Exits non-zero when
data.gov.in returns nothing, so the job shows as failed in Cloud Run instead of silently keeping stale data.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime

from .price_refs import doc_id, fetch_mandi

log = logging.getLogger("sauda_data.refresh")


def should_replace(old: dict | None, new: dict) -> bool:
    """Same document (same commodity and scope): never overwrite with an older record."""
    return not old or (old.get("as_of") or "") <= (new.get("as_of") or "")


def refresh(state: str, district: str, db=None, dry_run: bool = False) -> dict:
    refs = fetch_mandi(state, district)
    if not refs:
        raise RuntimeError("data.gov.in returned no mandi records")
    if db is None:
        from google.cloud import firestore

        db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    updated, kept = [], []
    for ref in refs:
        did = doc_id(ref)
        old = db.collection("price_refs").document(did).get().to_dict() if db is not None else None
        if not should_replace(old, ref):
            kept.append({"commodity": ref["commodity"], "scope": old.get("scope"), "as_of": old.get("as_of"),
                         "offered": f'{ref["scope"]} {ref["as_of"]}'})
            continue
        updated.append({"commodity": ref["commodity"], "scope": ref["scope"], "as_of": ref["as_of"],
                        "modal_price_paise_per_kg": ref["modal_price_paise_per_kg"]})
        if not dry_run:
            db.collection("price_refs").document(did).set(ref)
    summary = {"refreshed_at": datetime.now(UTC).isoformat(timespec="seconds"), "state": state, "district": district,
               "updated": len(updated), "kept_newer": len(kept),
               "latest_as_of": max((r["as_of"] for r in updated), default=None), "source": "data.gov.in mandi"}
    if not dry_run:
        db.collection("price_refs_meta").document("latest").set(summary)
    return {**summary, "updated_rows": updated, "kept_rows": kept}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default=os.environ.get("REF_STATE", "Karnataka"))
    ap.add_argument("--district", default=os.environ.get("REF_DISTRICT", "Bengaluru Urban"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        out = refresh(a.state, a.district, dry_run=a.dry_run)
    except Exception as e:  # surfaced as a failed job execution
        log.exception("price refresh failed: %s", e)
        return 1
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
