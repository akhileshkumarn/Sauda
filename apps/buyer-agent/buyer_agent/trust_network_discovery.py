"""Supplier discovery for the Trust Network: opt-in seller listings, Find suppliers and requests to connect.

Privacy rules
- Only businesses that onboarded and chose to list appear, plus the clearly labelled simulated fixtures.
- A card carries only what the seller opted to list (categories, service area, minimum order, a short note), the
  plain-language verification category, and per-dimension status and source kind. Never the GSTIN, contacts,
  the address line, members, documents or customers.
- The service area is the seller's own declaration and is labelled self-declared everywhere.
- Ranking is by delivery area and verification status only, never by price or quality.
"""
from __future__ import annotations

import base64
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Literal

from fastapi import Depends, Query
from pydantic import BaseModel, Field
from sauda_verify import policy
from sauda_verify import store as tn
from sauda_verify.models import Category, CheckStatus, Dim, RelState, SourceKind
from sauda_verify.providers import pincode

from .trust_network_routes import (
    Viewer,
    _checks,
    _err,
    _model,
    _public_business,
    _screen,
    ledger,
    router,
    uid_hash,
    viewer,
)

DISCOVER_PER_MIN = 60
CONNECT_PER_DAY = 20
SORT_NOTE = "Sorted by delivery area and verification status, not by price or quality"
FIXTURE_LABEL = "Simulated (demo data)"
CARD_DIMS = (Dim.identity, Dim.registration, Dim.address, Dim.operational, Dim.representative, Dim.distribution_authority)
VERIFIED_CATEGORIES = {Category.identity_confirmed, Category.evidence_reviewed, Category.ready_for_counterparty_review}
CATEGORY_STRENGTH = {Category.ready_for_counterparty_review: 3, Category.evidence_reviewed: 2, Category.identity_confirmed: 1}
LISTING_CATEGORIES = ["staples", "rice", "edible oil", "packaged foods", "personal care", "cleaning", "dry fruits", "spices",
                      "beverages", "dairy", "snacks", "fmcg"]
CATEGORY_TEXT = {
    Category.identity_confirmed: "Identity confirmed",
    Category.evidence_reviewed: "Identity confirmed and evidence reviewed",
    Category.ready_for_counterparty_review: "Verified and ready for you to review",
    Category.additional_review_required: "Verification in progress",
    Category.verification_unsuccessful: "Verification unsuccessful",
}


# ---------------------------------------------------------------- rate limits
_hits: dict[str, deque] = defaultdict(deque)


def _limited(key: str, limit: int, window_s: int) -> bool:
    hits, now = _hits[key], time.time()
    while hits and now - hits[0] > window_s:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


# ---------------------------------------------------------------- areas (data.gov.in PIN directory)
_areas: dict[str, set[str]] | None = None


def areas() -> dict[str, set[str]]:
    """state -> districts, from the PIN directory. Upper-case directory spellings."""
    global _areas
    if _areas is None:
        out: dict[str, set[str]] = defaultdict(set)
        for rows in pincode.load().values():
            for d, s in rows:
                if d and s and d != "NA" and s != "NA":
                    out[s].add(d)
        _areas = dict(out)
    return _areas


def _norm(s: str | None) -> str:
    return " ".join((s or "").upper().replace("-", " ").split())


def canon_state(s: str | None) -> str | None:
    n = _norm(s)
    if not n:
        return None
    by_norm = {_norm(k): k for k in areas()}
    return by_norm.get(n) or by_norm.get(_norm(pincode.norm_state(n)))


def canon_district(d: str | None, state: str | None = None) -> tuple[str, str] | None:
    """-> (district, state) in directory spelling, or None. With no state, the district must be unambiguous."""
    n = _norm(d)
    if not n:
        return None
    hits = [(dd, s) for s, ds in areas().items() for dd in ds if _norm(dd) == n and (state is None or s == state)]
    return hits[0] if len(hits) == 1 else None


