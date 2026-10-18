"""Trust Network API: auth and access isolation, idempotency, invitations, relationships, review decisions."""
import pytest
from sauda_verify.models import CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers.base import ProviderResult

OP = {"Authorization": "Bearer op-token-for-tests"}


def auth(uid):
    return {"Authorization": f"Bearer uid-{uid}"}


class FakeGst:
    name = "gst_registry"
    dims = [Dim.registration, Dim.identity]
    calls = 0

    def applicable(self, biz):
        return bool(biz.gstin)

    def run(self, biz, ctx):
        FakeGst.calls += 1
        name_ok = (biz.legal_name or biz.display_name) == "Ravi Stores"
        return [
            ProviderResult(status=CheckStatus.verified, source_kind=SourceKind.authorised_provider, source_name="GST provider",
                           summary="GST registration active", observed={"registration_status": "Active"}, dim=Dim.registration),
            ProviderResult(status=CheckStatus.verified if name_ok else CheckStatus.partially_verified,
                           source_kind=SourceKind.authorised_provider, source_name="GST provider", summary="Name compared",
                           fields=[FieldCompare(field="legal_name", declared=biz.legal_name, observed="Ravi Stores", match=name_ok)],
                           dim=Dim.identity),
        ]


class Boom:
    name = "udyam"
    dims = [Dim.registration]

    def applicable(self, biz):
        return True

    def run(self, biz, ctx):
        raise RuntimeError("upstream down")


@pytest.fixture
def tn(env, monkeypatch):
    from buyer_agent import deps
    from buyer_agent import trust_network_routes as r

    monkeypatch.setenv("REVIEWER_UIDS", "rita")
    deps.settings.cache_clear()
    FakeGst.calls = 0
    monkeypatch.setattr(r, "_providers", lambda: [FakeGst(), Boom()])
    uploads = {}
    monkeypatch.setattr(r, "_gcs_put", lambda bucket, path, data, mime: uploads.__setitem__(path, data))
    monkeypatch.setattr(r, "_gcs_signed_url", lambda bucket, path: f"https://signed.example/{path}")
    monkeypatch.setattr(r, "_screen", lambda text: {"blocked": "IGNORE PREVIOUS" in text, "categories": []})
    env.uploads = uploads
    return env


def mk(env, uid, name="Ravi Stores", roles=("buyer",), gstin="36AAAAA0000A1Z5", pin="500016", **kw):
    body = {"roles": list(roles), "display_name": name, "legal_name": name, "gstin": gstin,
            "address": {"line": "1 Road", "city": "Hyderabad", "state": "Telangana", "pin": pin},
            "representative": {"name": "Owner", "role": "Proprietor"}, "phone": "+91 98765 43210", **kw}
    return env.client.post("/tn/businesses", json=body, headers=auth(uid))


# ---------------------------------------------------------------- businesses
def test_create_requires_auth_and_masks_contact(tn):
    assert tn.client.post("/tn/businesses", json={"roles": ["buyer"], "display_name": "X"}).status_code == 401
    r = mk(tn, "alice")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["members"] == ["alice"] and b["contact"]["phone_masked"] == "••••••3210"
    assert "9876543210" not in r.text and "contact_hash" not in b
    assert tn.ledger.types(f"biz-{b['bid']}") == ["tn.business.created"]


def test_duplicate_detection(tn):
    assert mk(tn, "alice").status_code == 200
    r = mk(tn, "bob", name="Other Name", gstin="36aaaaa0000a1z5")
    assert r.status_code == 409 and r.json()["code"] == "possible_duplicate"
    cand = r.json()["candidates"][0]
    assert set(cand) == {"bid", "display_name", "city", "gstin_masked"}
    r2 = mk(tn, "bob", name="M/s Ravi Stores", gstin=None)  # same name + PIN
    assert r2.status_code == 409
    assert mk(tn, "bob", name="Ravi Stores", gstin=None, pin="500017").status_code == 200
    assert mk(tn, "bob", gstin="36AAAAA0000A1Z5", confirm_not_duplicate=True).json()["code"] == "gstin_already_registered"


