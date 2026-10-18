"""Restock-session routes (CONTRACT2): /restock/sessions*, /telemetry/voice. Owner auth on every route; an unknown,
foreign-shop or other-owner sid is 404 (existence is not leaked)."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .services import sessions

log = logging.getLogger("buyer_agent.sessions")
router = APIRouter()
TURNS_PER_MIN = 60  # continuous voice sends one turn per utterance


def owner(authorization: str | None = Header(default=None)) -> str:
    from .main import owner_uid

    return owner_uid(authorization)


def _can_access(shop_id: str, uid: str) -> bool:
    from .main import check_shop_owner

    try:
        check_shop_owner(shop_id, uid)
        return True
    except HTTPException:
        return False


def _err(e: sessions.SessionError) -> JSONResponse:
    body = {"code": e.code, "message": e.message, "detail": {"code": e.code, "message": e.message}}
    if e.session is not None:
        body["session"] = sessions.public(e.session) if "sid" in e.session else e.session
    return JSONResponse(body, status_code=e.status)


_hits: dict[str, deque] = defaultdict(deque)


def _rate(uid: str) -> None:
    q, now = _hits[uid], time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= TURNS_PER_MIN:
        raise HTTPException(429, f"turns: {TURNS_PER_MIN} per minute")
    q.append(now)


class CreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=80)
    shop_id: str | None = None  # contract extension: defaults to the demo shop (DEMO_SHOP_ID)


class PatchIn(BaseModel):
    model_config = {"extra": "ignore"}
    version: int
    title: str | None = Field(default=None, max_length=80)
    lines: list | None = None
    stated_budget_paise: int | None = None


class TurnIn(BaseModel):
    client_turn_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=2000)
    source: Literal["voice", "text"] = "text"
    lang: str | None = Field(default=None, max_length=10)


class Mark(BaseModel):
    model_config = {"extra": "allow"}  # e.g. `utt` (utterance id) used only for grouping; never logged
    name: str = Field(max_length=40)
    t_ms: float | None = None
    t: float | None = None  # the owner app sends `t` (performance.now() ms)

    @property
    def at(self) -> float | None:
        return self.t_ms if self.t_ms is not None else self.t


class TelemetryIn(BaseModel):
    sid: str | None = None
    marks: list[Mark] = Field(default_factory=list, max_length=200)


def _shop(shop_id: str | None) -> str:
    from .deps import settings

    return shop_id or settings().demo_shop_id


@router.post("/restock/sessions")
def create_session(body: CreateIn | None = None, uid: str = Depends(owner)):
    from .main import check_shop_owner

    body = body or CreateIn()
    shop_id = _shop(body.shop_id)
    check_shop_owner(shop_id, uid)
    return sessions.public(sessions.create(shop_id, uid, body.title))


@router.get("/restock/sessions")
def list_sessions(status: str | None = Query(None, max_length=20), limit: int = Query(20, ge=1, le=50),
                  shop_id: str | None = Query(None, max_length=64), uid: str = Depends(owner)):
    from .main import check_shop_owner

    sid_shop = _shop(shop_id)
    check_shop_owner(sid_shop, uid)
    return {"sessions": sessions.list_for(sid_shop, uid, status, limit)}


@router.get("/restock/sessions/{sid}")
def get_session(sid: str, uid: str = Depends(owner)):
    try:
        return sessions.public(sessions.load(sid, uid, _can_access))
    except sessions.SessionError as e:
        return _err(e)


@router.patch("/restock/sessions/{sid}")
def patch_session(sid: str, body: PatchIn, uid: str = Depends(owner)):
    try:
        kw = {}
        if "stated_budget_paise" in body.model_fields_set:
            kw["stated_budget_paise"] = body.stated_budget_paise
        return sessions.patch(sid, uid, _can_access, body.version, title=body.title, lines=body.lines, **kw)
    except sessions.SessionError as e:
        return _err(e)


@router.post("/restock/sessions/{sid}/turns")
async def post_turn(sid: str, body: TurnIn, uid: str = Depends(owner)):
    _rate(uid)
    try:
        return await asyncio.to_thread(sessions.turn, sid, uid, body.client_turn_id, body.text, body.source, body.lang, _can_access)
    except sessions.SessionError as e:
        return _err(e)


@router.post("/restock/sessions/{sid}/prepare")
async def prepare_session(sid: str, uid: str = Depends(owner)):
    from .main import check_shop_owner, claim_shop

    def claim(shop_id: str) -> None:
        claim_shop(shop_id, uid, check_shop_owner(shop_id, uid))

    try:
        return await asyncio.to_thread(sessions.prepare, sid, uid, _can_access, claim)
    except sessions.SessionError as e:
        return _err(e)


@router.post("/restock/sessions/{sid}/cancel")
def cancel_session(sid: str, uid: str = Depends(owner)):
    try:
        return sessions.cancel(sid, uid, _can_access)
    except sessions.SessionError as e:
        return _err(e)


VOICE_MARKS = ("speech_start", "first_partial", "utterance_end", "final_transcript", "turn_sent", "turn_applied", "draft_rendered")


@router.post("/telemetry/voice")
def telemetry_voice(body: TelemetryIn, uid: str = Depends(owner)):
    """Client latency marks. Only durations between known marks are logged (no text, no audio, nothing stored)."""
    if body.sid:
        try:
            sessions.load(body.sid, uid, _can_access)
        except sessions.SessionError as e:
            return _err(e)
    groups: dict[str, dict[str, float]] = {}
    for m in body.marks:  # grouped per utterance when the client tags marks with one (the tag is never logged)
        g = groups.setdefault(str(getattr(m, "utt", None) or (m.model_extra or {}).get("utt") or ""), {})
        if m.name in VOICE_MARKS and m.name not in g and m.at is not None:
            g[m.name] = m.at
    pairs = [("speech_start", "first_partial"), ("utterance_end", "final_transcript"), ("final_transcript", "turn_sent"),
             ("turn_sent", "turn_applied"), ("turn_applied", "draft_rendered"), ("utterance_end", "draft_rendered")]
    samples: dict[str, list[float]] = defaultdict(list)
    for g in groups.values():
        for a, b in pairs:
            if a in g and b in g and g[b] >= g[a]:
                samples[f"{a}->{b}"].append(g[b] - g[a])
    durs = {k: round(sorted(v)[len(v) // 2]) for k, v in samples.items()}  # median per pair
    log.info(json.dumps({"evt": "voice.telemetry", "sid_hash": sessions.sid_hash(body.sid) if body.sid else None,
                         "durations_ms": durs, "utterances": len(groups), "marks": len(body.marks)}))
    return {"ok": True, "durations_ms": durs}