def area_of_pin(pin: str, city: str = "", line: str = "") -> tuple[str | None, str | None]:
    rows = [(d, s) for d, s in pincode.lookup(pin) if d != "NA" and s != "NA"]
    if not rows:
        return None, None
    for d, s in rows:
        if pincode.city_matches_district(city, line, [d]):
            return d, s
    return rows[0]


def title(s: str | None) -> str | None:
    return s.title() if s else s


# ---------------------------------------------------------------- coverage
def covers_district(area: dict, district: str | None, state: str | None) -> bool:
    kind = area.get("kind")
    if kind == "pan_india":
        return True
    if kind == "state":
        return bool(state) and state in (area.get("states") or [])
    if kind == "district":
        return bool(district) and district in (area.get("districts") or []) and (not state or state in (area.get("states") or []))
    return False


def covers_state(area: dict, state: str | None) -> bool:
    if area.get("kind") == "pan_india":
        return True
    return bool(state) and state in (area.get("states") or [])


def area_label(area: dict) -> str:
    kind = area.get("kind")
    if kind == "pan_india":
        txt = "Delivers across India"
    elif kind == "state":
        txt = "Delivers across " + ", ".join(title(s) for s in area.get("states") or [])
    else:
        txt = "Delivers in " + ", ".join(title(d) for d in area.get("districts") or []) + " district"
    return f"{txt} (self-declared)"


# ---------------------------------------------------------------- trust view for a card
def trust_view(b: dict) -> tuple[dict, Category, str | None]:
    """Category and per-dimension status. A fixture is judged only by its own simulated results (treated as if from
    a registry so the demo can show the journey) and is always labelled; a real business uses the policy unchanged."""
    checks = _checks(b["bid"])
    biz = _model(b)
    fixture = bool(b.get("is_fixture"))
    judged = [c.model_copy(update={"source_kind": SourceKind.official_registry}) if fixture and c.source_kind == SourceKind.simulated_fixture
              else c for c in checks]
    cat = policy.category(judged, biz, evidence=tn.evidence_of(b["bid"]))
    dims = policy.dimensions(checks, biz)
    out_dims = []
    for d in CARD_DIMS:
        ds = dims.get(d)
        if ds is None:
            out_dims.append({"dim": d.value, "label": policy.DIM_LABELS[d], "status": CheckStatus.not_applicable.value, "source_kind": None})
        else:
            out_dims.append({"dim": d.value, "label": policy.DIM_LABELS[d], "status": ds.status.value,
                             "source_kind": ds.source_kind.value if ds.source_kind else None})
    text = CATEGORY_TEXT[cat] + (" (simulated demo data)" if fixture else "")
    last = max((c.checked_at for c in checks if c.checked_at), default=None)
    return {"category": cat.value, "category_text": text, "dims": out_dims}, cat, last


def _connection(rel: dict | None) -> str:
    if not rel:
        return "none"
    st = rel.get("state")
    if st in (RelState.requested.value, RelState.invited.value):
        return "requested"
    if st == RelState.declined.value:
        return "declined"
    return "connected"


def card(b: dict, *, viewer_area: tuple[str | None, str | None] = (None, None), rel: dict | None = None) -> tuple[dict, Category]:
    lst = b.get("listing") or {}
    area = {**(lst.get("service_area") or {}), "basis": "self_declared"}
    addr = b.get("address") or {}
    district, state = area_of_pin(str(addr.get("pin") or ""), addr.get("city") or "", "")
    trust, cat, last = trust_view(b)
    fixture = bool(b.get("is_fixture"))
    return {
        "bid": b["bid"],
        "display_name": b.get("display_name"),
        "city": addr.get("city"),
        "district": title(district),
        "state": title(state) or addr.get("state"),
        "categories": lst.get("categories") or [],
        "service_area": {"kind": area.get("kind"), "districts": area.get("districts") or [], "states": area.get("states") or [],
                         "basis": "self_declared", "label": area_label(area)},
        "min_order_paise": lst.get("min_order_paise"),
        "notes": lst.get("notes"),
        "delivers_to_viewer": covers_district(area, *viewer_area),
        "trust": trust,
        "last_checked_at": last,
        "is_fixture": fixture,
        "fixture_label": FIXTURE_LABEL if fixture else None,
        "connection": _connection(rel),
        "rid": rel.get("rid") if rel else None,
    }, cat