def test_non_member_cannot_read_full_profile(tn):
    bid = mk(tn, "alice").json()["bid"]
    assert tn.client.get(f"/tn/businesses/{bid}", headers=auth("alice")).status_code == 200
    assert tn.client.get(f"/tn/businesses/{bid}", headers=auth("mallory")).status_code == 404
    assert tn.client.get(f"/tn/businesses/{bid}/profile", headers=auth("mallory")).status_code == 404
    assert tn.client.get(f"/tn/businesses/{bid}/summary", headers=auth("mallory")).status_code == 404
    assert tn.client.get(f"/tn/businesses/{bid}", headers=auth("rita")).status_code == 200  # reviewer
    assert tn.client.get(f"/tn/businesses/{bid}", headers=OP).status_code == 200
    mine = tn.client.get("/tn/businesses/mine", headers=auth("mallory")).json()
    assert mine == []


def test_patch_optimistic_concurrency(tn):
    b = mk(tn, "alice").json()
    r = tn.client.patch(f"/tn/businesses/{b['bid']}", json={"version": 1, "category": "Kirana"}, headers=auth("alice"))
    assert r.status_code == 200 and r.json()["version"] == 2
    stale = tn.client.patch(f"/tn/businesses/{b['bid']}", json={"version": 1, "category": "X"}, headers=auth("alice"))
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    assert tn.client.patch(f"/tn/businesses/{b['bid']}", json={"version": 2, "category": "X"}, headers=auth("mallory")).status_code == 404
    assert tn.client.patch(f"/tn/businesses/{b['bid']}", json={"version": 2, "members": ["mallory"]}, headers=auth("alice")).json().get("members") == ["alice"]


