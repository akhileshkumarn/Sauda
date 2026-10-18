"""Role switch (buyer and/or seller) and business contact verification with a Firebase one-time code."""
import time
from types import SimpleNamespace

import pytest
from sauda_verify import policy
from sauda_verify.models import Business, Check, CheckStatus, Dim, SourceKind
from sauda_verify.providers.bank import BankProvider
from test_verify_routes import FakeGst, auth, mk, tn  # noqa: F401  (tn: shared route fixture)

RAW_PHONE = "9876543210"
RAW_EMAIL = "owner.business@example.com"


@pytest.fixture
def rc(tn, monkeypatch):  # noqa: F811
    from buyer_agent import trust_network_routes as r

    monkeypatch.setattr(r, "_providers", lambda: [FakeGst(), BankProvider()])
    r._contact_hits.clear()
    return tn


def _patch_roles(env, bid, uid, roles):
    cur = env.client.get(f"/tn/businesses/{bid}", headers=auth(uid)).json()
    return env.client.patch(f"/tn/businesses/{bid}", json={"version": cur["version"], "roles": roles}, headers=auth(uid))


# ---------------------------------------------------------------- role switch
def test_add_seller_role_reuses_identity_checks_and_adds_seller_checks(rc):
    bid = mk(rc, "alice", brand_claims=["Fortune"]).json()["bid"]
    assert rc.client.post(f"/tn/businesses/{bid}/verify", json={}, headers=auth("alice")).status_code == 200
    gst_calls = FakeGst.calls
    before = {c["check_id"] for c in rc.client.get(f"/tn/businesses/{bid}/checks", headers=auth("alice")).json()}

    r = _patch_roles(rc, bid, "alice", ["buyer", "seller"])
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["roles"] == ["buyer", "seller"]
    rc_ = out["role_change"]
    assert rc_["added"] == ["seller"] and rc_["removed"] == []
    assert FakeGst.calls == gst_calls  # identity / registration are not re-verified
    types = {c["check_type"] for c in rc_["new_checks"]}
    assert "bank_account_validation" in types
    assert all(c["status"] == "pending" for c in rc_["new_checks"])
    assert rc_["listing_eligibility"]["can_list"] is True
    after = {c["check_id"] for c in rc.client.get(f"/tn/businesses/{bid}/checks", headers=auth("alice")).json()}
    assert before <= after  # nothing removed
    assert "tn.business.role_added" in rc.ledger.types(f"biz-{bid}")

    # idempotent: removing and adding again creates no new seller rows
    assert _patch_roles(rc, bid, "alice", ["buyer"]).status_code == 200
    again = _patch_roles(rc, bid, "alice", ["buyer", "seller"]).json()["role_change"]
    assert {c["check_id"] for c in again["new_checks"]} == {c["check_id"] for c in rc_["new_checks"]}
    assert "tn.business.role_removed" in rc.ledger.types(f"biz-{bid}")


def test_brand_claim_checked_when_seller_added(rc):
    bid = mk(rc, "alice", brand_claims=["Fortune"]).json()["bid"]
    out = _patch_roles(rc, bid, "alice", ["buyer", "seller"]).json()["role_change"]
    assert "brand_authorisation_claim" in {c["check_type"] for c in out["new_checks"]}


def test_role_switch_members_only_and_versioned(rc):
    bid = mk(rc, "alice").json()["bid"]
    v = rc.client.get(f"/tn/businesses/{bid}", headers=auth("alice")).json()["version"]
    assert rc.client.patch(f"/tn/businesses/{bid}", json={"version": v, "roles": ["seller"]}, headers=auth("eve")).status_code == 404
    stale = rc.client.patch(f"/tn/businesses/{bid}", json={"version": v + 5, "roles": ["buyer", "seller"]}, headers=auth("alice"))
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    empty = rc.client.patch(f"/tn/businesses/{bid}", json={"version": v, "roles": []}, headers=auth("alice"))
    assert empty.status_code == 422


def test_remove_role_blocked_when_relationships_depend_on_it(rc):
    buyer = mk(rc, "alice").json()["bid"]
    seller = mk(rc, "sam", name="Sam Wholesale", roles=["seller"], gstin="36CCCCC0000C1Z5", pin="500030").json()["bid"]
    inv = rc.client.post("/tn/invitations", json={"from_bid": buyer, "role_invited": "seller", "contact": "sam.w@example.com",
                                                  "categories": ["rice"]}, headers=auth("alice")).json()
    assert rc.client.post(f"/tn/invitations/{inv['token']}/accept", json={"bid": seller}, headers=auth("sam")).status_code == 200
    # the seller adds buying, then cannot drop selling while the relationship is active
    assert _patch_roles(rc, seller, "sam", ["buyer", "seller"]).status_code == 200
    r = _patch_roles(rc, seller, "sam", ["buyer"])
    assert r.status_code == 409 and r.json()["code"] == "role_in_use" and r.json()["role"] == "seller"
    assert r.json()["relationships"]
    r2 = _patch_roles(rc, buyer, "alice", ["seller"])
    assert r2.status_code == 409 and r2.json()["role"] == "buyer"