# ---------------------------------------------------------------- listing
class ServiceAreaIn(BaseModel):
    kind: Literal["district", "state", "pan_india"]
    districts: list[str] = Field(default_factory=list, max_length=60)
    states: list[str] = Field(default_factory=list, max_length=40)


class ListingIn(BaseModel):
    version: int
    listed: bool
    categories: list[str] = Field(default_factory=list, max_length=12)
    service_area: ServiceAreaIn
    min_order_paise: int | None = Field(None, ge=0, le=10_000_000_00)
    notes: str | None = Field(None, max_length=200)


def _validate_area(a: ServiceAreaIn) -> tuple[dict | None, list[str]]:
    bad: list[str] = []
    states: list[str] = []
    for s in a.states:
        c = canon_state(s)
        if not c:
            bad.append(s)
        elif c not in states:
            states.append(c)
    districts: list[str] = []
    if a.kind == "district":
        if not a.districts:
            bad.append("at least one district")
        for d in a.districts:
            hit = None
            for s in states or [None]:
                hit = canon_district(d, s)
                if hit:
                    break
            if not hit:
                bad.append(d)
                continue
            if hit[0] not in districts:
                districts.append(hit[0])
            if hit[1] not in states:
                states.append(hit[1])
    elif a.kind == "state" and not states and not bad:
        bad.append("at least one state")
    if a.kind == "pan_india":
        states, districts = [], []
    if bad:
        return None, bad
    return {"kind": a.kind, "districts": districts, "states": states, "basis": "self_declared"}, []


@router.get("/tn/areas")
def list_areas():
    return {"states": [{"state": s, "districts": sorted(ds)} for s, ds in sorted(areas().items())],
            "source": pincode.SOURCE_NAME}


@router.get("/tn/listing-categories")
def listing_categories():
    return {"categories": LISTING_CATEGORIES}


@router.put("/tn/businesses/{bid}/listing")
def put_listing(bid: str, body: ListingIn, v: Viewer = Depends(viewer)):
    b = tn.business(bid)
    if not b or v.uid not in (b.get("members") or []):
        return _err(404, "not_found", "business not found")
    if "seller" not in (b.get("roles") or []):
        return _err(403, "seller_role_required", "Only a business that sells can be listed in Find suppliers.")
    area, bad = _validate_area(body.service_area)
    if bad:
        return _err(422, "invalid_area", "Some districts or states are not in the India PIN directory.", invalid=bad)
    cats = []
    for c in body.categories:
        c = " ".join(c.strip().lower().split())[:40]
        if c and c not in cats:
            cats.append(c)
    if body.listed and not cats:
        return _err(422, "categories_required", "Pick at least one category to be listed.")
    notes = tn.mask_text(body.notes.strip()) if body.notes and body.notes.strip() else None
    listing = {"listed": body.listed, "categories": cats, "service_area": area, "min_order_paise": body.min_order_paise,
               "notes": notes, "updated_at": tn.iso()}
    try:
        saved = tn.cas_replace(tn.BUSINESSES, bid, body.version, {**b, "listing": listing})
    except tn.VersionConflict as e:
        return _err(409, "version_conflict", "This business changed elsewhere; reload it.",
                    current=_public_business(e.current) if e.current else None)
    ledger(bid, "tn.listing.updated", uid_hash(v.uid), {"bid": bid, "listed": body.listed, "categories": cats,
                                                        "service_area": area, "version": saved["version"]})
    c, _ = card(saved)
    return {"business": _public_business(saved), "card": c}


