"""GST provider adapters (Cashfree, Setu) with HTTP mocked; contact provider wording with Firebase OTP."""
import httpx
import pytest
from sauda_verify.models import Address, Business, CheckStatus, SourceKind
from sauda_verify.providers import contact, gst_registry

ENV_KEYS = ("CASHFREE_CLIENT_ID", "CASHFREE_CLIENT_SECRET", "CASHFREE_ENV", "SETU_CLIENT_ID", "SETU_CLIENT_SECRET",
            "SETU_PRODUCT_INSTANCE_ID", "SETU_ENV", "AUTH_MODE", "CONTACT_OTP")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def biz(**kw):
    d = dict(bid="b", roles=["seller"], display_name="Infosys", legal_name="Infosys Limited", gstin="29AAACI4798L1ZU",
             address=Address(line="Electronics City", city="Bengaluru", state="Karnataka", pin="560100"))
    d.update(kw)
    return Business(**d)


CASHFREE_BODY = {
    "reference_id": 12345, "GSTIN": "29AAACI4798L1ZU", "legal_name_of_business": "INFOSYS LIMITED",
    "trade_name_of_business": "INFOSYS", "date_of_registration": "2017-07-01", "constitution_of_business": "Public Limited Company",
    "taxpayer_type": "Regular", "gst_in_status": "Active", "valid": True, "message": "GSTIN Exists",
    "principal_place_split_address": {"state": "Karnataka", "pincode": "560100", "city": "Bengaluru"},
}


class Resp:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def _capture(monkeypatch, body):
    calls = []

    def post(url, **kw):
        calls.append({"url": url, **kw})
        return Resp(body)

    monkeypatch.setattr(httpx, "post", post)
    return calls


def _cashfree(monkeypatch, env):
    monkeypatch.setenv("CASHFREE_CLIENT_ID", "cf-id")
    monkeypatch.setenv("CASHFREE_CLIENT_SECRET", "cf-secret")
    monkeypatch.setenv("CASHFREE_ENV", env)


def test_cashfree_sandbox_makes_real_call_but_never_verifies(monkeypatch):
    _cashfree(monkeypatch, "sandbox")
    calls = _capture(monkeypatch, CASHFREE_BODY)
    [r] = gst_registry.GstRegistryProvider().run(biz(), {"mode": "verify"})
    assert calls[0]["url"] == "https://sandbox.cashfree.com/verification/gstin"
    assert calls[0]["headers"]["x-client-id"] == "cf-id" and calls[0]["headers"]["x-client-secret"] == "cf-secret"
    assert calls[0]["json"] == {"GSTIN": "29AAACI4798L1ZU", "business_name": "Infosys Limited"}
    assert r.source_kind == SourceKind.authorised_provider
    assert r.source_name == "Cashfree GST verification (sandbox: sample data)"
    assert r.status == CheckStatus.inconclusive  # sandbox data never counts
    assert r.observed["sandbox"] is True and r.provider_ref == "12345"
    assert "cf-secret" not in r.model_dump_json()
    # a sandbox mismatch is not a finding either
    monkeypatch.setattr(httpx, "post", lambda url, **kw: Resp({**CASHFREE_BODY, "gst_in_status": "Cancelled"}))
    assert gst_registry.GstRegistryProvider().run(biz(), {})[0].status == CheckStatus.inconclusive


def test_cashfree_production_maps_to_verified_or_conflict(monkeypatch):
    _cashfree(monkeypatch, "production")
    calls = _capture(monkeypatch, CASHFREE_BODY)
    [r] = gst_registry.GstRegistryProvider().run(biz(), {})
    assert calls[0]["url"] == "https://api.cashfree.com/verification/gstin"
    assert r.status == CheckStatus.verified and r.source_name == "Cashfree GST verification"
    assert r.observed["status"] == "Active" and r.observed["pincode"] == "560100"
    monkeypatch.setattr(httpx, "post", lambda url, **kw: Resp({**CASHFREE_BODY, "gst_in_status": "Cancelled"}))
    assert gst_registry.GstRegistryProvider().run(biz(), {})[0].status == CheckStatus.conflict
    monkeypatch.setattr(httpx, "post", lambda url, **kw: Resp({"valid": False, "message": "GSTIN does not exist"}))
    assert gst_registry.GstRegistryProvider().run(biz(), {})[0].status == CheckStatus.inconclusive


def test_setu_sandbox_and_production(monkeypatch):
    monkeypatch.setenv("SETU_CLIENT_ID", "s-id")
    monkeypatch.setenv("SETU_CLIENT_SECRET", "s-secret")
    monkeypatch.setenv("SETU_PRODUCT_INSTANCE_ID", "s-pi")
    body = {"data": {"gstin": "27AAICB3918J1CT", "legalNameOfBusiness": "INFOSYS LIMITED", "tradeName": "INFOSYS",
                     "gstnStatus": "Active", "principalPlaceOfBusinessFields": {
                         "principalPlaceOfBusinessAddress": {"pincode": "560100", "stateName": "Karnataka"}}}}
    calls = _capture(monkeypatch, body)
    sample = biz(gstin="27AAICB3918J1CT")  # Setu's sandbox sample fails the local checksum; sandbox still calls
    [r] = gst_registry.GstRegistryProvider().run(sample, {})
    assert calls[0]["url"] == "https://dg-sandbox.setu.co/api/verify/gst"
    assert calls[0]["headers"]["x-product-instance-id"] == "s-pi"
    assert r.source_name == "Setu GST verification (sandbox: sample data)" and r.status == CheckStatus.inconclusive
    monkeypatch.setenv("SETU_ENV", "production")
    [r] = gst_registry.GstRegistryProvider().run(biz(), {})
    assert calls[-1]["url"] == "https://dg.setu.co/api/verify/gst"
    assert r.status == CheckStatus.verified and r.source_kind == SourceKind.authorised_provider


def test_no_credentials_means_no_call(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("no network call without credentials")

    monkeypatch.setattr(httpx, "post", boom)
    [r] = gst_registry.GstRegistryProvider().run(biz(), {})
    assert r.status == CheckStatus.pending and r.available is False


def test_contact_provider_points_to_firebase_otp(monkeypatch):
    b = biz(contact={"phone_masked": "••••••3210"})
    monkeypatch.setenv("AUTH_MODE", "firebase")
    rows = contact.ContactProvider().run(b, {})
    otp = rows[1]
    assert otp.check_type == "business_contact_otp" and otp.status == CheckStatus.pending and otp.available is True
    assert otp.source_name == "Firebase Authentication OTP" and "Verify business phone or email" in otp.summary
    assert "not configured" not in otp.summary
    monkeypatch.setenv("AUTH_MODE", "demo")
    assert "not configured" in contact.ContactProvider().run(b, {})[1].summary
