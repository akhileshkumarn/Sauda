"""Simulated registry data for the demo scenario ONLY (source_kind simulated_fixture).

Nothing here is real registry data. Every record is invented for the clearly labelled demo businesses
(ids prefixed fx_, is_fixture=True), and every result is labelled `simulated_fixture` with source
"Simulated GST registry (demo fixture)". The fixture GSTINs are made-up numbers built with a 'ZZZ' PAN
prefix and a valid check character so the real offline format check passes on them.

Use from the seed: `fixture_results(biz)` returns the labelled rows for one fixture business, and
DEMO_BUSINESSES carries suggested declared fields. Providers refuse to run for non-fixture businesses.
"""
from __future__ import annotations

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers._common import mode
from sauda_verify.providers.base import ProviderResult

SOURCE_NAME = "Simulated GST registry (demo fixture)"
BRAND_SOURCE = "Simulated brand authorisation register (demo fixture)"
FIXTURE_NOTE = "Demo fixture: simulated data, not from any real registry."

# keyed by fixture GSTIN; all values invented
FIXTURE_GST: dict[str, dict] = {
    "36ZZZFS0001A1ZH": {"legal_name": "SRI LAKSHMI GENERAL STORES", "trade_name": "SRI LAXMI GENERAL STORE",
                        "status": "Active", "constitution": "Partnership", "registration_date": "2019-04-01",
                        "pincode": "500016", "state": "Telangana", "ref": "fx-gst-1"},
    "36ZZZPA0002B1ZB": {"legal_name": "ANNAPURNA RICE TRADERS", "trade_name": "ANNAPURNA RICE TRADERS",
                        "status": "Active", "constitution": "Proprietorship", "registration_date": "2018-07-12",
                        "pincode": "500002", "state": "Telangana", "ref": "fx-gst-2"},
    "36ZZZCD0003C1ZW": {"legal_name": "DECCAN EDIBLE OILS PRIVATE LIMITED", "trade_name": "DECCAN EDIBLE OILS",
                        "status": "Active", "constitution": "Private Limited Company", "registration_date": "2017-09-20",
                        "pincode": "500080", "state": "Telangana", "ref": "fx-gst-3"},
    "36ZZZFM0004D1ZE": {"legal_name": "METRO DISTRIBUTORS", "trade_name": "METRO DISTRIBUTORS",
                        "status": "Active", "constitution": "Partnership", "registration_date": "2017-07-01",
                        "pincode": "500003", "state": "Telangana", "ref": "fx-gst-4"},
}

# brand -> fixture distributor GSTINs a simulated brand register would list (none: the Deccan claim must go to
# human review)
FIXTURE_BRAND_REGISTER: dict[str, set[str]] = {}

DEMO_BUSINESSES: dict[str, dict] = {
    "fx_sri_lakshmi": {
        "roles": ["buyer"], "display_name": "Sri Lakshmi General Stores", "legal_name": "Sri Lakshmi General Stores",
        "constitution": "Partnership", "category": "kirana", "products": ["staples", "edible oil", "rice"],
        "gstin": "36ZZZFS0001A1ZH",
        "address": {"line": "Plot 12, Prakash Nagar, Begumpet", "city": "Hyderabad", "state": "Telangana", "pin": "500016"},
        "representative": {"name": "Demo owner (fixture)", "role": "Partner", "authority_status": "pending"},
    },
    "fx_annapurna_rice": {
        "roles": ["seller"], "display_name": "Annapurna Rice Traders", "legal_name": "Annapurna Rice Traders",
        "constitution": "Proprietorship", "category": "rice wholesaler", "products": ["rice"],
        "gstin": "36ZZZPA0002B1ZB",
        "address": {"line": "Begum Bazar", "city": "Hyderabad", "state": "Telangana", "pin": "500002"},
        "representative": {"name": "Demo proprietor (fixture)", "role": "Proprietor", "authority_status": "self_declared"},
    },
    "fx_deccan_oils": {
        "roles": ["seller"], "display_name": "Deccan Edible Oils", "legal_name": "Deccan Edible Oils Private Limited",
        "constitution": "Private Limited Company", "category": "edible oil distributor", "products": ["edible oil"],
        "gstin": "36ZZZCD0003C1ZW", "brand_claims": ["Fortune"],
        "address": {"line": "Kavadiguda Main Road", "city": "Hyderabad", "state": "Telangana", "pin": "500080"},
        "representative": {"name": "Demo director (fixture)", "role": "Director", "authority_status": "self_declared"},
    },
    "fx_metro_distributors": {
        "roles": ["seller"], "display_name": "Metro Distributors", "legal_name": "Metro Distributors",
        "constitution": "Partnership", "category": "FMCG distributor", "products": ["staples", "packaged foods"],
        "gstin": "36ZZZFM0004D1ZE",
        "address": {"line": "Secunderabad", "city": "Hyderabad", "state": "Telangana", "pin": "500003"},
        "representative": {"name": "Demo partner (fixture)", "role": "Partner", "authority_status": "self_declared"},
    },
}


