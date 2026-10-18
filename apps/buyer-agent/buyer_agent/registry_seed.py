"""Register the supplier agents in Firestore `suppliers`: fetch each agent card from SUPPLIER_URLS, store
sha256(canonical(card)) as the fingerprint and payout_vpa from suppliers/<id>.json (status allowlisted).

  uv run --package buyer-agent python -m buyer_agent.registry_seed
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

from sauda_trust import registry

from .deps import settings
from .negotiation.a2a import CARD_PATH, fetch_card

REPO = Path(__file__).resolve().parents[3]


def resolve_vpa(sid: str, vpa: str | None) -> str | None:
    """`secret:<name>` -> env PAYOUT_VPA_<SID>, else Secret Manager via the operator's gcloud login."""
    if not vpa or not vpa.startswith("secret:"):
        return vpa
    env = os.environ.get(f"PAYOUT_VPA_{sid.upper()}", "").strip()
    if env:
        return env
    import subprocess

    out = subprocess.run(["gcloud", "secrets", "versions", "access", "latest", "--secret", vpa.split(":", 1)[1],
                          "--project", os.environ["GOOGLE_CLOUD_PROJECT"]],
                         capture_output=True, text=True, timeout=30, check=True)
    return out.stdout.strip()


def register_all(urls: dict[str, str] | None = None) -> list[dict]:
    urls = urls or settings().supplier_urls
    out = []
    for sid, base in urls.items():
        prof_path = REPO / "suppliers" / f"{sid}.json"
        prof = json.loads(prof_path.read_text()) if prof_path.exists() else {}
        card = fetch_card(base, use_cache=False)
        vpa = resolve_vpa(sid, prof.get("payout_vpa"))
        if not vpa:
            raise SystemExit(f"{sid}: no payout_vpa in {prof_path}")
        rec = registry.upsert_supplier({
            "supplier_id": sid,
            "name": prof.get("name") or card.get("name") or sid,
            "agent_card_url": base + CARD_PATH,
            "fingerprint": registry.card_fingerprint(card),
            "payout_vpa": vpa,
            "payout_account_hash": hashlib.sha256(vpa.encode()).hexdigest(),
            "status": "allowlisted",
            "reputation_score": None,
        })
        # clear any quarantine left from a previous demo run
        from sauda_trust import settings as ts

        ts.firestore_client().collection("suppliers").document(sid).set({"quarantine_reason": None}, merge=True)
        out.append({"supplier_id": sid, "url": base, "fingerprint": rec.fingerprint[:16] + "...", "payout_vpa": vpa[:3] + "***"})
    return out


if __name__ == "__main__":
    for r in register_all():
        print(json.dumps(r))
    sys.exit(0)
