"""Gemini structured-output call for evidence extraction (same pattern as buyer_agent.deps.gemini_json:
Vertex AI, low thinking, generous output budget). Imported lazily so tests never touch the network."""
from __future__ import annotations

import os
import threading

_lock = threading.Lock()
_client = None


def client():
    global _client
    if _client is None:
        with _lock:
            if _client is None:
                from google import genai

                _client = genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
                                       location=os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1"))
    return _client


def extract(data: bytes, mime: str, prompt: str, schema, *, system: str, max_tokens: int = 8192):
    """One multimodal call (file bytes + prompt) returning a parsed `schema` instance."""
    from google.genai import types

    cfg = types.GenerateContentConfig(
        temperature=0.0,
        max_output_tokens=max_tokens,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        response_mime_type="application/json",
        response_schema=schema,
        system_instruction=system,
    )
    contents = [types.Content(role="user", parts=[types.Part.from_bytes(data=data, mime_type=mime),
                                                  types.Part.from_text(text=prompt)])]
    resp = client().models.generate_content(model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash"),
                                            contents=contents, config=cfg)
    if getattr(resp, "parsed", None) is not None:
        return resp.parsed
    return schema.model_validate_json(resp.text or "{}")
