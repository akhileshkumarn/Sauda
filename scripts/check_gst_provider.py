"""Call the configured GST provider's SANDBOX once with a sample GSTIN and print only status fields.

    uv run python scripts/check_gst_provider.py [GSTIN]

Credentials come from .env (or the environment): CASHFREE_CLIENT_ID + CASHFREE_CLIENT_SECRET, or SETU_CLIENT_ID +
SETU_CLIENT_SECRET + SETU_PRODUCT_INSTANCE_ID. The script always forces sandbox mode, never prints credentials,
names or addresses, and exits 2 when no provider is configured. Sandbox responses are the provider's sample data,
so the result is reported as inconclusive by design.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Setu's documented sandbox sample (docs.setu.co/data/gst). Pass another GSTIN for the Cashfree sandbox if needed.
DEFAULT_SAMPLE = "27AAICB3918J1CT"


def load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> int:
    load_env()
    os.environ["CASHFREE_ENV"] = "sandbox"
    os.environ["SETU_ENV"] = "sandbox"
    from sauda_verify.models import Address, Business
    from sauda_verify.providers import gst_registry

    client = gst_registry.configured_client()
    if client is None:
        print("provider: none configured (set CASHFREE_CLIENT_ID/CASHFREE_CLIENT_SECRET or "
              "SETU_CLIENT_ID/SETU_CLIENT_SECRET/SETU_PRODUCT_INSTANCE_ID)")
        return 2
    gstin = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GST_SAMPLE_GSTIN") or DEFAULT_SAMPLE).strip().upper()
    print(f"provider: {client.name} (sandbox)")
    print(f"gstin: {gstin[:2]}••••••••{gstin[-3:]}")
    try:
        rec = client.lookup(gstin, business_name="Sample Business")
    except Exception as e:  # report the HTTP status only, never the request
        status = getattr(getattr(e, "response", None), "status_code", None)
        print(f"call: failed ({type(e).__name__}{f', HTTP {status}' if status else ''})")
        return 1
    if rec is None:
        print("call: ok; provider returned no registration for this GSTIN")
        return 0
    biz = Business(bid="check", display_name="Sample Business", gstin=gstin, address=Address())
    r = gst_registry.sandbox_result(biz, rec, client.name)
    print("call: ok")
    print(f"gst_status: {rec.get('status')}")
    print(f"valid: {rec.get('valid')}")
    print(f"has_legal_name: {bool(rec.get('legal_name'))}")
    print(f"has_reference_id: {bool(rec.get('ref'))}")
    print(f"check_status: {r.status.value} (source_kind={r.source_kind.value}, source_name={r.source_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
