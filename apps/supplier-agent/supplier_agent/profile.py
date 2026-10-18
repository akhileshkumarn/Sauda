"""Supplier profile loading. SUPPLIER_PROFILE selects suppliers/<id>.json (11.3 values)."""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def suppliers_dir() -> Path:
    return Path(os.environ.get("SUPPLIERS_DIR", REPO_ROOT / "suppliers"))


@cache
def load_profile(profile_id: str | None = None) -> dict:
    pid = profile_id or os.environ.get("SUPPLIER_PROFILE", "metro")
    path = suppliers_dir() / f"{pid}.json"
    with path.open(encoding="utf-8") as f:
        prof = json.load(f)
    if prof.get("id") != pid:
        raise ValueError(f"profile id mismatch in {path}")
    vpa = prof.get("payout_vpa") or ""
    if vpa.startswith("secret:"):
        # Real payee UPI IDs are not kept in git: Cloud Run mounts the secret as PAYOUT_VPA.
        real = os.environ.get("PAYOUT_VPA", "").strip()
        if not real:
            raise RuntimeError(f"{pid}: payout_vpa is {vpa} but PAYOUT_VPA is not set")
        prof["payout_vpa"] = real
    return prof
