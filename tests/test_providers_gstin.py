"""GSTIN preliminary validation (offline).

Valid vectors are real GSTINs of well-known companies as listed on public GST lookup sites (knowyourgst.com,
credlix.com, python-stdnum docs); they are used only as checksum fixtures.
"""
import pytest
from sauda_verify.models import Address, Business, CheckStatus, SourceKind
from sauda_verify.providers import REGISTRY, gstin

REAL = {
    "29AAACI4798L1ZU": ("Infosys Ltd", "Karnataka"),
    "29AAACI4798L2ZT": ("Infosys Ltd (2nd registration)", "Karnataka"),
    "36AAACI4798L3ZX": ("Infosys Ltd", "Telangana"),
    "27AAACR5055K1Z7": ("Reliance Industries Ltd", "Maharashtra"),
    "27AAACT2727Q1ZW": ("Tata Motors Ltd", "Maharashtra"),
    "33AAACR4849R1ZS": ("Tata Consultancy Services Ltd", "Tamil Nadu"),
    "27AAPFU0939F1ZV": ("python-stdnum documentation example", "Maharashtra"),
}


def biz(g, state="", constitution=None):
    return Business(bid="b1", display_name="X", gstin=g, constitution=constitution, address=Address(state=state))


@pytest.mark.parametrize("g", sorted(REAL))
def test_real_public_gstins_are_well_formed(g):
    p = gstin.parse(g)
    assert p["valid"], (REAL[g], p["errors"])
    assert gstin.checksum_char(g[:14]) == g[14]


@pytest.mark.parametrize("g", sorted(REAL))
def test_real_gstin_with_matching_state_is_partially_verified_never_verified(g):
    r = gstin.validate(biz(g, REAL[g][1], "Public Limited Company" if g[5] == "C" else None))
    assert r.status == CheckStatus.partially_verified
    assert r.source_kind == SourceKind.preliminary_validation
    assert "does not confirm" in r.summary


@pytest.mark.parametrize("bad,why", [
    ("27AAPFU0939F1ZO", "check character"),          # stdnum invalid example
    ("29AAACI4798L1ZV", "check character"),          # last char changed
    ("29AAACI4789L1ZU", "check character"),          # transposed digits
    ("29AAACJ4798L1ZU", "check character"),          # one letter changed
    ("39AAACI4798L1ZU", "state code"),        # no state 39
    ("29AAAXI4798L1ZU", "holder-type"),       # X is not a PAN holder type
    ("29AAACI4798L0ZU", "entity number"),     # 13th char cannot be 0
    ("29AAACI4798L1ZU1", "length"),
    ("29AAACI4798L1Z", "length"),
    ("29AAACI4798L1Z#", "characters"),
])
def test_corrupted_variants_fail(bad, why):
    p = gstin.parse(bad)
    assert not p["valid"]
    assert any(why in e for e in p["errors"]), p["errors"]
    r = gstin.validate(biz(bad, "Karnataka"))
    assert r.status in (CheckStatus.failed, CheckStatus.inconclusive)


def test_bad_checksum_is_failed_with_typo_summary():
    r = gstin.validate(biz("29AAACI4798L1ZV", "Karnataka"))
    assert r.status == CheckStatus.failed and "typo" in r.summary


def test_position_14_must_be_z():
    p = gstin.parse("29AAACI4798L1YU")
    assert not p["valid"] and any("'Z'" in e for e in p["errors"])


def test_state_mismatch_is_conflict():
    r = gstin.validate(biz("36AAACI4798L3ZX", "Karnataka"))
    assert r.status == CheckStatus.conflict
    f = next(f for f in r.fields if f.field == "gstin_state")
    assert f.match is False and f.observed == "Telangana"


def test_state_alias_and_case():
    assert gstin.validate(biz("36AAACI4798L3ZX", "telangana")).status == CheckStatus.partially_verified
    assert gstin.validate(biz("21AAACI4798L1ZA", "Orissa")).status == CheckStatus.partially_verified


def test_constitution_vs_pan_holder_type():
    r = gstin.validate(biz("29AAACI4798L1ZU", "Karnataka", "Proprietorship"))
    assert r.status == CheckStatus.conflict and "company" in r.summary
    assert gstin.validate(biz("27AAPFU0939F1ZV", "Maharashtra", "Partnership firm")).status == CheckStatus.partially_verified


def test_entity_type_and_masking():
    p = gstin.parse("27AAACR5055K1Z7")
    assert p["entity_type"] == "C" and p["entity_number"] == "1" and p["state"] == "MAHARASHTRA"
    assert "5055" not in p["pan_masked"]


def test_lowercase_and_spaces_normalised():
    assert gstin.parse(" 29aaaci4798l1zu ")["valid"]


def test_provider_respects_mode_and_consent():
    p = next(x for x in REGISTRY if x.name == "gstin_format")
    b = biz("29AAACI4798L1ZU", "Karnataka")
    assert p.applicable(b) and not p.applicable(biz(None))
    assert p.run(b, {"mode": "evidence"}) == []
    r = p.run(b, {"consents": {"gst": False}})
    assert r[0].status == CheckStatus.pending and not r[0].available
    assert p.run(b, {"consents": {"gst": True}})[0].status == CheckStatus.partially_verified