def _require_fixture(biz: Business) -> None:
    if not biz.is_fixture:
        raise ValueError("simulated providers run only for fixture businesses (is_fixture=True)")


def gst_result(biz: Business) -> ProviderResult:
    """Simulated GST registry row for a fixture business, compared like a real provider response."""
    _require_fixture(biz)
    from sauda_verify.providers import gst_registry, gstin

    rec = FIXTURE_GST.get(gstin.normalise(biz.gstin))
    if rec is None:
        return ProviderResult(status=CheckStatus.inconclusive, source_kind=SourceKind.simulated_fixture,
                              source_name=SOURCE_NAME, dim=Dim.registration, check_type="gst_registry",
                              summary=f"No simulated GST record for this GSTIN. {FIXTURE_NOTE}")
    r = gst_registry.compare(biz, rec, SOURCE_NAME, source_kind=SourceKind.simulated_fixture)
    return r.model_copy(update={"summary": f"{r.summary} {FIXTURE_NOTE}", "provider_ref": rec["ref"]})


def identity_result(biz: Business) -> ProviderResult:
    """Simulated identity row (legal name) derived from the same fixture record."""
    _require_fixture(biz)
    from sauda_verify.providers import gstin
    from sauda_verify.providers._common import name_field

    rec = FIXTURE_GST.get(gstin.normalise(biz.gstin)) or {}
    f, r = name_field("legal_name", biz.legal_name or biz.display_name, rec.get("legal_name"))
    status = {"exact": CheckStatus.verified, "near": CheckStatus.partially_verified,
              "different": CheckStatus.conflict}.get(r, CheckStatus.inconclusive)
    words = {"exact": "matches", "near": "nearly matches (reviewer must confirm)", "different": "does not match"}
    return ProviderResult(status=status, source_kind=SourceKind.simulated_fixture, source_name=SOURCE_NAME,
                          dim=Dim.identity, check_type="gst_legal_name", fields=[f],
                          summary=(f"The simulated registry's legal name {words.get(r, 'is unavailable and')} "
                                   f"the declared legal name. {FIXTURE_NOTE}"))


def brand_results(biz: Business) -> list[ProviderResult]:
    _require_fixture(biz)
    from sauda_verify.providers import gstin

    out = []
    for brand in biz.brand_claims:
        listed = gstin.normalise(biz.gstin) in FIXTURE_BRAND_REGISTER.get(brand.lower(), set())
        out.append(ProviderResult(
            status=CheckStatus.partially_verified if listed else CheckStatus.pending,
            source_kind=SourceKind.simulated_fixture, source_name=BRAND_SOURCE, dim=Dim.distribution_authority,
            check_type="brand_authorisation",
            fields=[FieldCompare(field="brand", declared=brand, observed="listed" if listed else None,
                                 match=True if listed else None)],
            summary=(f"The claim to distribute {brand} needs human review: upload the brand's authorisation letter "
                     f"and a reviewer confirms it (ideally with the brand). {FIXTURE_NOTE}"),
        ))
    return out


def fixture_results(biz: Business) -> list[ProviderResult]:
    """All simulated rows for one fixture business (for the seed)."""
    _require_fixture(biz)
    out: list[ProviderResult] = []
    if biz.gstin:
        out += [identity_result(biz), gst_result(biz)]
    out += brand_results(biz)
    return out


class SimulatedRegistryProvider:
    """Registry-like simulated rows; applicable ONLY to fixtures. Not in REGISTRY by default (the backend seeds
    fixture checks directly) but safe to include: it never runs for a real business."""
    name = "simulated_registry"
    dims = [Dim.identity, Dim.registration, Dim.distribution_authority]

    def applicable(self, biz: Business) -> bool:
        return biz.is_fixture

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify" or not biz.is_fixture:
            return []
        return fixture_results(biz)