# ---------------------------------------------------------------- contact verification
@pytest.fixture
def fb(monkeypatch):
    """Mocks firebase_admin.auth for the secondary (temporary) sign-in."""
    from buyer_agent import trust_network_routes as r
    from firebase_admin import auth as fb_auth

    state = SimpleNamespace(claims={}, deleted=[], providers=["phone"], created_ms=time.time() * 1000)

    def verify(token, app=None, **kw):
        if token.startswith("bad"):
            raise ValueError("invalid token")
        return dict(state.claims)

    monkeypatch.setattr(r, "_contact_fb_app", lambda: None)
    monkeypatch.setattr(fb_auth, "verify_id_token", verify)
    monkeypatch.setattr(fb_auth, "get_user", lambda uid, app=None: SimpleNamespace(
        uid=uid, provider_data=[SimpleNamespace(provider_id=p) for p in state.providers],
        user_metadata=SimpleNamespace(creation_timestamp=state.created_ms)))
    monkeypatch.setattr(fb_auth, "delete_user", lambda uid, app=None: state.deleted.append(uid))
    return state


def _phone_claims(phone=f"+91{RAW_PHONE}"):
    return {"uid": "tmp-phone-1", "phone_number": phone, "auth_time": int(time.time()),
            "firebase": {"sign_in_provider": "phone"}}


def _email_claims(email=RAW_EMAIL, verified=True):
    return {"uid": "tmp-email-1", "email": email, "email_verified": verified, "auth_time": int(time.time()),
            "firebase": {"sign_in_provider": "emailLink"}}


def _verify(env, bid, kind, uid="alice", token="tok-" + "x" * 30):
    return env.client.post(f"/tn/businesses/{bid}/contact/verify", json={"kind": kind, "id_token": token}, headers=auth(uid))


def _no_raw(env):
    blob = repr(env.db.data.get("tn_checks")) + repr(env.db.data.get("tn_businesses")) + repr(env.ledger.__dict__)
    assert RAW_PHONE not in blob and RAW_EMAIL not in blob


def test_phone_otp_success_matches_declared_and_deletes_temp_user(rc, fb):
    bid = mk(rc, "alice").json()["bid"]  # declared phone +91 98765 43210
    fb.claims = _phone_claims()
    r = _verify(rc, bid, "phone")
    assert r.status_code == 200, r.text
    out = r.json()
    c = out["check"]
    assert c["dim"] == "representative" and c["check_type"] == "business_contact_otp"
    assert c["source_kind"] == "authorised_provider" and c["source_name"] == "Firebase Authentication OTP"
    assert c["status"] == "partially_verified"
    assert c["summary"].startswith("Controls the business phone ••••••3210. This shows access to the business contact, "
                                   "not legal authority to act for the business.")
    assert "matches the phone declared" in c["summary"]
    assert out["contact"] == {"kind": "phone", "masked": "••••••3210", "declared_match": True, "document_match": None}
    assert fb.deleted == ["tmp-phone-1"]
    assert "tn.contact.verified" in rc.ledger.types(f"biz-{bid}")
    _no_raw(rc)
    # stored: keyed hash + masked only
    [stored] = [x for x in rc.db.data["tn_checks"].values() if x["check_type"] == "business_contact_otp" and x["business_id"] == bid
                and x["status"] == "partially_verified"]
    assert stored["observed"]["masked"] == "••••••3210" and len(stored["observed"]["contact_hash"]) == 64
    listed = rc.client.get(f"/tn/businesses/{bid}/checks", headers=auth("alice")).json()
    assert all("contact_hash" not in (x.get("observed") or {}) for x in listed)


def test_email_otp_success(rc, fb):
    bid = mk(rc, "alice", email=RAW_EMAIL).json()["bid"]
    fb.claims = _email_claims(email=RAW_EMAIL.upper())
    fb.providers = ["password"]
    r = _verify(rc, bid, "email")
    assert r.status_code == 200, r.text
    assert r.json()["check"]["status"] == "partially_verified"
    assert r.json()["contact"]["masked"] == "o••••@example.com" and r.json()["contact"]["declared_match"] is True
    assert fb.deleted == ["tmp-email-1"]
    _no_raw(rc)


def test_email_not_verified_rejected(rc, fb):
    bid = mk(rc, "alice").json()["bid"]
    fb.claims = _email_claims(verified=False)
    r = _verify(rc, bid, "email")
    assert r.status_code == 422 and r.json()["code"] == "email_not_verified"
    assert not [x for x in rc.db.data.get("tn_checks", {}).values() if x.get("source_name") == "Firebase Authentication OTP"]