def test_verify_idempotent_and_source_unavailable(tn):
    bid = mk(tn, "alice").json()["bid"]
    r = tn.client.post(f"/tn/businesses/{bid}/verify", json={"consents": {"gst": True}}, headers=auth("alice"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert not j["idempotent"]
    kinds = {(c["dim"], c["source_kind"], c["status"], c["available"]) for c in j["checks"]}
    assert ("registration", "authorised_provider", "verified", True) in kinds
    assert ("registration", "preliminary_validation", "inconclusive", False) in kinds  # the failing source
    assert j["summary"]["category"] == "identity_confirmed"
    assert "source_unavailable" in j["summary"]["review_reasons"]
    again = tn.client.post(f"/tn/businesses/{bid}/verify", json={"consents": {"gst": True}}, headers=auth("alice")).json()
    assert again["idempotent"] and again["case"]["case_id"] == j["case"]["case_id"] and FakeGst.calls == 1
    assert tn.client.post(f"/tn/businesses/{bid}/verify", json={"consents": {}}, headers=auth("mallory")).status_code == 404
    assert "tn.verify.run" in tn.ledger.types(f"biz-{bid}")


def test_fixture_business_never_gets_registry_source(tn):
    from buyer_agent import trust_network_routes as r

    tn.client.post("/tn/fixtures/seed", headers=OP)
    b = tn.db.collection("tn_businesses").document("fx_seller_annapurna").get().to_dict()
    rows = r.run_providers(b, "case_x", {})
    assert rows and all(c["source_kind"] != "authorised_provider" for c in rows if c["available"])


# ---------------------------------------------------------------- evidence
def test_evidence_upload_dedupe_and_reuse_flag(tn):
    a = mk(tn, "alice").json()["bid"]
    b = mk(tn, "bob", name="Bob Mart", gstin="36BBBBB0000B1Z5", pin="500020").json()["bid"]
    files = {"file": ("gst.pdf", b"%PDF-1.4 certificate", "application/pdf")}
    r = tn.client.post(f"/tn/businesses/{a}/evidence", files=files, data={"type": "gst_certificate"}, headers=auth("alice"))
    assert r.status_code == 200, r.text
    eid = r.json()["evidence"]["eid"]
    assert f"tn/{a}/{eid}" in tn.uploads and r.json()["checks"][0]["status"] == "pending"
    again = tn.client.post(f"/tn/businesses/{a}/evidence", files=files, data={"type": "gst_certificate"}, headers=auth("alice")).json()
    assert again["deduplicated"] and again["evidence"]["eid"] == eid
    other = tn.client.post(f"/tn/businesses/{b}/evidence", files=files, data={"type": "gst_certificate"}, headers=auth("bob")).json()
    assert other["evidence"]["reused_by_other_business"]
    assert any(c["status"] == "conflict" for c in other["checks"])
    s = tn.client.get(f"/tn/businesses/{b}/summary", headers=auth("bob")).json()
    assert "suspicious_document" in s["review_reasons"]
    assert tn.client.get(f"/tn/evidence/{eid}/url", headers=auth("alice")).json()["url"].startswith("https://signed.example/")
    assert tn.client.get(f"/tn/evidence/{eid}/url", headers=auth("bob")).status_code == 404
    assert tn.client.get(f"/tn/evidence/{eid}/url", headers=auth("rita")).status_code == 200
    bad = tn.client.post(f"/tn/businesses/{a}/evidence", files={"file": ("x.exe", b"MZ", "application/x-msdownload")},
                         data={"type": "gst_certificate"}, headers=auth("alice"))
    assert bad.status_code == 415


def test_location_requires_consent(tn):
    a = mk(tn, "alice").json()["bid"]
    assert tn.client.post(f"/tn/businesses/{a}/location", json={"lat": 17.4, "lng": 78.4, "consent": False}, headers=auth("alice")).status_code == 422
    r = tn.client.post(f"/tn/businesses/{a}/location", json={"lat": 17.4, "lng": 78.4, "accuracy_m": 20, "consent": True}, headers=auth("alice"))
    assert r.status_code == 200 and r.json()["checks"][0]["source_kind"] == "device_signal"


# ---------------------------------------------------------------- invitations + relationships
def _pair(tn):
    buyer = mk(tn, "alice").json()["bid"]
    seller = mk(tn, "sam", name="Sam Wholesale", roles=["seller"], gstin="36CCCCC0000C1Z5", pin="500030").json()["bid"]
    inv = tn.client.post("/tn/invitations", json={"from_bid": buyer, "role_invited": "seller", "contact": "sam.w@example.com",
                                                  "categories": ["rice"]}, headers=auth("alice"))
    assert inv.status_code == 200, inv.text
    return buyer, seller, inv.json()


def test_invitation_token_once_and_duplicates(tn):
    buyer, seller, inv = _pair(tn)
    token = inv["token"]
    assert token and inv["share_link"].endswith(token) and inv["invitation"]["contact_masked"] == "s••••@example.com"
    stored = tn.db.collection("tn_invitations").document(inv["invitation"]["iid"]).get().to_dict()
    assert token not in str(stored) and "sam.w@example.com" not in str(stored)
    dup = tn.client.post("/tn/invitations", json={"from_bid": buyer, "role_invited": "seller", "contact": "SAM.W@example.com"},
                         headers=auth("alice")).json()
    assert dup["duplicate"] and dup["token"] is None and dup["invitation"]["iid"] == inv["invitation"]["iid"]
    assert len(tn.db.data["tn_invitations"]) == 1
    assert tn.client.post("/tn/invitations", json={"from_bid": buyer, "role_invited": "seller", "contact": "x@example.com"},
                          headers=auth("mallory")).status_code == 404
    pub = tn.client.get(f"/tn/invitations/{token}").json()
    assert pub["inviter_display_name"] == "Ravi Stores" and pub["role_invited"] == "seller" and "contact" not in str(pub)
    assert tn.client.get("/tn/invitations/not-a-token").status_code == 404
    assert "sam.w@example.com" not in str(tn.ledger.chains)


def test_counterparty_gets_redacted_profile_only_with_relationship(tn):
    buyer, seller, inv = _pair(tn)
    assert tn.client.get(f"/tn/businesses/{buyer}/profile", headers=auth("sam")).status_code == 404
    acc = tn.client.post(f"/tn/invitations/{inv['token']}/accept", json={"bid": seller}, headers=auth("sam"))
    assert acc.status_code == 200, acc.text
    rel = acc.json()["relationship"]
    assert rel["state"] == "onboarding" and [h["to"] for h in rel["history"]] == ["invited", "accepted", "onboarding"]
    p = tn.client.get(f"/tn/businesses/{buyer}/profile", headers=auth("sam"))
    assert p.status_code == 200 and p.json()["redacted"]
    body = p.text
    assert "36AAAAA0000A1Z5" not in body and "members" not in body and "contact" not in body and "1 Road" not in body
    assert p.json()["pin_prefix"] == "500xxx"
    assert tn.client.get(f"/tn/businesses/{buyer}", headers=auth("sam")).status_code == 404
    again = tn.client.post(f"/tn/invitations/{inv['token']}/accept", json={"bid": seller}, headers=auth("sam")).json()
    assert again["idempotent"]
    assert tn.client.post(f"/tn/invitations/{inv['token']}/accept", json={"bid": seller}, headers=auth("mallory")).status_code == 404


def test_relationship_transitions_and_readiness(tn):
    buyer, seller, inv = _pair(tn)
    rid = tn.client.post(f"/tn/invitations/{inv['token']}/accept", json={"bid": seller}, headers=auth("sam")).json()["relationship"]["rid"]
    # buyer cannot approve on the seller's behalf
    r = tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "approve_for_trading", "reason": "looks fine"}, headers=auth("alice"))
    assert r.status_code == 403
    # no checks yet: requirements not met
    r = tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "approve_for_trading", "reason": "looks fine"}, headers=auth("sam"))
    assert r.status_code == 409 and r.json()["code"] == "requirements_not_met" and "identity" in r.json()["missing"]
    tn.client.post(f"/tn/businesses/{buyer}/verify", json={"consents": {"gst": True}}, headers=auth("alice"))
    r = tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "approve_for_trading", "reason": "prepaid only", "tier": "credit"},
                       headers=auth("sam"))
    assert r.status_code == 409 and r.json()["code"] == "human_review_required"
    r = tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "approve_for_trading", "reason": "prepaid only"}, headers=auth("sam"))
    assert r.status_code == 200, r.text
    rel = r.json()["relationship"]
    assert rel["state"] == "approved_for_trading" and rel["approved_tiers"] == ["prepaid_small"]
    assert [h["to"] for h in rel["history"]][-2:] == ["under_review", "approved_for_trading"]
    lst = tn.client.get(f"/tn/relationships?bid={seller}", headers=auth("sam")).json()
    assert lst[0]["readiness"]["prepaid_small"]["ready"] and not lst[0]["readiness"]["credit"]["ready"]
    assert tn.client.get(f"/tn/relationships?bid={seller}", headers=auth("mallory")).status_code == 404
    assert tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "pause", "reason": "stock check"}, headers=auth("alice")).json()["relationship"]["state"] == "paused"
    assert tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "decline", "reason": "closed"}, headers=auth("sam")).status_code == 200
    r = tn.client.post(f"/tn/relationships/{rid}/decision", json={"action": "resume", "reason": "again"}, headers=auth("sam"))
    assert r.status_code == 409 and r.json()["code"] == "invalid_transition"
    # declined relationships no longer open the profile
    assert tn.client.get(f"/tn/businesses/{buyer}/profile", headers=auth("sam")).status_code == 404
    assert "tn.relationship.decision" in tn.ledger.types(f"biz-{buyer}")


