"""Registry adapters (manual tasks, MCA via data.gov.in mocked), contact/bank, simulated fixtures, REGISTRY."""
import pytest
from sauda_verify.models import Address, Business, CheckStatus, SourceKind
from sauda_verify.providers import (
    REGISTRY,
    SIMULATED,
    get,
    gst_registry,
    mca,
    simulated,
)
from sauda_verify.providers._registry import MANUAL_SUMMARY, DataGovUnavailable
from sauda_verify.providers.base import Provider


def biz(**kw):
    d = dict(bid="b", roles=["seller"], display_name="Infosys", legal_name="Infosys Limited", gstin="29AAACI4798L1ZU",
             cin_llpin="L85110KA1981PLC013115", udyam="UDYAM-TS-02-0012345", fssai="13619999000123",
             address=Address(line="Electronics City", city="Bengaluru", state="Karnataka", pin="560100"))
    d.update(kw)
    return Business(**d)


@pytest.fixture(autouse=True)
def no_creds(monkeypatch):
    for k in ("CASHFREE_CLIENT_ID", "CASHFREE_CLIENT_SECRET", "SETU_CLIENT_ID", "SETU_CLIENT_SECRET",
              "SETU_PRODUCT_INSTANCE_ID", "RAZORPAYX_KEY_ID", "RAZORPAYX_KEY_SECRET"):
        monkeypatch.delenv(k, raising=False)


def test_registry_is_ordered_and_conforms():
    names = [p.name for p in REGISTRY]
    assert names[:3] == ["gstin_format", "pincode_directory", "geocode"]
    assert {"documents", "photo", "gst_registry", "mca", "udyam", "fssai", "contact", "bank"} <= set(names)
    assert all(isinstance(p, Provider) for p in REGISTRY)
    assert "simulated_registry" not in names and get("geocode") is not None


def test_applicable_depends_on_declared_fields_and_type():
    bare = Business(bid="x", roles=["buyer"], display_name="Shop")
    app = {p.name for p in REGISTRY if p.applicable(bare)}
    assert not app & {"gstin_format", "pincode_directory", "geocode", "mca", "gst_registry", "udyam", "fssai", "bank"}
    assert "contact" in app
    full = {p.name for p in REGISTRY if p.applicable(biz())}
    assert {"gstin_format", "pincode_directory", "geocode", "mca", "gst_registry", "udyam", "fssai", "bank"} <= full


def test_gst_registry_manual_without_credentials():
    [r] = gst_registry.GstRegistryProvider().run(biz(), {"mode": "verify"})
    assert r.status == CheckStatus.pending and r.available is False
    assert r.summary.startswith(MANUAL_SUMMARY)
    assert r.source_url == "https://services.gst.gov.in/services/searchtp"
    m = r.observed["manual_check"]
    assert m["evidence_required"] and "legal_name" in m["reviewer_fields"]


def test_gst_registry_uses_authorised_client_when_configured(monkeypatch):
    monkeypatch.setenv("CASHFREE_CLIENT_ID", "id")
    monkeypatch.setenv("CASHFREE_CLIENT_SECRET", "s")
    monkeypatch.setenv("CASHFREE_ENV", "production")
    rec = {"legal_name": "INFOSYS LIMITED", "trade_name": "INFOSYS", "status": "Active", "pincode": "560100"}
    monkeypatch.setattr(gst_registry.CashfreeGstClient, "lookup", lambda self, g, **kw: rec)
    [r] = gst_registry.GstRegistryProvider().run(biz(), {})
    assert r.status == CheckStatus.verified and r.source_kind == SourceKind.authorised_provider
    rec["status"] = "Cancelled"
    assert gst_registry.GstRegistryProvider().run(biz(), {})[0].status == CheckStatus.conflict


@pytest.mark.parametrize("cls,url", [
    ("UdyamProvider", "udyamregistration.gov.in"), ("FssaiProvider", "foscos.fssai.gov.in")])
def test_udyam_fssai_format_plus_manual(cls, url):
    from sauda_verify.providers import fssai, udyam
    p = getattr(udyam if cls.startswith("U") else fssai, cls)()
    fmt, man = p.run(biz(), {})
    assert fmt.source_kind == SourceKind.preliminary_validation and fmt.status == CheckStatus.partially_verified
    assert "not confirmed with the registry" in fmt.summary
    assert man.status == CheckStatus.pending and url in man.source_url and man.summary.startswith(MANUAL_SUMMARY)
    bad = p.run(biz(udyam="UDYAM-TS-2-12345", fssai="3123"), {})
    assert bad[0].status == CheckStatus.failed and len(bad) == 1


