"""Shared pieces for registry adapters: the guided MANUAL check, the authorised-provider client interface,
and a small data.gov.in client.

Where an official portal needs a CAPTCHA and no authorised API credentials are configured, Sauda never
automates the portal. It creates a manual task instead: the official link, the fields a reviewer records,
an evidence slot, and status `pending`.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

from sauda_verify.models import CheckStatus, Dim, SourceKind
from sauda_verify.providers.base import ProviderResult

logging.getLogger("httpx").setLevel(logging.WARNING)  # keys can travel in URLs; never log them

MANUAL_SUMMARY = ("Manual check required: the official portal requires a CAPTCHA and no authorised API "
                  "credentials are configured")
USER_AGENT = "Sauda/0.1 (+https://saudaai.web.app)"
DATAGOV_BASE = "https://api.data.gov.in/resource/"


def manual_task(*, name: str, dim: Dim, source_name: str, source_url: str, identifier: tuple[str, str | None],
                reviewer_fields: list[str], extra: str = "") -> ProviderResult:
    """A pending guided manual check. `identifier` = (field, declared value) to look up on the portal."""
    field, value = identifier
    return ProviderResult(
        status=CheckStatus.pending, source_kind=SourceKind.human_review, source_name=source_name,
        source_url=source_url, dim=dim, check_type=f"{name}_manual", available=False,
        summary=MANUAL_SUMMARY + (f". {extra}" if extra else "."),
        observed={"manual_check": {
            "source_url": source_url,
            "lookup": {field: value},
            "reviewer_fields": reviewer_fields,
            "evidence_required": True,
            "instructions": (f"Open {source_url}, search for the {field.replace('_', ' ')} yourself, compare the "
                             "fields below with the declared details, attach a screenshot or the downloaded "
                             "certificate as evidence, and record your decision with a reason."),
        }},
    )


@runtime_checkable
class AuthorisedClient(Protocol):
    """An authorised provider (GSP, KYB vendor) reached with contract credentials from env."""
    name: str

    def configured(self) -> bool: ...

    def lookup(self, identifier: str, **kw: Any) -> dict | None: ...


def env_present(*names: str) -> bool:
    return all(os.environ.get(n) for n in names)


class DataGovUnavailable(Exception):
    """data.gov.in refused or failed (403 from cloud IPs, rate limit, key not authorised, outage)."""


def datagov_get(resource_id: str, params: dict, *, timeout: float = 15.0) -> dict:
    import httpx

    key = os.environ.get("DATA_GOV_IN_API_KEY")
    if not key:
        raise DataGovUnavailable("no data.gov.in key configured")
    try:
        r = httpx.get(DATAGOV_BASE + resource_id, params={"api-key": key, "format": "json", **params},
                      headers={"User-Agent": USER_AGENT}, timeout=timeout)
    except httpx.HTTPError as e:
        raise DataGovUnavailable(type(e).__name__) from None
    if r.status_code != 200:
        raise DataGovUnavailable(f"HTTP {r.status_code}")
    try:
        d = r.json()
    except ValueError:
        raise DataGovUnavailable("non-JSON response") from None
    msg = str(d.get("message") or d.get("error") or "")
    if d.get("status") not in (None, "ok") or "rate limit" in msg.lower() or "not authori" in msg.lower():
        raise DataGovUnavailable(msg or "error status")
    return d
