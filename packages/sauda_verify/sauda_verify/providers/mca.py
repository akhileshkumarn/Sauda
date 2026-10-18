"""Company identity from the MCA company master data published on data.gov.in (official_registry).

Lookup by CIN against the "Registrars of Companies (RoC)-wise Company Master Data" resource. data.gov.in
refuses requests from Google Cloud IPs (403), so on Cloud Run this lookup usually returns inconclusive with
a manual fallback; it works from a developer machine. The MCA21 portal itself needs a CAPTCHA and is never
automated. LLPs (LLPIN) go straight to the manual check.
"""
from __future__ import annotations

import logging
import re

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers._common import (
    consent_denied,
    mode,
    name_field,
    norm_state,
    not_consented,
)
from sauda_verify.providers._registry import (
    DataGovUnavailable,
    datagov_get,
    manual_task,
)
from sauda_verify.providers.base import ProviderResult

log = logging.getLogger("sauda_verify.mca")

RESOURCE_ID = "4dbe5667-7b6b-41d7-82af-211562424d9a"
DATASET_URL = "https://www.data.gov.in/resource/registrars-companies-roc-wise-company-master-data"
PORTAL_URL = "https://www.mca.gov.in/content/mca/global/en/mca/master-data/MDS.html"
CIN_RE = re.compile(r"^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$")
LLPIN_RE = re.compile(r"^[A-Z]{3}-?[0-9]{4}$")
REVIEWER_FIELDS = ["company_name", "status", "registered_office_address", "date_of_incorporation",
                   "directors_or_designated_partners"]


def _manual(biz: Business, extra: str = "") -> ProviderResult:
    return manual_task(name="mca", dim=Dim.identity, source_name="MCA21 company/LLP master data (manual)",
                       source_url=PORTAL_URL, identifier=("cin_llpin", biz.cin_llpin),
                       reviewer_fields=REVIEWER_FIELDS, extra=extra)


def compare(biz: Business, rec: dict, dataset_date: str) -> ProviderResult:
    src = f"MCA company master data via data.gov.in (dataset {dataset_date})"
    fields: list[FieldCompare] = []
    declared_name = biz.legal_name or biz.display_name
    f, name_r = name_field("legal_name", declared_name, rec.get("CompanyName"))
    fields.append(f)
    status = (rec.get("CompanyStatus") or "").strip()
    fields.append(FieldCompare(field="company_status", declared="Active", observed=status or None,
                               match=status.lower() == "active"))
    addr = rec.get("Registered_Office_Address") or ""
    pin = re.sub(r"\D", "", biz.address.pin or "")
    if pin:
        fields.append(FieldCompare(field="registered_office_pin", declared=pin,
                                   observed=(re.findall(r"\b\d{6}\b", addr) or [None])[-1], match=pin in addr))
    st = norm_state(rec.get("CompanyStateCode"))
    if biz.address.state and st:
        fields.append(FieldCompare(field="state", declared=biz.address.state, observed=st.title(),
                                   match=norm_state(biz.address.state) == st))
    observed = {"cin": rec.get("CIN"), "company_name": rec.get("CompanyName"), "status": status,
                "roc": rec.get("CompanyROCcode"), "registration_date": rec.get("CompanyRegistrationdate_date"),
                "category": rec.get("CompanyCategory"), "class": rec.get("CompanyClass"),
                "registered_office": addr, "dataset_date": dataset_date}
    base = dict(source_kind=SourceKind.official_registry, source_name=src, source_url=DATASET_URL, dim=Dim.identity,
                check_type="mca_master_data", fields=fields, observed=observed, provider_ref=f"data.gov.in:{RESOURCE_ID}")
    if status.lower() != "active":
        return ProviderResult(status=CheckStatus.conflict, **base,
                              summary=f"MCA records the company status as '{status or 'unknown'}', not Active.")
    if name_r == "different":
        return ProviderResult(status=CheckStatus.conflict, **base,
                              summary=f"The CIN belongs to '{rec.get('CompanyName')}', which does not match the "
                                      f"declared name '{declared_name}'.")
    note = ("Registered office is a registered address, not proof that the business operates there. "
            "This does not confirm who may act for the company.")
    if name_r == "near":
        return ProviderResult(status=CheckStatus.partially_verified, **base,
                              summary=f"MCA lists '{rec.get('CompanyName')}' as Active; the declared name is a near "
                                      f"match and needs a reviewer to confirm. {note}")
    return ProviderResult(status=CheckStatus.verified, **base,
                          summary=f"MCA master data lists '{rec.get('CompanyName')}' with this CIN as Active. {note}")


def lookup(biz: Business) -> ProviderResult:
    cin = re.sub(r"\s", "", (biz.cin_llpin or "").upper())
    if not CIN_RE.match(cin):
        if LLPIN_RE.match(cin):
            return _manual(biz, "LLP records are not in the data.gov.in company dataset")
        return ProviderResult(status=CheckStatus.failed, source_kind=SourceKind.preliminary_validation,
                              source_name="CIN format check (offline)", dim=Dim.identity, check_type="mca_cin_format",
                              fields=[FieldCompare(field="cin", declared=biz.cin_llpin, observed="invalid format",
                                                   match=False)],
                              summary="The CIN/LLPIN format is invalid; likely a typo.")
    try:
        d = datagov_get(RESOURCE_ID, {"filters[CIN]": cin, "limit": 5})
    except DataGovUnavailable as e:
        log.info("MCA data.gov.in lookup unavailable: %s", e)
        m = _manual(biz)
        return m.model_copy(update={
            "status": CheckStatus.inconclusive,
            "summary": ("The MCA dataset on data.gov.in could not be reached from this server (it refuses cloud "
                        "IPs or was rate limited). Not a negative finding. " + m.summary)})
    dataset_date = (d.get("updated_date") or "")[:10] or "unknown date"
    recs = [r for r in d.get("records") or [] if (r.get("CIN") or "").upper() == cin]
    if not recs:
        return ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.official_registry,
                              source_name=f"MCA company master data via data.gov.in (dataset {dataset_date})",
                              source_url=DATASET_URL, dim=Dim.identity, check_type="mca_master_data",
                              summary="No company with this CIN is in the published MCA dataset. This is not a "
                                      "negative finding (the dataset may lag); a manual check is suggested.",
                              observed={"cin": cin, "dataset_date": dataset_date})
    return compare(biz, recs[0], dataset_date)


class McaProvider:
    name = "mca"
    dims = [Dim.identity]
    consent_key = "mca"

    def applicable(self, biz: Business) -> bool:
        return bool((biz.cin_llpin or "").strip()) and not biz.is_fixture

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify" or biz.is_fixture or (ctx or {}).get("is_fixture"):
            return []
        if consent_denied(ctx, self.consent_key):
            return [not_consented(self.name, Dim.identity, self.consent_key)]
        return [lookup(biz)]
