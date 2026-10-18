"""Sandbox ("Try with a sample shop"): one personal, simulated buyer business per signed-in user.

- Created idempotently: the business id is derived from the user, so a second start returns the same shop.
- Marked `is_fixture: true` and `sandbox: true`. Every check on it is a simulated fixture result and is labelled as such,
  so it reads "Partially verified (sample)". Nothing on it is ever presented as a real verification.
- Only its owner sees it. It never appears in another user's Find suppliers (see trust_network_discovery).
- DELETE /tn/sandbox removes the shop and everything attached to it (checks, cases, review task, relationships,
  invitations). The ledger entries stay, as the ledger is append-only.
"""
from __future__ import annotations

import re

from fastapi import Body, Depends
from pydantic import BaseModel, Field
from sauda_verify import store as tn
from sauda_verify.models import FieldCompare as F

from .trust_network_routes import (
    ID_FIELD,
    SIM_NOTE,
    Viewer,
    _check_doc,
    _ensure_review,
    _index_fields,
    _public_business,
    ledger,
    router,
    summary_of,
    uid_hash,
    viewer,
)

SANDBOX_LABEL = "Sample shop for trying Sauda. Simulated data, not a real business."
SANDBOX_PIN = "500016"
SIM_SOURCE = "Simulated GST registry (sample shop)"


def sandbox_bid(uid: str) -> str:
    return f"sbx_{tn.keyed_hash(uid, 'sandbox')[:16]}"


def is_sandbox(b: dict | None) -> bool:
    return bool(b and b.get("sandbox"))


def visible_sandbox(b: dict, v: Viewer) -> bool:
    """A sandbox is visible only to its own members (and reviewers)."""
    return not is_sandbox(b) or v.uid in (b.get("members") or []) or v.is_reviewer


class SandboxIn(BaseModel):
    first_name: str | None = Field(None, max_length=40)


def _first_name(raw: str | None) -> str:
    words = re.sub(r"[^A-Za-zऀ-ॿఀ-౿ ]", " ", raw or "").split()
    return words[0][:20].title() if words else "Demo"


def _sandbox_doc(bid: str, v: Viewer, first: str) -> dict:
    now = tn.iso()
    name = f"Sample Kirana · {first}"
    doc = {
        "bid": bid, "roles": ["buyer"], "display_name": name, "legal_name": name, "constitution": "Proprietorship",
        "category": "Kirana / general store", "products": ["staples", "rice", "edible oil", "packaged foods"],
        "gstin": None, "udyam": None, "fssai": None, "cin_llpin": None,
        "address": {"line": "Sample address, Begumpet (not a real shop)", "city": "Hyderabad", "state": "Telangana", "pin": SANDBOX_PIN},
        "geo": None, "contact": {}, "contact_hash": None, "contact_hashes": {},
        "representative": {"name": first, "role": "Proprietor", "authority_status": "self_declared"},
        "brand_claims": [], "requirements": None, "owner_uid": v.uid, "members": [v.uid],
        "is_fixture": True, "sandbox": True, "fixture_label": SANDBOX_LABEL,
        "created_at": now, "updated_at": now, "version": 1,
    }
    return _index_fields(doc)


def _sandbox_checks(bid: str, name: str) -> list[dict]:
    case = f"case_{bid}_seed"
    rows = [
        ("registration", "simulated_fixture", "verified", "GST registration shows Active, regular taxpayer",
         {"check_type": "gst_registry", "observed": {"registration_status": "Active", "taxpayer_type": "Regular"}}),
        ("identity", "simulated_fixture", "partially_verified",
         "GST record matches the state and constitution, but the trade name is spelled slightly differently",
         {"check_type": "gst_name_match", "fields": [F(field="trade_name", declared=name, observed=name.replace("Kirana", "Kirana Store"),
                                                       match=False).model_dump()]}),
        ("address", "simulated_fixture", "partially_verified", f"Principal place of business is in Hyderabad, PIN {SANDBOX_PIN}",
         {"check_type": "gst_address", "fields": [F(field="pin", declared=SANDBOX_PIN, observed=SANDBOX_PIN, match=True).model_dump()]}),
        ("representative", "self_declared", "pending", "Proprietor is self-declared; authority to act for the business has not been shown yet.",
         {"check_type": "representative_declaration"}),
    ]
    out = []
    for n, (dim, kind, status, summary, extra) in enumerate(rows, 1):
        src = SIM_SOURCE if kind == "simulated_fixture" else "Owner declaration"
        if kind == "simulated_fixture":
            summary += SIM_NOTE
        c = _check_doc(bid, case, dim=dim, check_type=extra.pop("check_type"), source_kind=kind, source_name=src, status=status,
                       summary=summary, check_id=f"chk_{bid}_{n:02d}", **extra)
        c["is_fixture"] = True
        c["sandbox"] = True
        out.append(c)
    return out


def _view(b: dict, created: bool) -> dict:
    return {"business": {**_public_business(b), "summary": summary_of(b)}, "created": created, "sandbox": True,
            "label": SANDBOX_LABEL, "status_text": "Partially verified (sample)"}


@router.get("/tn/sandbox")
def get_sandbox(v: Viewer = Depends(viewer)):
    b = tn.business(sandbox_bid(v.uid))
    return {"exists": bool(b), **(_view(b, False) if b else {})}


@router.post("/tn/sandbox/start")
def start_sandbox(body: SandboxIn | None = Body(None), v: Viewer = Depends(viewer)):
    bid = sandbox_bid(v.uid)
    cur = tn.business(bid)
    if cur:
        return _view(cur, False)
    first = _first_name(body.first_name if body else None)
    doc = _sandbox_doc(bid, v, first)
    if not tn.create(tn.BUSINESSES, bid, doc):
        return _view(tn.business(bid), False)
    tn.create(tn.CASES, f"case_{bid}_seed", {"case_id": f"case_{bid}_seed", "bid": bid, "purpose": "sandbox", "status": "completed",
                                             "is_fixture": True, "sandbox": True, "created_at": tn.iso()})
    for c in _sandbox_checks(bid, doc["display_name"]):
        tn.put(tn.CHECKS, c["check_id"], c)
    actor = uid_hash(v.uid)
    ledger(bid, "tn.sandbox.created", actor, {"bid": bid, "is_fixture": True, "sandbox": True, "label": SANDBOX_LABEL})
    _ensure_review(doc, f"case_{bid}_seed", actor)
    return _view(tn.business(bid), True)


def _remove(bid: str) -> int:
    n = 0
    for coll, idf in ID_FIELD.items():
        for d in tn.all_docs(coll, limit=2000):
            owner = {str(d.get(k) or "") for k in ("bid", "business_id", "from_bid", "buyer_bid", "seller_bid")}
            if bid in owner and d.get(idf):
                tn.delete(coll, d[idf])
                n += 1
    return n


@router.delete("/tn/sandbox")
@router.post("/tn/sandbox/delete")  # same as DELETE, for browsers whose CORS policy allows only GET/POST/PATCH
def delete_sandbox(v: Viewer = Depends(viewer)):
    bid = sandbox_bid(v.uid)
    b = tn.business(bid)
    if not b or not is_sandbox(b) or v.uid not in (b.get("members") or []):
        return {"ok": True, "removed": 0, "existed": False}
    removed = _remove(bid)
    ledger(bid, "tn.sandbox.deleted", uid_hash(v.uid), {"bid": bid, "removed": removed})
    return {"ok": True, "removed": removed, "existed": True}
