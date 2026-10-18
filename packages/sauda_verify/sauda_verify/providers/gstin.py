"""GSTIN preliminary validation (deterministic, offline).

Checks the structure of a GSTIN: state code, embedded PAN pattern and entity type, entity number,
the fixed 'Z', and the official mod-36 check character. A structurally valid GSTIN says nothing about
whether the registration exists, is active, or belongs to the declaring business: the result is
`preliminary_validation` and never `verified`.
"""
from __future__ import annotations

import re

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers._common import (
    consent_denied,
    mode,
    norm_state,
    not_consented,
)
from sauda_verify.providers.base import ProviderResult

CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# GST state / UT codes (CBIC). 25 (Daman & Diu) and 26 were merged in 2020; 28 is pre-2014 Andhra Pradesh
# (registrations remain); 97 = Other Territory, 99 = Centre Jurisdiction.
STATE_CODES: dict[str, str] = {
    "01": "JAMMU & KASHMIR", "02": "HIMACHAL PRADESH", "03": "PUNJAB", "04": "CHANDIGARH", "05": "UTTARAKHAND",
    "06": "HARYANA", "07": "DELHI", "08": "RAJASTHAN", "09": "UTTAR PRADESH", "10": "BIHAR", "11": "SIKKIM",
    "12": "ARUNACHAL PRADESH", "13": "NAGALAND", "14": "MANIPUR", "15": "MIZORAM", "16": "TRIPURA",
    "17": "MEGHALAYA", "18": "ASSAM", "19": "WEST BENGAL", "20": "JHARKHAND", "21": "ODISHA",
    "22": "CHHATTISGARH", "23": "MADHYA PRADESH", "24": "GUJARAT", "25": "DADRA & NAGAR HAVELI & DAMAN & DIU",
    "26": "DADRA & NAGAR HAVELI & DAMAN & DIU", "27": "MAHARASHTRA", "28": "ANDHRA PRADESH", "29": "KARNATAKA",
    "30": "GOA", "31": "LAKSHADWEEP", "32": "KERALA", "33": "TAMIL NADU", "34": "PUDUCHERRY",
    "35": "ANDAMAN & NICOBAR ISLANDS", "36": "TELANGANA", "37": "ANDHRA PRADESH", "38": "LADAKH",
    "97": "OTHER TERRITORY", "99": "CENTRE JURISDICTION",
}
SPECIAL_CODES = {"97", "99"}

# 4th PAN character: holder type
ENTITY_TYPES: dict[str, str] = {
    "P": "individual (proprietor)", "C": "company", "H": "Hindu undivided family", "F": "firm / LLP",
    "A": "association of persons", "T": "trust", "B": "body of individuals", "L": "local authority",
    "J": "artificial juridical person", "G": "government",
}
# declared constitution keyword -> expected PAN holder type(s)
_CONSTITUTION_TYPES = [
    (("proprietor", "individual", "sole"), {"P"}),
    (("llp", "limited liability partnership", "partnership", "firm"), {"F"}),
    (("private limited", "pvt", "public limited", "limited company", "company", "ltd"), {"C"}),
    (("huf", "hindu undivided"), {"H"}),
    (("trust",), {"T"}),
    (("society", "association", "aop"), {"A", "T"}),
    (("government", "govt"), {"G"}),
]