# ---------------------------------------------------------------- discovery
def _buyer_business(v: Viewer, bid: str | None) -> dict | None:
    mine = [b for b in tn.businesses_of(v.uid) if "buyer" in (b.get("roles") or [])]
    if bid:
        mine = [b for b in mine if b["bid"] == bid]
    return min(mine, key=lambda b: b.get("created_at") or "") if mine else None


def _buyer_required() -> object:
    return _err(403, "buyer_profile_required", "Set up and verify your shop's business profile to find suppliers.")


def listed_sellers() -> list[dict]:
    if not hasattr(tn.db(), "replace_if"):
        docs = tn.where(tn.BUSINESSES, "listing.listed", True)
    else:  # the in-memory test double has no nested-field filter
        docs = [b for b in tn.all_docs(tn.BUSINESSES, limit=2000) if (b.get("listing") or {}).get("listed") is True]
    return [b for b in docs if "seller" in (b.get("roles") or []) and (b.get("listing") or {}).get("listed") is True]


def _encode_cursor(n: int) -> str:
    return base64.urlsafe_b64encode(f"o:{n}".encode()).decode().rstrip("=")


def _decode_cursor(c: str | None) -> int:
    if not c:
        return 0
    try:
        raw = base64.urlsafe_b64decode(c + "=" * (-len(c) % 4)).decode()
        return max(0, int(raw.split(":", 1)[1]))
    except Exception:
        return 0


@router.get("/tn/discover")
def discover(bid: str | None = Query(None), q: str | None = Query(None, max_length=80), category: str | None = Query(None, max_length=40),
             scope: Literal["district", "state", "india"] = Query("district"), district: str | None = Query(None, max_length=80),
             state: str | None = Query(None, max_length=80), verified_only: bool = Query(True), limit: int = Query(20, ge=1, le=50),
             cursor: str | None = Query(None, max_length=200), v: Viewer = Depends(viewer)):
    if _limited(f"discover:{v.uid}", DISCOVER_PER_MIN, 60):
        return _err(429, "rate_limited", f"Up to {DISCOVER_PER_MIN} searches a minute. Try again shortly.")
    buyer = _buyer_business(v, bid)
    if not buyer:
        return _buyer_required()
    addr = buyer.get("address") or {}
    my_d, my_s = area_of_pin(str(addr.get("pin") or ""), addr.get("city") or "", addr.get("line") or "")
    st = canon_state(state) if state else my_s
    if state and not st:
        return _err(422, "invalid_area", "That state is not in the India PIN directory.", invalid=[state])
    di = my_d if not district else (canon_district(district, st) or (None, None))[0]
    if district and not di:
        return _err(422, "invalid_area", "That district is not in the India PIN directory.", invalid=[district])
    rels = {}
    for r in tn.relationships_of(buyer["bid"]):
        if r.get("buyer_bid") == buyer["bid"]:
            rels[r["seller_bid"]] = r
    ql = (q or "").strip().lower()
    cat_f = (category or "").strip().lower()
    rows = []
    for s in listed_sellers():
        if s["bid"] == buyer["bid"]:
            continue
        lst = s["listing"]
        area = lst.get("service_area") or {}
        if scope == "district" and not covers_district(area, di, st):
            continue
        if scope == "state" and not covers_state(area, st):
            continue
        cats = lst.get("categories") or []
        if cat_f and cat_f not in cats:
            continue
        if ql and not any(ql in (x or "").lower() for x in [s.get("display_name"), (s.get("address") or {}).get("city"), *cats]):
            continue
        c, cat = card(s, viewer_area=(di, st), rel=rels.get(s["bid"]))
        if verified_only and cat not in VERIFIED_CATEGORIES:
            continue
        rows.append(c)
    def last_ts(c):  # most recently checked first
        return c["last_checked_at"] or ""
    rows.sort(key=lambda c: c["display_name"] or "")
    rows.sort(key=last_ts, reverse=True)
    rows.sort(key=lambda c: (not c["delivers_to_viewer"], -CATEGORY_STRENGTH.get(Category(c["trust"]["category"]), 0)))
    off = _decode_cursor(cursor)
    page = rows[off:off + limit]
    nxt = _encode_cursor(off + limit) if off + limit < len(rows) else None
    return {"viewer": {"bid": buyer["bid"], "display_name": buyer.get("display_name"), "district": title(my_d), "state": title(my_s),
                       "pin": addr.get("pin")},
            "scope": scope, "area": {"district": title(di), "state": title(st)}, "verified_only": verified_only,
            "results": page, "next_cursor": nxt, "total": len(rows), "sort_note": SORT_NOTE}