def test_bad_token_kind_mismatch_and_members_only(rc, fb):
    bid = mk(rc, "alice").json()["bid"]
    fb.claims = _phone_claims()
    assert _verify(rc, bid, "phone", token="bad-" + "x" * 30).json()["code"] == "invalid_contact_token"
    assert _verify(rc, bid, "email").json()["code"] == "contact_missing"  # a phone sign-in cannot confirm an email
    assert _verify(rc, bid, "phone", uid="eve").status_code == 404
    fb.claims = {**_phone_claims(), "auth_time": int(time.time()) - 3600}
    assert _verify(rc, bid, "phone").json()["code"] == "invalid_contact_token"


def test_mismatch_with_declared_is_inconclusive_and_reviewed(rc, fb):
    bid = mk(rc, "alice").json()["bid"]
    fb.claims = _phone_claims("+919123456789")
    out = _verify(rc, bid, "phone").json()
    assert out["check"]["status"] == "inconclusive" and out["contact"]["declared_match"] is False
    assert "differs from the declared phone" in out["check"]["summary"]
    assert "field_mismatch" in out["summary"]["review_reasons"]


def test_existing_account_is_never_deleted(rc, fb):
    bid = mk(rc, "alice").json()["bid"]
    fb.claims = _phone_claims()
    fb.providers = ["phone", "google.com"]  # the number belongs to an existing account with another sign-in method
    assert _verify(rc, bid, "phone").json()["temp_user"] == "kept_existing_account"
    fb.providers, fb.created_ms = ["phone"], (time.time() - 86400 * 30) * 1000  # an old account
    assert _verify(rc, bid, "phone").json()["temp_user"] == "kept_existing_account"
    fb.claims = {**_phone_claims(), "uid": "alice"}  # the owner's own account
    assert _verify(rc, bid, "phone").json()["temp_user"] == "kept_owner_account"
    assert fb.deleted == []


def test_contact_rate_limit_five_an_hour(rc, fb):
    bid = mk(rc, "alice").json()["bid"]
    fb.claims = _email_claims(verified=False)
    codes = [_verify(rc, bid, "email").status_code for _ in range(6)]
    assert codes[:5] == [422] * 5 and codes[5] == 429
    other = mk(rc, "bob", name="Other Shop", gstin=None, pin="500017").json()["bid"]
    assert _verify(rc, other, "email", uid="bob").status_code == 422  # per business


def test_contact_otp_never_makes_representative_verified(rc, fb):
    bid = mk(rc, "alice").json()["bid"]
    fb.claims = _phone_claims()
    s = _verify(rc, bid, "phone").json()["summary"]
    rep = next(d for d in s["dimensions"] if d["dim"] == "representative")
    assert rep["status"] == "partially_verified"
    assert "representative_authority_unknown" in s["review_reasons"]


# ---------------------------------------------------------------- policy rule
def _chk(**kw):
    base = dict(check_id="c", business_id="b", case_id="k", dim=Dim.representative, check_type="business_contact_otp",
                source_kind=SourceKind.authorised_provider, source_name="Firebase Authentication OTP",
                status=CheckStatus.partially_verified, summary="Controls the business phone", checked_at="2026-10-18T10:00:00+00:00")
    return Check(**{**base, **kw})


def test_policy_contact_otp_alone_never_verifies_representative():
    biz = Business(bid="b", display_name="X", roles=["buyer"])
    for st in (CheckStatus.partially_verified, CheckStatus.verified):  # even a mislabelled 'verified' row is capped
        dims = policy.dimensions([_chk(status=st)], biz)
        rep = dims[Dim.representative]
        assert rep.status == CheckStatus.partially_verified
        assert not policy.satisfies(rep)
        assert "representative_authority_unknown" in policy.review_reasons([_chk(status=st)], biz)
        r = policy.readiness("large_order", None, [_chk(status=st)], biz, relationship_reviewed=True)
        assert "representative" in r.missing
    # a reviewer's confirmation still wins
    reviewed = _chk(check_id="r", check_type="review_decision", source_kind=SourceKind.human_review, status=CheckStatus.verified,
                    checked_at="2026-10-18T11:00:00+00:00")
    rep = policy.dimensions([_chk(), reviewed], biz)[Dim.representative]
    assert rep.status == CheckStatus.verified and policy.satisfies(rep)
    # an uploaded authorisation document is not hidden behind the contact code
    doc = _chk(check_id="d", check_type="document_authorisation_letter", source_kind=SourceKind.uploaded_evidence)
    rep = policy.dimensions([_chk(), doc], biz)[Dim.representative]
    assert rep.check_type == "document_authorisation_letter" and policy.satisfies(rep)