def test_transition_table():
    from buyer_agent.trust_network_routes import TRANSITIONS, can_transition

    assert can_transition("invited", "accepted") and not can_transition("invited", "approved_for_trading")
    assert not can_transition("declined", "under_review") and TRANSITIONS["declined"] == set()
    assert not can_transition("onboarding", "approved_for_trading")


# ---------------------------------------------------------------- review
def test_review_queue_reviewers_only_and_reason_required(tn):
    bid = mk(tn, "alice", legal_name="Ravi Store").json()["bid"]
    tn.client.post(f"/tn/businesses/{bid}/verify", json={"consents": {"gst": True}}, headers=auth("alice"))
    assert tn.client.get("/review/queue", headers=auth("alice")).status_code == 403
    q = tn.client.get("/review/queue", headers=auth("rita")).json()
    assert q and q[0]["bid"] == bid and "field_mismatch" in q[0]["reasons"]
    tid = q[0]["tid"]
    assert tn.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity"}, headers=auth("rita")).status_code == 422
    assert tn.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity", "reason": "  "},
                          headers=auth("rita")).status_code == 422
    assert tn.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity", "reason": "spelling variant"},
                          headers=auth("alice")).status_code == 403
    r = tn.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity",
                                                              "reason": "Certificate shows the same proprietor; spelling variant"}, headers=auth("rita"))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["task"]["decisions"][-1]["reason"].startswith("Certificate") and "reviewer_hash" in j["task"]["decisions"][-1]
    assert "field_mismatch" not in j["task"]["reasons"]
    assert j["checks"][0]["source_kind"] == "human_review" and j["checks"][0]["reviewer"]["decision"] == "approve_identity"
    assert "tn.review.decision" in tn.ledger.types(f"biz-{bid}")
    detail = tn.client.get(f"/review/tasks/{tid}", headers=auth("rita")).json()
    assert detail["task"]["decisions"] and detail["checks"]


