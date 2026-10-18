"""PIN directory check: offline, against a tiny index and against the committed data.gov.in CSV."""
from pathlib import Path

import pytest
from sauda_verify.models import Address, Business, CheckStatus, SourceKind
from sauda_verify.providers import pincode

CSV = Path(__file__).resolve().parents[1] / "data" / "pincodes" / "pincodes.csv"
IDX = {
    "500016": [("HYDERABAD", "TELANGANA"), ("MEDCHAL MALKAJGIRI", "TELANGANA")],
    "560100": [("BENGALURU URBAN", "KARNATAKA")],
    "110001": [("NEW DELHI", "DELHI")],
    "121004": [("NA", "NA")],
}


def biz(pin, city="", state="", line=""):
    return Business(bid="b", display_name="X", address=Address(line=line, city=city, state=state, pin=pin))


def test_match_is_verified_official_registry():
    r = pincode.check(biz("500016", "Hyderabad", "Telangana"), IDX)
    assert r.status == CheckStatus.verified
    assert r.source_kind == SourceKind.official_registry
    assert r.source_name.startswith("data.gov.in All India Pincode Directory (as of ")
    assert "not the street address" in r.summary


def test_city_alias_to_district():
    assert pincode.check(biz("560100", "Bangalore", "Karnataka"), IDX).status == CheckStatus.verified
    assert pincode.check(biz("560100", "Bengaluru", "KA"), IDX).status == CheckStatus.verified
    assert pincode.check(biz("110001", "Delhi", "NCT of Delhi"), IDX).status == CheckStatus.verified


def test_wrong_state_is_conflict():
    r = pincode.check(biz("560100", "Bengaluru", "Telangana"), IDX)
    assert r.status == CheckStatus.conflict
    assert next(f for f in r.fields if f.field == "state").match is False


def test_wrong_district_is_conflict():
    r = pincode.check(biz("500016", "Warangal", "Telangana"), IDX)
    assert r.status == CheckStatus.conflict


def test_unknown_pin_is_conflict_and_malformed_failed():
    assert pincode.check(biz("999999", "X", "Telangana"), IDX).status == CheckStatus.conflict
    assert pincode.check(biz("50001", "X", "Telangana"), IDX).status == CheckStatus.failed
    assert pincode.check(biz("012345", "X", "Telangana"), IDX).status == CheckStatus.failed


def test_na_rows_are_inconclusive():
    assert pincode.check(biz("121004", "Faridabad", "Haryana"), IDX).status == CheckStatus.inconclusive


def test_missing_dataset_is_pending_never_invented():
    r = pincode.check(biz("500016", "Hyderabad", "Telangana"), {})
    assert r.status == CheckStatus.pending and r.available is False


@pytest.mark.skipif(not CSV.exists(), reason="pincode CSV not present")
def test_committed_dataset_real_pins():
    idx = pincode.load(CSV)
    assert len(idx) > 19000
    assert ("HYDERABAD", "TELANGANA") in idx["500001"]
    assert pincode.check(biz("560100", "Bengaluru", "Karnataka"), idx).status == CheckStatus.verified
    assert pincode.check(biz("400701", "Navi Mumbai", "Maharashtra"), idx).status == CheckStatus.verified
    assert pincode.check(biz("500016", "Hyderabad", "Karnataka"), idx).status == CheckStatus.conflict


def test_provider_mode_and_consent():
    p = pincode.PincodeProvider()
    b = biz("500016", "Hyderabad", "Telangana")
    assert p.run(b, {"mode": "location"}) == []
    assert p.run(b, {"consents": {"address": False}})[0].status == CheckStatus.pending
    assert not p.applicable(biz(""))
