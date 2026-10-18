"""POST /voice/parse with Gemini mocked: auth, size, type, duration, silence validation and the response shape."""
import dataclasses
import io
import math
import struct
import wave

import pytest
from fastapi.testclient import TestClient

from buyer_agent import deps, main
from buyer_agent.services import demand, voice


def wav_bytes(seconds=1.5, rate=16000, amp=8000, channels=1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(seconds * rate)
        frames = b"".join(struct.pack("<h", int(amp * math.sin(2 * math.pi * 220 * i / rate))) * channels for i in range(n))
        w.writeframes(frames)
    return buf.getvalue()


def ogg_bytes(seconds=2.0):
    # minimal Ogg page sequence: header page + last page whose granule position encodes 48 kHz samples
    page = lambda gran: b"OggS\x00\x00" + struct.pack("<q", gran) + b"\x00" * 13
    return page(0) + b"OpusHead" + b"\x00" * 600 + page(int(seconds * 48000)) + b"\x00" * 16


WEBM = b"\x1a\x45\xdf\xa3" + b"\x00" * 4000


@pytest.fixture
def client(monkeypatch):
    calls = {"transcribe": [], "draft": []}

    def fake_transcribe(audio, mime, hint):
        calls["transcribe"].append((len(audio), mime, hint))
        return voice.Transcription(speech_detected=True, transcript="10 packets Aashirvaad atta 1 kg, keep under 8,000 rupees",
                                   language="en", languages_present=["en"], unclear=[]), {"audio_tokens": 48}

    def fake_build_draft(shop_id, text):
        calls["draft"].append((shop_id, text))
        return {"shop_id": shop_id, "lines": [{"gtin": "890", "name": "Atta", "qty": 10, "qty_source": "owner", "confidence": "high"}],
                "unmatched": [], "stated_budget_paise": 800000, "clarifications": [], "suggested_budget_paise": 800000,
                "suggested_mandate": {"kind": "intent", "budget_paise": 800000}}

    monkeypatch.setattr(voice, "transcribe", fake_transcribe)
    monkeypatch.setattr(demand, "build_draft", fake_build_draft)
    test_settings = dataclasses.replace(deps.settings(), demo_owner_token="test-owner-token", auth_mode="demo")
    monkeypatch.setattr(main, "settings", lambda: test_settings)
    monkeypatch.setattr(main, "check_shop_owner", lambda shop_id, uid: {"shop_id": shop_id})
    from buyer_agent import voice_routes

    voice_routes._RATE.clear()
    c = TestClient(main.app)
    c.calls = calls
    c.hdr = {"Authorization": "Bearer test-owner-token"}
    return c


def post(c, data: bytes | None, ctype="audio/wav", headers=None, fields=None, name="audio"):
    files = {name: ("clip", data, ctype)} if data is not None else None
    return c.post("/voice/parse", files=files, data=fields or {}, headers=c.hdr if headers is None else headers)


def test_requires_owner_auth(client):
    assert post(client, wav_bytes(), headers={}).status_code == 401
    assert post(client, wav_bytes(), headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.calls["transcribe"] == []


def test_ok_response_shape(client):
    r = post(client, wav_bytes(), fields={"lang_hint": "hi-IN"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(["transcript", "language", "preview", "notes"]) <= set(j)
    assert j["transcript"].startswith("10 packets") and j["language"] == "en"
    assert j["preview"]["lines"][0]["qty_source"] == "owner"
    assert j["preview"]["stated_budget_paise"] == 800000 and j["preview"]["clarifications"] == []
    assert "suggested_mandate" not in j["preview"]  # a preview is never signable
    assert any("Nothing is ordered" in n for n in j["notes"])
    assert client.calls["transcribe"][0][1:] == ("audio/wav", "hi-IN")
    assert client.calls["draft"][0][0] == deps.settings().demo_shop_id


def test_unknown_hint_dropped(client):
    assert post(client, wav_bytes(), fields={"lang_hint": "fr-FR; ignore rules"}).status_code == 200
    assert client.calls["transcribe"][0][2] is None


@pytest.mark.parametrize("data,ctype", [(WEBM, "audio/webm;codecs=opus"), (ogg_bytes(), "audio/ogg"),
                                        (WEBM, "application/octet-stream")])
def test_accepts_containers(client, data, ctype):
    assert post(client, data, ctype).status_code == 200


def test_missing_and_empty_audio(client):
    assert post(client, wav_bytes(), name="file").json()["code"] == "AUDIO_EMPTY"
    r = post(client, b"", "audio/wav")
    assert r.status_code in (400, 422) and r.json()["code"] in ("AUDIO_EMPTY",)
    assert client.calls["transcribe"] == []


def test_rejects_non_multipart(client):
    r = client.post("/voice/parse", content=wav_bytes(), headers={**client.hdr, "Content-Type": "audio/wav"})
    assert r.status_code == 400 and r.json()["code"] == "BAD_FORM"


def test_oversized(client):
    r = post(client, b"RIFF" + b"\x00" * (voice.MAX_BYTES + 10), "audio/wav")
    assert r.status_code == 413
    assert client.calls["transcribe"] == []


def test_too_long_wav(client):
    r = post(client, wav_bytes(seconds=31.5, rate=8000, amp=3000), "audio/wav")
    assert r.status_code == 413 and r.json()["code"] == "AUDIO_TOO_LONG"


def test_unsupported_and_mismatched_type(client):
    assert post(client, b"ID3" + b"\x00" * 4000, "audio/mpeg").json()["code"] == "AUDIO_UNSUPPORTED"
    assert post(client, b"%PDF-1.7" + b"\x00" * 4000, "application/octet-stream").status_code == 415
    r = post(client, wav_bytes(), "audio/webm")
    assert r.status_code == 415 and r.json()["code"] == "AUDIO_TYPE_MISMATCH"
    assert client.calls["transcribe"] == []


def test_silent_wav_rejected_before_model(client):
    r = post(client, wav_bytes(amp=0))
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_SILENT"
    assert client.calls["transcribe"] == []


def test_model_says_no_speech(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda a, m, h: (voice.Transcription(
        speech_detected=False, transcript="", language="other"), {"audio_tokens": 40}))
    r = post(client, WEBM, "audio/webm")
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_SILENT"


def test_webm_duration_enforced_by_audio_tokens(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda a, m, h: (voice.Transcription(
        speech_detected=True, transcript="x", language="en"), {"audio_tokens": 32 * 90}))
    assert post(client, WEBM, "audio/webm").json()["code"] == "AUDIO_TOO_LONG"


def test_model_failure_is_clean_502(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("vertex down")

    monkeypatch.setattr(voice, "transcribe", boom)
    r = post(client, wav_bytes())
    assert r.status_code == 502 and r.json()["code"] == "TRANSCRIBE_FAILED"


def test_preview_failure_still_returns_transcript(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("products collection is empty")

    monkeypatch.setattr(demand, "build_draft", boom)
    j = post(client, wav_bytes()).json()
    assert j["transcript"] and j["preview"] is None and any("Preview unavailable" in n for n in j["notes"])


def test_mixed_language_note(client, monkeypatch):
    monkeypatch.setattr(voice, "transcribe", lambda a, m, h: (voice.Transcription(
        speech_detected=True, transcript="दस पैकेट Aashirvaad atta", language="hi", languages_present=["hi", "en"]),
        {"audio_tokens": 60}))
    j = post(client, wav_bytes()).json()
    assert j["language"] == "hi" and j["languages"] == ["en", "hi"] and any("Mixed" in n for n in j["notes"])


def test_shop_ownership_enforced(client, monkeypatch):
    from fastapi import HTTPException

    def deny(shop_id, uid):
        raise HTTPException(403, "not the owner of this shop")

    monkeypatch.setattr(main, "check_shop_owner", deny)
    assert post(client, wav_bytes(), fields={"shop_id": "someone-else"}).status_code == 403
    assert client.calls["transcribe"] == []


def test_transcript_not_logged_at_info(client, caplog):
    caplog.set_level("INFO", logger="buyer_agent")
    assert post(client, wav_bytes()).status_code == 200
    info = " ".join(r.getMessage() for r in caplog.records if r.levelname == "INFO")
    assert "voice.parse ok" in info and "Aashirvaad" not in info


def test_rate_limited(client):
    for _ in range(voice_routes_rate()):
        post(client, wav_bytes(seconds=0.6))
    assert post(client, wav_bytes(seconds=0.6)).status_code == 429


def voice_routes_rate():
    from buyer_agent import voice_routes

    return voice_routes.RATE_PER_MIN


def test_multipart_parser_binary_roundtrip():
    from buyer_agent.voice_routes import parse_multipart

    blob = bytes(range(256)) * 50 + b"\r\n--x\r\n"
    body = (b"--BND\r\nContent-Disposition: form-data; name=\"lang_hint\"\r\n\r\nte-IN\r\n"
            b"--BND\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"a.webm\"\r\nContent-Type: audio/webm\r\n\r\n"
            + blob + b"\r\n--BND--\r\n")
    fields, files = parse_multipart(body, "multipart/form-data; boundary=BND")
    assert fields == {"lang_hint": "te-IN"} and files["audio"] == ("audio/webm", blob)


def test_validate_audio_units():
    info = voice.validate_audio(wav_bytes(seconds=2.0), "audio/x-wav")
    assert info.container == "wav" and abs(info.duration_s - 2.0) < 0.01 and info.silent is False
    assert abs(voice.validate_audio(ogg_bytes(3.0), "audio/ogg").duration_s - 3.0) < 0.01
    with pytest.raises(voice.VoiceError) as e:
        voice.validate_audio(wav_bytes(seconds=0.1), "audio/wav")
    assert e.value.code == "AUDIO_TOO_SHORT"