def test_reviewer_identity_approval_does_not_approve_relationship(tn):
    from buyer_agent import trust_network_routes as r

    tn.client.post("/tn/fixtures/seed", headers=OP)
    tid = "rv_fx_buyer_srilakshmi"
    tn.client.post(f"/review/tasks/{tid}/decision", json={"action": "approve_identity", "scope": "identity", "reason": "Name spelling variant"},
                   headers=OP)
    rel = [x for x in tn.db.data["tn_relationships"].values() if x["seller_bid"] == r.FX_METRO][0]
    assert rel["state"] == "accepted" and rel["approved_tiers"] == []
    s = tn.client.get(f"/tn/businesses/{r.FX_BUYER}/summary", headers=OP).json()
    assert s["category"] != "additional_review_required" or "identity" not in [d["dim"] for d in s["dimensions"] if d["status"] != "verified"]
    dims = {d["dim"]: d for d in s["dimensions"]}
    assert dims["identity"]["source_kind"] == "human_review"


def test_reject_claim_makes_unsuccessful(tn):
    bid = mk(tn, "alice").json()["bid"]
    v = tn.client.post(f"/tn/businesses/{bid}/verify", json={"consents": {"gst": True}}, headers=auth("alice")).json()
    reg = next(c for c in v["checks"] if c["dim"] == "registration" and c["available"])
    tid = f"rv_{bid}"
    r = tn.client.post(f"/review/tasks/{tid}/decision", json={"action": "reject_claim", "scope": f"claim:{reg['check_id']}",
                                                              "reason": "Certificate belongs to a different business"}, headers=auth("rita"))
    assert r.status_code == 200 and r.json()["task"]["status"] == "rejected"
    assert r.json()["summary"]["category"] == "verification_unsuccessful"
    for a in ("request_evidence", "escalate"):
        x = tn.client.post(f"/review/tasks/{tid}/decision", json={"action": a, "scope": "identity", "reason": "need more"}, headers=auth("rita"))
        assert x.json()["task"]["status"] == {"request_evidence": "needs_evidence", "escalate": "escalated"}[a]
    assert len(tn.client.get(f"/review/tasks/{tid}", headers=auth("rita")).json()["task"]["decisions"]) == 3


