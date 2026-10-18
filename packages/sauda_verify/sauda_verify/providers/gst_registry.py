"""GST registration lookup through an authorised provider, else a guided manual check.

The GST portal's taxpayer search requires a CAPTCHA and is never automated. GSTN public APIs are only
reachable through GSPs / authorised KYB providers under contract. Adapters below are enabled only when their
env credentials exist (none are configured today); otherwise the result is a MANUAL task.

Env:
  Cashfree: CASHFREE_CLIENT_ID, CASHFREE_CLIENT_SECRET, CASHFREE_ENV=sandbox|production
  Setu:     SETU_CLIENT_ID, SETU_CLIENT_SECRET, SETU_PRODUCT_INSTANCE_ID, SETU_ENV=sandbox|production
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers import gstin as gstin_mod
from sauda_verify.providers._common import (
    consent_denied,
    mode,
    name_field,
    not_consented,
)
from sauda_verify.providers._registry import (
    USER_AGENT,
    AuthorisedClient,
    env_present,
    manual_task,
)
from sauda_verify.providers.base import ProviderResult

log = logging.getLogger("sauda_verify.gst_registry")

PORTAL_URL = "https://services.gst.gov.in/services/searchtp"
REVIEWER_FIELDS = ["legal_name", "trade_name", "status", "constitution", "registration_date",
                   "principal_place_of_business", "pin"]


class CashfreeGstClient:
    """Cashfree Verification Suite: POST /verification/gstin {GSTIN, business_name}."""
    name = "Cashfree GSTIN verification"

    def configured(self) -> bool:
        return env_present("CASHFREE_CLIENT_ID", "CASHFREE_CLIENT_SECRET")

    @property
    def sandbox(self) -> bool:
        return os.environ.get("CASHFREE_ENV", "sandbox").lower() != "production"

    def lookup(self, identifier: str, **kw: Any) -> dict | None:
        import httpx

        base = "https://sandbox.cashfree.com" if self.sandbox else "https://api.cashfree.com"
        r = httpx.post(f"{base}/verification/gstin", timeout=15,
                       headers={"x-client-id": os.environ["CASHFREE_CLIENT_ID"],
                                "x-client-secret": os.environ["CASHFREE_CLIENT_SECRET"],
                                "User-Agent": USER_AGENT, "Content-Type": "application/json"},
                       json={"GSTIN": identifier, "business_name": kw.get("business_name") or ""})
        r.raise_for_status()
        d = r.json()
        if not d.get("valid", True) and not d.get("legal_name_of_business"):
            return None
        a = d.get("principal_place_split_address") or {}
        return {"gstin": d.get("GSTIN"), "legal_name": d.get("legal_name_of_business"),
                "trade_name": d.get("trade_name_of_business"), "status": d.get("gst_in_status"),
                "constitution": d.get("constitution_of_business"), "registration_date": d.get("date_of_registration"),
                "pincode": str(a.get("pincode") or ""), "state": a.get("state"), "ref": d.get("reference_id")}


class SetuGstClient:
    """Setu GST verification (contract credentials). Response mapping is defensive: confirm against Setu docs
    when credentials are issued."""
    name = "Setu GST verification"

    def configured(self) -> bool:
        return env_present("SETU_CLIENT_ID", "SETU_CLIENT_SECRET", "SETU_PRODUCT_INSTANCE_ID")

    @property
    def sandbox(self) -> bool:
        return os.environ.get("SETU_ENV", "sandbox").lower() != "production"

    def lookup(self, identifier: str, **kw: Any) -> dict | None:
        import httpx

        base = "https://dg-sandbox.setu.co" if self.sandbox else "https://dg.setu.co"
        r = httpx.post(f"{base}/api/verify/gst", timeout=15, json={"gstin": identifier},
                       headers={"x-client-id": os.environ["SETU_CLIENT_ID"],
                                "x-client-secret": os.environ["SETU_CLIENT_SECRET"],
                                "x-product-instance-id": os.environ["SETU_PRODUCT_INSTANCE_ID"],
                                "User-Agent": USER_AGENT})
        r.raise_for_status()
        d = (r.json() or {}).get("data") or {}
        if not d:
            return None
        addr = (d.get("principalPlaceOfBusinessFields") or {}).get("principalPlaceOfBusinessAddress") or {}
        return {"gstin": d.get("gstin") or identifier, "legal_name": d.get("legalNameOfBusiness") or d.get("lgnm"),
                "trade_name": d.get("tradeName") or d.get("tradeNam"), "status": d.get("gstnStatus") or d.get("sts"),
                "constitution": d.get("constitutionOfBusiness") or d.get("ctb"),
                "registration_date": d.get("dateOfRegistration") or d.get("rgdt"),
                "pincode": str(addr.get("pincode") or ""), "state": addr.get("stateName"), "ref": d.get("id")}


CLIENTS: list[AuthorisedClient] = [CashfreeGstClient(), SetuGstClient()]


def configured_client() -> AuthorisedClient | None:
    return next((c for c in CLIENTS if c.configured()), None)


def compare(biz: Business, rec: dict, source_name: str, source_kind: SourceKind = SourceKind.authorised_provider,
            source_url: str | None = None) -> ProviderResult:
    """Declared vs registry record. Used for authorised-provider responses and (by simulated.py) fixtures."""
    fields: list[FieldCompare] = []
    legal_f, legal_r = name_field("legal_name", biz.legal_name, rec.get("legal_name"))
    if biz.legal_name:
        fields.append(legal_f)
    trade_f, trade_r = name_field("trade_name", biz.display_name, rec.get("trade_name") or rec.get("legal_name"))
    fields.append(trade_f)
    st = (rec.get("status") or "").strip()
    active = st.lower() == "active"
    fields.append(FieldCompare(field="gst_status", declared="Active", observed=st or None, match=active))
    pin = re.sub(r"\D", "", biz.address.pin or "")
    if pin and rec.get("pincode"):
        fields.append(FieldCompare(field="principal_place_pin", declared=pin, observed=rec["pincode"],
                                   match=pin == rec["pincode"]))
    observed = {k: rec.get(k) for k in ("legal_name", "trade_name", "status", "constitution", "registration_date",
                                        "pincode", "state")}
    base = dict(source_kind=source_kind, source_name=source_name, source_url=source_url, dim=Dim.registration,
                check_type="gst_registry", fields=fields, observed=observed, provider_ref=rec.get("ref"))
    if not active:
        return ProviderResult(status=CheckStatus.conflict, **base,
                              summary=f"The GST registration status is '{st or 'unknown'}', not Active.")
    different = [f.field for f in fields if f.match is False]
    if legal_r == "different" or (trade_r == "different" and legal_r != "exact"):
        return ProviderResult(status=CheckStatus.conflict, **base,
                              summary="The registered GST names do not match the declared business name: "
                                      + ", ".join(different) + ". A reviewer needs to look at this.")
    near = [f.field for f in fields if f.match is None and f.field.endswith("_name")]
    if near or different:
        parts = []
        if near:
            parts.append("near-match on " + ", ".join(near) + " (e.g. spelling variant)")
        if different:
            parts.append("mismatch on " + ", ".join(different))
        return ProviderResult(status=CheckStatus.partially_verified, **base,
                              summary=("The GST registration is Active, but " + "; ".join(parts)
                                       + ". A reviewer must confirm before this counts as a match."))
    return ProviderResult(status=CheckStatus.verified, **base,
                          summary=("The GST registration is Active and the registered names and PIN match the "
                                   "declared details. A valid GST registration alone does not make a business "
                                   "legitimate or confirm who may act for it."))


def _manual(biz: Business) -> ProviderResult:
    return manual_task(name="gst_registry", dim=Dim.registration, source_name="GST portal taxpayer search (manual)",
                       source_url=PORTAL_URL, identifier=("gstin", gstin_mod.normalise(biz.gstin)),
                       reviewer_fields=REVIEWER_FIELDS)


class GstRegistryProvider:
    name = "gst_registry"
    dims = [Dim.registration]
    consent_key = "gst"

    def applicable(self, biz: Business) -> bool:
        return bool((biz.gstin or "").strip()) and not biz.is_fixture

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify" or biz.is_fixture or (ctx or {}).get("is_fixture"):
            return []
        if consent_denied(ctx, self.consent_key):
            return [not_consented(self.name, Dim.registration, self.consent_key)]
        client = configured_client()
        if client is None:
            return [_manual(biz)]
        g = gstin_mod.normalise(biz.gstin)
        # sandbox sample GSTINs fail the checksum, so only production skips invalid numbers
        if not getattr(client, "sandbox", False) and not gstin_mod.parse(g)["valid"]:
            return [ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.authorised_provider,
                                   source_name=client.name, dim=Dim.registration, check_type="gst_registry",
                                   summary="Not looked up: the GSTIN fails the format check (see the format result).")]
        rec = client.lookup(g, business_name=biz.legal_name or biz.display_name)  # errors -> inconclusive upstream
        if rec is None:
            return [ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.authorised_provider,
                                   source_name=client.name, dim=Dim.registration, check_type="gst_registry",
                                   summary="The provider returned no registration for this GSTIN. Not a negative "
                                           "finding on its own; a manual check is suggested.")]
        label = client.name + (" (sandbox: synthetic data)" if getattr(client, "sandbox", False) else "")
        return [compare(biz, rec, label)]
