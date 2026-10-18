"""PIN code check against the Department of Posts directory (data.gov.in), shipped as data/pincodes/pincodes.csv.

Confirms that the declared PIN exists and lies in the declared state and district/city. It does not
confirm the street address or that the business is located there.
"""
from __future__ import annotations

import csv
import os
import re
import threading
from pathlib import Path

from sauda_verify.models import Business, CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers._common import (
    consent_denied,
    mode,
    norm_state,
    norm_text,
    not_consented,
)
from sauda_verify.providers.base import ProviderResult

RESOURCE_ID = "5c2f62fe-5afa-4119-a499-fec9d604d5bd"
SOURCE_URL = "https://www.data.gov.in/catalog/all-india-pincode-directory"
# the date data.gov.in last updated the resource (see data/pincodes/README.md)
AS_OF = os.environ.get("PINCODES_AS_OF", "2025-10-03")
SOURCE_NAME = f"data.gov.in All India Pincode Directory (as of {AS_OF})"

_DEFAULT_CSV = Path(__file__).resolve().parents[4] / "data" / "pincodes" / "pincodes.csv"
_lock = threading.Lock()
_index: dict[str, list[tuple[str, str]]] | None = None

_DELHI = {"NEW DELHI", "CENTRAL", "EAST", "NORTH", "NORTH EAST", "NORTH WEST", "SHAHDARA", "SOUTH", "SOUTH EAST",
          "SOUTH WEST", "WEST", "CENTRAL DELHI", "SOUTH DELHI", "NORTH DELHI", "EAST DELHI", "WEST DELHI"}
# city name -> district names it sits in (directory districts differ from common city names)
CITY_DISTRICTS: dict[str, set[str]] = {
    "BENGALURU": {"BENGALURU URBAN", "BANGALORE", "BENGALURU", "BANGALORE URBAN", "BENGALURU RURAL"},
    "BANGALORE": {"BENGALURU URBAN", "BANGALORE", "BENGALURU", "BANGALORE URBAN", "BENGALURU RURAL"},
    "HYDERABAD": {"HYDERABAD", "RANGA REDDY", "RANGAREDDY", "MEDCHAL MALKAJGIRI", "MEDCHAL-MALKAJGIRI",
                  "SANGAREDDY"},
    "SECUNDERABAD": {"HYDERABAD", "MEDCHAL MALKAJGIRI", "MEDCHAL-MALKAJGIRI"},
    "MUMBAI": {"MUMBAI", "MUMBAI CITY", "MUMBAI SUBURBAN", "THANE"},
    "BOMBAY": {"MUMBAI", "MUMBAI CITY", "MUMBAI SUBURBAN"},
    "DELHI": _DELHI,
    "NEW DELHI": _DELHI,
    "CHENNAI": {"CHENNAI", "TIRUVALLUR", "KANCHIPURAM", "CHENGALPATTU"},
    "MADRAS": {"CHENNAI"},
    "KOLKATA": {"KOLKATA", "NORTH 24 PARGANAS", "SOUTH 24 PARGANAS", "HOWRAH"},
    "CALCUTTA": {"KOLKATA"},
    "GURGAON": {"GURGAON", "GURUGRAM"},
    "GURUGRAM": {"GURGAON", "GURUGRAM"},
    "PUNE": {"PUNE"},
    "NAVI MUMBAI": {"THANE", "RAIGAD", "RAIGARH(MH)", "RAIGARH"},
    "NOIDA": {"GAUTAM BUDDHA NAGAR", "GAUTAM BUDDH NAGAR"},
}


def _csv_path() -> Path:
    return Path(os.environ.get("PINCODES_CSV") or _DEFAULT_CSV)


def load(path: Path | None = None) -> dict[str, list[tuple[str, str]]]:
    """pin -> [(district, state), ...]. Empty dict when the dataset is missing."""
    global _index
    if path is None and _index is not None:
        return _index
    p = path or _csv_path()
    idx: dict[str, list[tuple[str, str]]] = {}
    if p.exists():
        with p.open(newline="") as f:
            for row in csv.DictReader(f):
                idx.setdefault(row["pincode"], []).append((row["district"], row["state"]))
    if path is None:
        with _lock:
            _index = idx
    return idx


def lookup(pin: str, index: dict | None = None) -> list[tuple[str, str]]:
    return (index if index is not None else load()).get(re.sub(r"\D", "", pin or ""), [])