# ---------------------------------------------------------------- fixtures + act-as
def test_seed_operator_only_and_idempotent(tn):
    assert tn.client.post("/tn/fixtures/seed", headers=auth("alice")).status_code == 403
    a = tn.client.post("/tn/fixtures/seed", headers=OP).json()
    assert a["created"]["businesses"] == 6 and a["created"]["relationships"] == 1
    counts = {k: len(v) for k, v in tn.db.data.items() if k.startswith("tn_")}
    b = tn.client.post("/tn/fixtures/seed", headers=OP).json()
    assert b["created"] == {"businesses": 0, "checks": 0, "reviews": 0, "relationships": 0}
    assert counts == {k: len(v) for k, v in tn.db.data.items() if k.startswith("tn_")}
    assert all(x["is_fixture"] for x in tn.db.data["tn_businesses"].values())
    assert all(c["source_kind"] in ("simulated_fixture", "preliminary_validation", "device_signal", "self_declared")
               for c in tn.db.data["tn_checks"].values())
    q = {t["tid"]: t for t in tn.client.get("/review/queue", headers=OP).json()}
    assert {"field_mismatch", "representative_authority_unknown"} <= set(q["rv_fx_buyer_srilakshmi"]["reasons"])
    assert "brand_authorisation_unconfirmed" in q["rv_fx_seller_deccan"]["reasons"]
    c = tn.client.post("/tn/fixtures/seed?reset=true", headers=OP).json()
    assert c["removed"] > 0 and c["created"]["businesses"] == 6


def test_act_as_fixture_users_only(tn):
    tn.client.post("/tn/fixtures/seed", headers=OP)
    h = {**OP, "X-Act-As": "fx-user-srilakshmi"}
    assert tn.client.get("/tn/businesses/fx_buyer_srilakshmi", headers=h).status_code == 200
    assert tn.client.get("/review/queue", headers=h).status_code == 403  # acting as a user drops reviewer rights
    assert tn.client.get("/tn/businesses/fx_seller_deccan", headers=h).status_code == 404
    assert tn.client.get("/tn/businesses/mine", headers={**OP, "X-Act-As": "alice"}).status_code == 403
    assert tn.client.get("/tn/businesses/mine", headers={**auth("alice"), "X-Act-As": "fx-user-srilakshmi"}).status_code == 403
    r = tn.client.post("/tn/businesses", json={"roles": ["buyer"], "display_name": "Demo New Shop"}, headers={**OP, "X-Act-As": "fx-user-new"})
    assert r.json()["bid"].startswith("fx_") and r.json()["is_fixture"]


def test_business_ledger_members_only(tn):
    bid = mk(tn, "alice").json()["bid"]
    r = tn.client.get(f"/tn/businesses/{bid}/ledger", headers=auth("alice"))
    assert r.status_code == 200 and r.json()["events"][0]["type"] == "tn.business.created"
    assert r.json()["verification"]["chain_ok"]
    assert "9876543210" not in r.text
    assert tn.client.get(f"/tn/businesses/{bid}/ledger", headers=auth("mallory")).status_code == 404


def test_owner_can_request_manual_review_once(tn):
    bid = mk(tn, "alice").json()["bid"]
    c = tn.client
    r1 = c.post(f"/tn/businesses/{bid}/request-review", json={"note": "Shop renamed last year"}, headers=auth("alice"))
    r2 = c.post(f"/tn/businesses/{bid}/request-review", json={}, headers=auth("alice"))
    assert r1.status_code == 200 and r2.status_code == 200
    assert r2.json()["task"]["reasons"].count("owner_requested") == 1
    assert c.post(f"/tn/businesses/{bid}/request-review", json={}, headers=auth("mallory")).status_code == 404
    t = c.get(f"/review/tasks/rv_{bid}", headers=auth("rita")).json()
    assert t["recommended_action"] and isinstance(t["manual_checks"], list)
