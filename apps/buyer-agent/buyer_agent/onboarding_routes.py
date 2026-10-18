"""Conversational onboarding routes: /tn/onboarding*. Owner-only (other callers get 404).

POST /tn/onboarding {role, lang?}                          start; returns the first question
GET  /tn/onboarding/{oid}                                  the session
POST /tn/onboarding/{oid}/turns {client_turn_id, text, source, lang?}
PATCH /tn/onboarding/{oid} {version, updates, skip?}       tap-to-edit a field (validated the same way)
POST /tn/onboarding/{oid}/confirm {version, consents?, confirm_not_duplicate?}
POST /tn/onboarding/{oid}/cancel

Confirm creates the business through the same function as POST /tn/businesses (duplicate detection included),
then runs verification with the consents the owner gave.
"""
from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import onboarding_agent as ob
from . import trust_network_routes as tnr

router = APIRouter()


def _err(e: ob.OnboardingError) -> JSONResponse:
    return tnr._err(e.status, e.code, e.message, **e.extra)


class StartIn(BaseModel):
    role: Literal["buyer", "seller"] = "buyer"
    lang: str | None = Field(None, max_length=8)


class TurnIn(BaseModel):
    client_turn_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    source: Literal["voice", "text"] = "text"
    lang: str | None = Field(None, max_length=8)


class EditIn(BaseModel):
    version: int
    updates: dict = Field(default_factory=dict)
    skip: list[str] = Field(default_factory=list)


class ConfirmIn(BaseModel):
    version: int
    consents: dict[str, bool] | None = None
    confirm_not_duplicate: bool = False


@router.post("/tn/onboarding")
def start(body: StartIn, v: tnr.Viewer = Depends(tnr.viewer)):
    s = ob.start(v.uid, body.role, body.lang, v.is_fixture_user)
    return {"session": ob.public(s), "reply": s["question"]}


@router.get("/tn/onboarding/{oid}")
def get_session(oid: str, v: tnr.Viewer = Depends(tnr.viewer)):
    try:
        return ob.public(ob.load(oid, v.uid))
    except ob.OnboardingError as e:
        return _err(e)


@router.post("/tn/onboarding/{oid}/turns")
def post_turn(oid: str, body: TurnIn, v: tnr.Viewer = Depends(tnr.viewer)):
    try:
        return ob.turn(oid, v.uid, body.client_turn_id, body.text, body.source, body.lang)
    except ob.OnboardingError as e:
        return _err(e)


@router.patch("/tn/onboarding/{oid}")
def edit(oid: str, body: EditIn, v: tnr.Viewer = Depends(tnr.viewer)):
    try:
        return ob.edit(oid, v.uid, body.version, dict(body.updates), body.skip)
    except ob.OnboardingError as e:
        return _err(e)


@router.post("/tn/onboarding/{oid}/cancel")
def cancel(oid: str, v: tnr.Viewer = Depends(tnr.viewer)):
    try:
        return ob.cancel(oid, v.uid)
    except ob.OnboardingError as e:
        return _err(e)


@router.post("/tn/onboarding/{oid}/confirm")
def confirm(oid: str, body: ConfirmIn, v: tnr.Viewer = Depends(tnr.viewer)):
    t0 = time.perf_counter()
    with ob._lock(oid):
        try:
            s = ob.load(oid, v.uid)
        except ob.OnboardingError as e:
            return _err(e)
        if s["status"] == "created" and s.get("bid"):  # idempotent
            return {"bid": s["bid"], "summary": s.get("result_summary"), "session": ob.public(s), "idempotent": True}
        if s["version"] != body.version:
            return tnr._err(409, "version_conflict", "This setup changed on another device; reload it.", session=ob.public(s))
        if s["status"] != "confirming":
            return tnr._err(409, "not_ready", "A few details are still missing.", missing=s.get("missing") or [], session=ob.public(s))
        consents = body.consents if body.consents is not None else (s["draft"].get("consents") or {})
        if not consents.get("store"):
            return tnr._err(422, "consent_required", "Agree to keep the results privately and share only a summary to continue.")
        try:
            biz_in = tnr.BusinessIn(**ob.business_body(s, body.confirm_not_duplicate))
        except Exception as e:  # pydantic validation
            return tnr._err(422, "invalid_draft", f"Some details need fixing: {str(e)[:200]}")
        t1 = time.perf_counter()
        created = tnr.create_business(biz_in, v)
        if isinstance(created, JSONResponse):
            out = json.loads(created.body)
            out["session"] = ob.public(s)
            return JSONResponse(status_code=created.status_code, content=out)
        bid = created["bid"]
        t2 = time.perf_counter()
        try:
            ver = tnr.verify_business(bid, tnr.VerifyIn(consents=ob.verify_consents(consents)), v)
            summary = ver.get("summary") if isinstance(ver, dict) else None
        except Exception:
            ob.log.exception("verification after onboarding failed for %s", bid)
            summary = None
        t3 = time.perf_counter()
        s["status"], s["bid"] = "created", bid
        s["draft"]["consents"] = {k: bool(consents.get(k)) for k in ("registry", "address", "store")}
        s["draft"]["phone"] = s["draft"]["email"] = None  # raw contact lives only in the business's hashed form now
        s["result_summary"] = summary
        try:
            saved = ob.save(s)
        except ob.OnboardingError:
            saved = s
        latency = {"create": round((t2 - t1) * 1000), "verify": round((t3 - t2) * 1000), "total": round((time.perf_counter() - t0) * 1000)}
        return {"bid": bid, "summary": summary, "session": ob.public(saved), "latency_ms": latency, "idempotent": False}