REGULAR = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
PATTERN = re.compile(r"^[0-9]{2}[A-Z]{3}[PCHFATBLJG][A-Z][0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
SOURCE_NAME = "GSTIN format and checksum validation (offline)"


def checksum_char(first14: str) -> str:
    """Official GSTIN check character over the first 14 characters (mod-36, alternating factor 1/2)."""
    total = 0
    for i, ch in enumerate(first14):
        v = CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return CHARS[(36 - total % 36) % 36]


def normalise(g: str | None) -> str:
    return re.sub(r"[\s\-]", "", (g or "")).upper()


def parse(gstin: str | None) -> dict:
    """Structural analysis. Returns {valid, errors:[...], state_code, state, pan, entity_type, entity_number,
    checksum_ok}. Never raises."""
    g = normalise(gstin)
    out: dict = {"gstin": g, "errors": [], "checksum_ok": False}
    if len(g) != 15:
        out["errors"].append(f"length is {len(g)}, expected 15")
    if any(c not in CHARS for c in g):
        out["errors"].append("contains characters other than A-Z and 0-9")
    if out["errors"]:
        out["valid"] = False
        return out
    sc = g[:2]
    out["state_code"] = sc
    out["state"] = STATE_CODES.get(sc)
    if sc not in STATE_CODES:
        out["errors"].append(f"state code {sc} is not a GST state code")
    pan = g[2:12]
    out["pan_masked"] = pan[:5] + "****" + pan[9]
    if not re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", pan):
        out["errors"].append("characters 3-12 do not follow the PAN pattern (5 letters, 4 digits, 1 letter)")
    elif pan[3] not in ENTITY_TYPES:
        out["errors"].append(f"PAN holder-type letter '{pan[3]}' is not a recognised type")
    else:
        out["entity_type"] = pan[3]
        out["entity_type_label"] = ENTITY_TYPES[pan[3]]
    if g[12] == "0":
        out["errors"].append("13th character (entity number) cannot be 0")
    out["entity_number"] = g[12]
    if g[13] != "Z":
        out["errors"].append("14th character must be 'Z'")
    expected = checksum_char(g[:14])
    out["checksum_ok"] = expected == g[14]
    if not out["checksum_ok"]:
        out["errors"].append("check character does not match (likely a typo or an invalid number)")
    out["valid"] = not out["errors"] and bool(PATTERN.match(g))
    # 15 alphanumerics that are not a regular-taxpayer GSTIN may be a UIN / TDS / TCS / non-resident number
    out["special_pattern"] = (not out["valid"] and len(g) == 15 and g.isalnum() and not REGULAR.match(g)
                              and sc in STATE_CODES)
    return out


def expected_entity_types(constitution: str | None) -> set[str] | None:
    c = (constitution or "").lower()
    if not c:
        return None
    for keys, types in _CONSTITUTION_TYPES:
        if any(k in c for k in keys):
            return types
    return None


class GstinFormatProvider:
    name = "gstin_format"
    dims = [Dim.registration]
    consent_key = "gst"

    def applicable(self, biz: Business) -> bool:
        return bool((biz.gstin or "").strip())

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify":
            return []
        if consent_denied(ctx, self.consent_key):
            return [not_consented(self.name, Dim.registration, self.consent_key)]
        return [validate(biz)]


def validate(biz: Business) -> ProviderResult:
    p = parse(biz.gstin)
    g = p["gstin"]
    fields: list[FieldCompare] = [
        FieldCompare(field="gstin_checksum", declared=g, observed="valid" if p["checksum_ok"] else "invalid",
                     match=p["checksum_ok"]),
    ]
    observed = {k: p.get(k) for k in ("state_code", "state", "pan_masked", "entity_type", "entity_type_label",
                                      "entity_number", "checksum_ok", "errors")}
    base = dict(source_kind=SourceKind.preliminary_validation, source_name=SOURCE_NAME, dim=Dim.registration,
                check_type="gstin_format", observed=observed)
    if p.get("special_pattern"):
        return ProviderResult(status=CheckStatus.inconclusive, fields=fields, **base,
                              summary=("The number is not in the regular-taxpayer GSTIN pattern (it may be a UIN, "
                                       "TDS/TCS or non-resident registration), so it could not be checked locally."))
    if not p["valid"]:
        return ProviderResult(status=CheckStatus.failed, fields=fields, **base,
                              summary="GSTIN format/checksum invalid; likely a typo: " + "; ".join(p["errors"]) + ".")

    conflicts: list[str] = []
    declared_state = norm_state(biz.address.state)
    if declared_state and p["state_code"] not in SPECIAL_CODES:
        ok = declared_state == p["state"]
        fields.append(FieldCompare(field="gstin_state", declared=biz.address.state, observed=p["state"].title(), match=ok))
        if not ok:
            conflicts.append(f"the GSTIN state code {p['state_code']} is {p['state'].title()}, but the declared "
                             f"address is in {biz.address.state}")
    exp = expected_entity_types(biz.constitution)
    if exp is not None:
        ok = p["entity_type"] in exp
        fields.append(FieldCompare(field="pan_holder_type", declared=biz.constitution,
                                   observed=p["entity_type_label"], match=ok))
        if not ok:
            conflicts.append(f"the PAN inside the GSTIN is for a {p['entity_type_label']}, "
                             f"but the declared constitution is '{biz.constitution}'")
    if conflicts:
        return ProviderResult(status=CheckStatus.conflict, fields=fields, **base,
                              summary="The GSTIN is well-formed, but " + "; and ".join(conflicts) + ".")
    return ProviderResult(
        status=CheckStatus.partially_verified, fields=fields, **base,
        summary=(f"The GSTIN is well-formed (state {p['state'].title()}, PAN holder type: "
                 f"{p['entity_type_label']}) and its check character is correct. This is a format check only: "
                 "it does not confirm that the registration exists, is active, or belongs to this business."),
    )
