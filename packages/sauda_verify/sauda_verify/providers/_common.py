"""Shared helpers for providers: name/state normalisation, field comparison, consent handling."""
from __future__ import annotations

import difflib
import re
import unicodedata
from datetime import UTC, datetime

from sauda_verify.models import CheckStatus, Dim, FieldCompare, SourceKind
from sauda_verify.providers.base import ProviderResult

# --------------------------------------------------------------------------- name normalisation
_PUNCT = re.compile(r"[^A-Z0-9 ]+")
# spelling variants that are common in Indian business names; mapping to one canonical token makes the
# two spellings a NEAR match (never an exact one)
_VARIANTS = {
    "SHRI": "SRI", "SREE": "SRI", "SHREE": "SRI", "SHRII": "SRI", "SIRI": "SRI", "SRII": "SRI",
    "LAXMI": "LAKSHMI", "LUXMI": "LAKSHMI", "LAKSMI": "LAKSHMI", "LAKSHMY": "LAKSHMI", "LAXMY": "LAKSHMI",
    "LIMITED": "LTD", "PRIVATE": "PVT", "COMPANY": "CO", "AND": "&", "ENTERPRISE": "ENTERPRISES",
    "TRADER": "TRADERS", "STORE": "STORES", "AGENCY": "AGENCIES", "DISTRIBUTOR": "DISTRIBUTORS",
    "SUPERMARKET": "SUPERMARKETS", "MART": "MARTS",
}
_DROP = {"M S", "MS", "M/S", "MESSRS"}


def norm_text(s: str | None) -> str:
    """Upper-case, strip accents and punctuation, collapse whitespace. '&' kept as a word."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = _PUNCT.sub(" ", s.upper().replace("&", " QQAMPQQ "))
    return " ".join(s.split()).replace("QQAMPQQ", "&")


def _canon_tokens(s: str) -> list[str]:
    n = norm_text(s)
    for d in _DROP:
        if n.startswith(d + " "):
            n = n[len(d) + 1:]
    return [_VARIANTS.get(t, t) for t in n.split()]


def compare_names(declared: str | None, observed: str | None) -> str:
    """'exact' (equal ignoring case/punctuation/spacing), 'near' (equal after spelling variants such as
    Sri/Shri/Sree, Laxmi/Lakshmi, Store/Stores, or very similar), 'different', or 'missing'."""
    if not (declared or "").strip() or not (observed or "").strip():
        return "missing"
    a, b = norm_text(declared), norm_text(observed)
    if a == b:
        return "exact"
    ca, cb = _canon_tokens(declared), _canon_tokens(observed)
    if ca == cb or sorted(ca) == sorted(cb):
        return "near"
    if difflib.SequenceMatcher(None, " ".join(ca), " ".join(cb)).ratio() >= 0.9:
        return "near"
    return "different"


def name_field(field: str, declared: str | None, observed: str | None) -> tuple[FieldCompare, str]:
    """FieldCompare for a name: exact -> match True, near -> match None (needs a human look), different -> False."""
    r = compare_names(declared, observed)
    match = {"exact": True, "near": None, "different": False, "missing": None}[r]
    return FieldCompare(field=field, declared=declared, observed=observed, match=match), r


def norm_id(s: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


# --------------------------------------------------------------------------- states
# canonical names follow the GST state-code table (gstin.STATE_CODES)
_STATE_ALIASES = {
    "ORISSA": "ODISHA", "PONDICHERRY": "PUDUCHERRY", "UTTARANCHAL": "UTTARAKHAND",
    "J&K": "JAMMU & KASHMIR", "JAMMU KASHMIR": "JAMMU & KASHMIR", "JAMMU & KASHMIR": "JAMMU & KASHMIR",
    "ANDAMAN & NICOBAR": "ANDAMAN & NICOBAR ISLANDS", "ANDAMAN & NICOBAR ISLANDS": "ANDAMAN & NICOBAR ISLANDS",
    "DADRA & NAGAR HAVELI": "DADRA & NAGAR HAVELI & DAMAN & DIU",
    "DAMAN & DIU": "DADRA & NAGAR HAVELI & DAMAN & DIU",
    "DADRA & NAGAR HAVELI & DAMAN & DIU": "DADRA & NAGAR HAVELI & DAMAN & DIU",
    "NCT OF DELHI": "DELHI", "NEW DELHI": "DELHI", "TAMILNADU": "TAMIL NADU", "CHHATISGARH": "CHHATTISGARH",
    "TELENGANA": "TELANGANA", "AP": "ANDHRA PRADESH", "TS": "TELANGANA", "KA": "KARNATAKA", "MH": "MAHARASHTRA",
    "TN": "TAMIL NADU", "UP": "UTTAR PRADESH", "MP": "MADHYA PRADESH", "WB": "WEST BENGAL",
}


def norm_state(s: str | None) -> str:
    n = norm_text(s).replace(" AND ", " & ")
    n = n.removeprefix("THE ")
    n = n.replace("STATE OF ", "")
    return _STATE_ALIASES.get(n, n)


# --------------------------------------------------------------------------- misc
def now_iso(ctx: dict | None = None) -> str:
    return (ctx or {}).get("now") or datetime.now(UTC).isoformat()


def mode(ctx: dict | None) -> str:
    """'verify' (default), 'evidence' (documents/photo) or 'location' (geocode device check)."""
    return (ctx or {}).get("mode") or "verify"


def consent_denied(ctx: dict | None, key: str | None) -> bool:
    """A check is skipped only when its consent key is present and explicitly false."""
    if not key:
        return False
    consents = (ctx or {}).get("consents") or {}
    return key in consents and consents[key] is False


def not_consented(name: str, dim: Dim, key: str) -> ProviderResult:
    return ProviderResult(
        status=CheckStatus.pending, source_kind=SourceKind.self_declared, source_name=name, dim=dim,
        check_type=name, available=False,
        summary=f"Not run: consent '{key}' was not given. Nothing was checked; this is not a negative finding.",
        observed={"consent": key, "consented": False},
    )
