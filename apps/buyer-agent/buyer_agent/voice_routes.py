"""POST /voice/parse (contract item 7). Owner auth; audio is parsed in memory and never stored.

Starlette's built-in form parser spools uploads over 1 MB to a temporary file on disk. To keep the promise that audio
is never stored, this route streams the body with a hard byte cap and parses the multipart form in memory itself.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from .services import voice

log = logging.getLogger("buyer_agent.voice")
router = APIRouter()

# multipart overhead (boundaries, headers, small text fields) on top of the audio cap
_BODY_CAP = voice.MAX_BYTES + 64 * 1024
_RATE: dict[str, deque] = defaultdict(deque)
RATE_PER_MIN = 30  # continuous voice: one request per spoken segment
TIMEOUT_S = 45.0


def owner(authorization: str | None = Header(default=None)) -> str:
    """The existing owner_uid dependency from main.py, resolved at call time (main includes this router)."""
    from .main import owner_uid

    return owner_uid(authorization)


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"code": code, "message": message, "detail": {"code": code, "message": message}}, status_code=status)


def _rate_ok(uid: str) -> bool:
    now, q = time.monotonic(), _RATE[uid]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_PER_MIN:
        return False
    q.append(now)
    return True


class _FormTooLarge(Exception):
    pass


def parse_multipart(body: bytes, content_type: str) -> tuple[dict[str, str], dict[str, tuple[str, bytes]]]:
    """In-memory multipart/form-data parse. Returns (text fields, files{name: (content_type, bytes)})."""
    from python_multipart.multipart import MultipartParser, parse_options_header

    ctype, params = parse_options_header(content_type)
    if ctype != b"multipart/form-data" or b"boundary" not in params:
        raise ValueError("expected multipart/form-data")
    fields: dict[str, str] = {}
    files: dict[str, tuple[str, bytes]] = {}
    cur: dict = {}
    hname = bytearray()
    hval = bytearray()

    def on_part_begin():
        cur.clear()
        cur.update(headers={}, data=bytearray())

    def on_header_field(d, s, e):
        hname.extend(d[s:e])

    def on_header_value(d, s, e):
        hval.extend(d[s:e])

    def on_header_end():
        cur["headers"][bytes(hname).decode("latin-1").lower()] = bytes(hval).decode("latin-1")
        hname.clear()
        hval.clear()

    def on_part_data(d, s, e):
        cur["data"].extend(d[s:e])

    def on_part_end():
        disp, dp = parse_options_header(cur["headers"].get("content-disposition", ""))
        name = dp.get(b"name", b"").decode("utf-8", "replace")
        if not name:
            return
        if b"filename" in dp:
            files[name] = (cur["headers"].get("content-type", ""), bytes(cur["data"]))
        else:
            fields[name] = bytes(cur["data"])[:200].decode("utf-8", "replace")

    p = MultipartParser(params[b"boundary"], {
        "on_part_begin": on_part_begin, "on_part_data": on_part_data, "on_part_end": on_part_end,
        "on_header_field": on_header_field, "on_header_value": on_header_value, "on_header_end": on_header_end,
    })
    p.write(body)
    p.finalize()
    return fields, files


async def _read_capped(request: Request) -> bytes:
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _BODY_CAP:
        raise _FormTooLarge
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > _BODY_CAP:
            raise _FormTooLarge
    return bytes(buf)


@router.post("/voice/parse")
async def voice_parse(request: Request, uid: str = Depends(owner)):
    if not _rate_ok(uid):
        return _err(429, "RATE_LIMITED", "Too many voice requests. Wait a minute and try again.")
    try:
        body = await _read_capped(request)
    except _FormTooLarge:
        return _err(413, "AUDIO_TOO_LARGE", "Recording segment is larger than 2 MB. Keep each segment under 30 seconds.")
    try:
        fields, files = parse_multipart(body, request.headers.get("content-type", ""))
    except Exception:
        return _err(400, "BAD_FORM", "Send the recording as multipart/form-data in a field named 'audio'.")
    del body
    if "audio" not in files:
        return _err(400, "AUDIO_EMPTY", "No audio was received. Send the recording in a field named 'audio'.")
    declared, audio = files.pop("audio")
    shop_id = (fields.get("shop_id") or "").strip()
    from . import main
    from .deps import settings

    shop_id = shop_id or settings().demo_shop_id
    try:
        main.check_shop_owner(shop_id, uid)
    except HTTPException as e:
        return _err(e.status_code, "FORBIDDEN" if e.status_code == 403 else "SHOP_ERROR", str(e.detail))
    lang_hint = (fields.get("lang_hint") or "").strip() or None
    try:
        out = await asyncio.wait_for(
            asyncio.to_thread(voice.parse_voice, audio, declared, lang_hint, shop_id), timeout=TIMEOUT_S)
    except voice.VoiceError as e:
        return _err(e.status, e.code, e.message)
    except asyncio.TimeoutError:
        return _err(504, "TRANSCRIBE_TIMEOUT", "Transcription took too long. Please try a shorter recording or type it.")
    return out
