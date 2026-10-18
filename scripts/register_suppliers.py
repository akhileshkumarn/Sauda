"""Write the supplier registry (Firestore `suppliers`) for the URLs in SUPPLIER_URLS.

  uv run scripts/register_suppliers.py            # uses SUPPLIER_URLS from .env (local)
  uv run scripts/register_suppliers.py --cloud    # the three Cloud Run supplier services

Card fingerprints include the card URL, so register the environment you are about to demo.
"""
import json
import os
import sys

from dotenv import load_dotenv

load_dotenv()

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
    for row in register_all(cloud_urls() if "--cloud" in sys.argv else None):
        print(json.dumps(row))