def _norm_district(s: str) -> str:
    return norm_text(s).replace("-", " ")


def city_matches_district(city: str, line: str, districts: list[str]) -> bool:
    c = _norm_district(city)
    ds = {_norm_district(d) for d in districts}
    if not c and not line:
        return False
    if c and (c in ds or any(c in d or d in c for d in ds)):
        return True
    if c in CITY_DISTRICTS and CITY_DISTRICTS[c] & ds:
        return True
    hay = f" {norm_text(line)} {c} "
    return any(f" {d} " in hay for d in ds)


def check(biz: Business, index: dict | None = None) -> ProviderResult:
    idx = index if index is not None else load()
    pin = re.sub(r"\D", "", biz.address.pin or "")
    base = dict(source_kind=SourceKind.official_registry, source_name=SOURCE_NAME, source_url=SOURCE_URL,
                dim=Dim.address, check_type="pincode_directory", provider_ref=f"data.gov.in:{RESOURCE_ID}")
    if not idx:
        return ProviderResult(status=CheckStatus.pending, available=False, **base,
                              summary="PIN directory data is not available on this server, so the PIN was not checked.")
    if len(pin) != 6 or pin[0] == "0":
        return ProviderResult(status=CheckStatus.failed, **base,
                              fields=[FieldCompare(field="pin", declared=biz.address.pin, observed=None, match=False)],
                              summary="The declared PIN is not a valid 6-digit Indian PIN code.")
    rows = idx.get(pin, [])
    if not rows:
        return ProviderResult(status=CheckStatus.conflict, **base,
                              fields=[FieldCompare(field="pin", declared=pin, observed="not found", match=False)],
                              summary=f"PIN {pin} is not in the Department of Posts directory ({AS_OF}).")
    rows = [(d, s) for d, s in rows if s and s != "NA"] or rows
    if all(s == "NA" for _, s in rows):
        return ProviderResult(status=CheckStatus.inconclusive, **base, observed={"pin": pin},
                              fields=[FieldCompare(field="pin", declared=pin, observed="found", match=True)],
                              summary=(f"PIN {pin} is in the directory, but the directory records no district or "
                                       "state for it, so the address could not be compared."))
    states = sorted({s for _, s in rows})
    districts = sorted({d for d, _ in rows})
    observed = {"pin": pin, "districts": districts, "states": states}
    fields = [FieldCompare(field="pin", declared=pin, observed="found", match=True)]
    st_ok = bool(biz.address.state) and norm_state(biz.address.state) in {norm_state(s) for s in states}
    fields.append(FieldCompare(field="state", declared=biz.address.state or None, observed=", ".join(states).title(),
                               match=st_ok if biz.address.state else None))
    dist_ok = city_matches_district(biz.address.city, biz.address.line, districts)
    fields.append(FieldCompare(field="district", declared=biz.address.city or None,
                               observed=", ".join(districts).title(), match=dist_ok if biz.address.city else None))
    where = f"{', '.join(districts).title()} district, {', '.join(states).title()}"
    if biz.address.state and not st_ok:
        return ProviderResult(status=CheckStatus.conflict, fields=fields, observed=observed, **base,
                              summary=f"PIN {pin} belongs to {where}, but the declared state is {biz.address.state}.")
    if not biz.address.state:
        return ProviderResult(status=CheckStatus.inconclusive, fields=fields, observed=observed, **base,
                              summary=f"PIN {pin} exists ({where}); no state was declared to compare.")
    if not dist_ok:
        return ProviderResult(status=CheckStatus.conflict, fields=fields, observed=observed, **base,
                              summary=(f"PIN {pin} is in {where}. The state matches, but the declared city "
                                       f"'{biz.address.city}' does not match the PIN's district."))
    return ProviderResult(status=CheckStatus.verified, fields=fields, observed=observed, **base,
                          summary=(f"PIN {pin} exists and lies in {where}, matching the declared city and state. "
                                   "This confirms the PIN, not the street address or that the business is there."))


class PincodeProvider:
    name = "pincode_directory"
    dims = [Dim.address]
    consent_key = "address"

    def applicable(self, biz: Business) -> bool:
        return bool((biz.address.pin or "").strip())

    def run(self, biz: Business, ctx: dict) -> list[ProviderResult]:
        if mode(ctx) != "verify":
            return []
        if consent_denied(ctx, self.consent_key):
            return [not_consented(self.name, Dim.address, self.consent_key)]
        return [check(biz)]
