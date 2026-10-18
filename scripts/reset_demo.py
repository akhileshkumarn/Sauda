"""Restore the demo shop to a known state: re-register suppliers (clears quarantine) and clear the active negotiation.

  uv run scripts/reset_demo.py [--cloud]

The ledger is append-only and is never deleted; a fresh run starts a new negotiation chain.
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from buyer_agent import store  # noqa: E402
from buyer_agent.registry_seed import register_all  # noqa: E402

def _project_number() -> str:
    import subprocess
    if os.environ.get("GCP_PROJECT_NUMBER"):
        return os.environ["GCP_PROJECT_NUMBER"]
    return subprocess.run(["gcloud", "projects", "describe", os.environ["GOOGLE_CLOUD_PROJECT"], "--format=value(projectNumber)"],
                          capture_output=True, text=True, check=True).stdout.strip()


def cloud_urls() -> dict[str, str]:
    pn = _project_number()
    return {s: f"https://supplier-{s}-{pn}.asia-south1.run.app" for s in ("metro", "sharma", "quickstock")}

if __name__ == "__main__":
    rows = register_all(cloud_urls() if "--cloud" in sys.argv else None)
    print(f"suppliers registered: {[r['supplier_id'] for r in rows]}")
    store.update_shop("demo", active_negotiation_id=None)
    print("demo shop: active negotiation cleared")