# ---------------------------------------------------------------- request to connect
class ConnectIn(BaseModel):
    from_bid: str
    to_bid: str
    categories: list[str] = Field(default_factory=list, max_length=12)
    message: str | None = Field(None, max_length=300)


@router.post("/tn/connect")
def connect(body: ConnectIn, v: Viewer = Depends(viewer)):
    buyer = _buyer_business(v, body.from_bid)
    if not buyer:
        return _buyer_required()
    if body.to_bid == buyer["bid"]:
        return _err(409, "self_connect", "A business cannot connect to itself.")
    seller = tn.business(body.to_bid)
    if not seller or not (seller.get("listing") or {}).get("listed") or "seller" not in (seller.get("roles") or []):
        return _err(404, "not_found", "supplier not found")
    rid = f"rel_{tn.stable_hash([buyer['bid'], seller['bid']])[:16]}"
    existing = tn.get(tn.RELATIONSHIPS, rid)
    if existing:
        return {"relationship": existing, "duplicate": True, "guard": (existing.get("request") or {}).get("guard")}
    day_ago = tn.iso(tn.now() - timedelta(days=1))
    recent = [r for r in tn.where(tn.RELATIONSHIPS, "buyer_bid", buyer["bid"])
              if r.get("provenance") == "discovery_request" and (r.get("created_at") or "") >= day_ago]
    if len(recent) >= CONNECT_PER_DAY:
        return _err(429, "rate_limited", f"Up to {CONNECT_PER_DAY} connection requests a day per business.")
    listed = (seller.get("listing") or {}).get("categories") or []
    cats = [c for c in dict.fromkeys(" ".join(x.strip().lower().split()) for x in body.categories) if c in listed] or listed[:1]
    msg = (body.message or "").strip()
    guard = _screen(msg) if msg else {"blocked": False, "categories": []}
    now = tn.iso()
    actor = uid_hash(v.uid)
    rel = {"rid": rid, "buyer_bid": buyer["bid"], "seller_bid": seller["bid"], "initiated_by_bid": buyer["bid"],
           "state": RelState.requested.value, "categories": cats, "provenance": "discovery_request",
           "shared_fields": ["display_name", "city", "state", "category", "products", "verification_summary"],
           "requirements": seller.get("requirements") or policy.DEFAULT_REQUIREMENTS, "approved_tiers": [],
           "human_review": None, "invitation_id": None,
           "request": {"message": None if guard.get("blocked") else (tn.mask_text(msg) or None), "message_blocked": bool(guard.get("blocked")),
                       "guard": guard, "categories": cats, "at": now, "untrusted": True},
           "history": [{"from": None, "to": "requested", "by_hash": actor, "by_bid": buyer["bid"],
                        "reason": "connection requested from Find suppliers", "at": now}],
           "is_fixture": bool(buyer.get("is_fixture") and seller.get("is_fixture")), "created_at": now, "updated_at": now, "version": 1}
    if not tn.create(tn.RELATIONSHIPS, rid, rel):
        cur = tn.get(tn.RELATIONSHIPS, rid)
        return {"relationship": cur, "duplicate": True, "guard": (cur.get("request") or {}).get("guard")}
    for b_ in (buyer["bid"], seller["bid"]):
        ledger(b_, "tn.relationship.requested", actor, {"rid": rid, "buyer_bid": buyer["bid"], "seller_bid": seller["bid"],
                                                       "categories": cats, "message_blocked": bool(guard.get("blocked"))})
    return {"relationship": rel, "duplicate": False, "guard": guard}
