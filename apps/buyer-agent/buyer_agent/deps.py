"""Settings from env and lazily created clients (Firestore, Gemini)."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache

try:  # local dev convenience; Cloud Run sets real env vars
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:  # pragma: no cover
    pass

# ADK / google-genai read these from the environment
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "true")
os.environ.setdefault("GOOGLE_CLOUD_LOCATION", "asia-south1")


def _supplier_urls(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip().rstrip("/")
    return out


@dataclass(frozen=True)
class Settings:
    project: str
    location: str
    gemini_model: str
    supplier_urls: dict[str, str] = field(default_factory=dict)
    demo_shop_id: str = "demo"
    owner_app_origin: str = "http://localhost:3000"
    auth_mode: str = "demo"  # firebase | demo
    demo_owner_token: str = ""
    agent_mode: str = "adk"  # adk | direct (deterministic router, no LLM tool-calling)
    a2a_timeout_s: float = 20.0
    cooling_off_min: int = 10
    confirmation_ttl_min: int = 15
    demo_pay_amount_paise: int | None = None
    use_model_armor: bool = True


@lru_cache(maxsize=1)
def settings() -> Settings:
    e = os.environ.get
    demo_amt = e("DEMO_PAY_AMOUNT_PAISE")
    return Settings(
        project=e("GOOGLE_CLOUD_PROJECT", ""),
        location=e("GOOGLE_CLOUD_LOCATION", "asia-south1"),
        gemini_model=e("GEMINI_MODEL", "gemini-3.5-flash"),
        supplier_urls=_supplier_urls(
            e("SUPPLIER_URLS", "metro=http://localhost:8001,sharma=http://localhost:8002,quickstock=http://localhost:8003")
        ),
        demo_shop_id=e("DEMO_SHOP_ID", "demo"),
        owner_app_origin=e("OWNER_APP_ORIGIN", "http://localhost:3000"),
        auth_mode=e("AUTH_MODE", "demo").lower(),
        demo_owner_token=e("DEMO_OWNER_TOKEN", ""),  # no default: operator auth is off unless the env sets it
        agent_mode=e("AGENT_MODE", "adk").lower(),
        a2a_timeout_s=float(e("A2A_TIMEOUT_S", "20")),
        cooling_off_min=int(e("COOLING_OFF_MIN", "10")),
        confirmation_ttl_min=int(e("CONFIRMATION_TTL_MIN", "15")),
        demo_pay_amount_paise=int(demo_amt) if demo_amt else None,
        use_model_armor=e("USE_MODEL_ARMOR", "true").lower() != "false",
    )


_lock = threading.Lock()
_clients: dict[str, object] = {}


def _lazy(name, factory):
    c = _clients.get(name)
    if c is None:
        with _lock:
            c = _clients.get(name)
            if c is None:
                c = factory()
                _clients[name] = c
    return c


def db():
    try:
        from sauda_trust import settings as ts

        return ts.firestore_client()
    except Exception:  # pragma: no cover
        from google.cloud import firestore

        return _lazy("firestore", lambda: firestore.Client(project=settings().project))


def genai_client():
    def make():
        from google import genai

        return genai.Client(vertexai=True, project=settings().project, location=settings().location)

    return _lazy("genai", make)


def gemini_json(prompt: str | list, schema, *, system: str | None = None, max_tokens: int = 8192):
    """Structured-output Gemini call (temperature 0.2). Returns a parsed pydantic instance or raises.
    Thinking tokens count against max_output_tokens; extraction needs little reasoning, so thinking is
    kept low and the budget generous (2048 truncated the JSON after ~1.8k thinking tokens)."""
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=0.2,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        response_mime_type="application/json",
        response_schema=schema,
        system_instruction=system,
    )
    resp = genai_client().models.generate_content(model=settings().gemini_model, contents=prompt, config=cfg)
    if resp.parsed is not None:
        return resp.parsed
    return schema.model_validate_json(resp.text)