def test_mca_lookup_match_and_outage(monkeypatch):
    rec = {"CIN": "L85110KA1981PLC013115", "CompanyName": "INFOSYS LIMITED", "CompanyStatus": "Active",
           "Registered_Office_Address": "ELECTRONICS CITY,HOSUR ROAD, BANGALORE,KARNATAKA,560100-India",
           "CompanyStateCode": "karnataka"}
    monkeypatch.setattr(mca, "datagov_get", lambda rid, params: {"updated_date": "2026-10-13T09:47:32Z", "records": [rec]})
    [r] = mca.McaProvider().run(biz(), {})
    assert r.status == CheckStatus.verified and r.source_kind == SourceKind.official_registry
    assert "2026-10-13" in r.source_name
    rec["CompanyStatus"] = "Strike Off"
    assert mca.McaProvider().run(biz(), {})[0].status == CheckStatus.conflict

    def boom(rid, params):
        raise DataGovUnavailable("HTTP 403")
    monkeypatch.setattr(mca, "datagov_get", boom)
    [r] = mca.McaProvider().run(biz(), {})
    assert r.status == CheckStatus.inconclusive and r.available is False and "manual_check" in r.observed
    monkeypatch.setattr(mca, "datagov_get", lambda rid, params: {"updated_date": "2026-10-13", "records": []})
    assert mca.McaProvider().run(biz(), {})[0].status == CheckStatus.inconclusive
    assert mca.McaProvider().run(biz(cin_llpin="AAB-1234"), {})[0].status == CheckStatus.pending
    assert mca.McaProvider().run(biz(cin_llpin="L851"), {})[0].status == CheckStatus.failed


def test_contact_and_bank_pending_never_verified():
    rows = get("contact").run(biz(contact={"phone_masked": "******1234"}), {})
    assert [r.check_type for r in rows] == ["representative_authority", "business_contact_otp"]
    assert all(r.status == CheckStatus.pending for r in rows)
    assert "does not establish authority" in rows[0].summary
    [b] = get("bank").run(biz(), {})
    assert b.status == CheckStatus.pending and b.available is False
    assert not get("bank").applicable(biz(roles=["buyer"]))


def test_registry_like_providers_skip_fixtures():
    fx = biz(is_fixture=True)
    for name in ("gst_registry", "mca"):
        assert not get(name).applicable(fx)
        assert get(name).run(fx, {"is_fixture": True}) == []
    rows = get("udyam").run(fx, {"is_fixture": True})
    assert [r.source_kind for r in rows] == [SourceKind.preliminary_validation]  # no manual registry task


def test_consent_false_gives_not_consented():
    for name in ("gst_registry", "mca", "udyam", "fssai"):
        key = get(name).consent_key
        [r] = get(name).run(biz(), {"consents": {key: False}})
        assert r.status == CheckStatus.pending and "consent" in r.summary


# ------------------------------------------------------------------ simulated fixtures
def fixture(bid):
    return Business(bid=bid, is_fixture=True, **simulated.DEMO_BUSINESSES[bid])


def test_simulated_only_for_fixtures():
    real = Business(bid="r", is_fixture=False, **simulated.DEMO_BUSINESSES["fx_sri_lakshmi"])
    assert not SIMULATED.applicable(real)
    assert SIMULATED.run(real, {}) == []
    with pytest.raises(ValueError):
        simulated.fixture_results(real)


def test_simulated_rows_are_labelled():
    for bid in simulated.DEMO_BUSINESSES:
        for r in SIMULATED.run(fixture(bid), {}):
            assert r.source_kind == SourceKind.simulated_fixture
            assert "fixture" in r.source_name.lower() and "simulated" in r.summary.lower()


def test_demo_scenario_outcomes():
    sl = {r.check_type: r for r in SIMULATED.run(fixture("fx_sri_lakshmi"), {})}
    assert sl["gst_registry"].status == CheckStatus.partially_verified
    assert sl["gst_registry"].source_name == "Simulated GST registry (demo fixture)"
    assert any(f.field == "trade_name" and f.observed == "SRI LAXMI GENERAL STORE" and f.match is None
               for f in sl["gst_registry"].fields)
    an = {r.check_type: r.status for r in SIMULATED.run(fixture("fx_annapurna_rice"), {})}
    assert an == {"gst_legal_name": CheckStatus.verified, "gst_registry": CheckStatus.verified}
    dc = {r.check_type: r.status for r in SIMULATED.run(fixture("fx_deccan_oils"), {})}
    assert dc["brand_authorisation"] == CheckStatus.pending and dc["gst_registry"] == CheckStatus.verified


def test_fixture_gstins_pass_real_format_check():
    from sauda_verify.providers import gstin
    for g in simulated.FIXTURE_GST:
        assert gstin.parse(g)["valid"]
