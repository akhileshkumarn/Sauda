"""SupplierClient: agent-card fetch + registry fingerprint check (R2), A2A message/send with a text part
and a JSON data part, nonce/negotiation_id echo check, 20 s timeout (one retry, same nonce).

Speaks A2A JSON-RPC `message/send` (v0.3 wire format, which the ADK/a2a-sdk server accepts via its
v0.3 compat layer) directly over httpx: deterministic, and no model in the loop.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from .. import trust
from ..deps import settings

log = logging.getLogger("buyer_agent.a2a")
CARD_PATH = "/.well-known/agent-card.json"
_CARD_CACHE: dict[str, tuple[float, dict]] = {}
CARD_TTL_S = 600


class SupplierUnavailable(Exception):
    pass


class SupplierUnverified(Exception):
    pass


class SpoofSuspected(Exception):
    pass


@dataclass
class Reply:
    supplier_id: str
    text: str
    data: dict
    raw: dict = field(default_factory=dict)
    nonce: str = ""


def _is_local(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "0.0.0.0") or url.startswith("http://")


def _auth_headers(base_url: str) -> dict:
    if _is_local(base_url):
        return {}
    try:
        import google.auth.transport.requests
        from google.oauth2 import id_token

        tok = id_token.fetch_id_token(google.auth.transport.requests.Request(), base_url)
        return {"Authorization": f"Bearer {tok}"}
    except Exception as e:  # pragma: no cover - only on Cloud Run
        # Operator laptop (user ADC cannot mint audience tokens): fall back to the gcloud CLI identity token.
        try:
            import subprocess

            tok = subprocess.run(["gcloud", "auth", "print-identity-token"], capture_output=True, text=True,
                                 timeout=15, check=True).stdout.strip()
            if tok:
                return {"Authorization": f"Bearer {tok}"}
        except Exception:
            pass
        log.warning("could not fetch ID token for %s: %s", base_url, e)
        return {}


def base_url_for(sid: str, rec=None) -> str:
    url = settings().supplier_urls.get(sid)
    if url:
        return url
    card_url = (rec.agent_card_url if rec is not None else "") or ""
    return card_url.replace(CARD_PATH, "").rstrip("/")


def fetch_card(base_url: str, use_cache: bool = True) -> dict:
    hit = _CARD_CACHE.get(base_url)
    if use_cache and hit and time.time() - hit[0] < CARD_TTL_S:
        return hit[1]
    r = httpx.get(base_url + CARD_PATH, headers=_auth_headers(base_url), timeout=10)
    r.raise_for_status()
    card = r.json()
    _CARD_CACHE[base_url] = (time.time(), card)
    return card


def _rpc_url(card: dict, base_url: str) -> str:
    url = card.get("url")
    if not url:
        for itf in card.get("supportedInterfaces") or card.get("supported_interfaces") or []:
            if (itf.get("protocolBinding") or itf.get("protocol_binding") or "JSONRPC").upper() == "JSONRPC":
                url = itf.get("url")
                break
    # When running locally, cards may advertise a different host; always talk to the configured base.
    if not url or _is_local(base_url):
        return base_url + "/"
    return url


def _walk_parts(obj, texts: list[str], datas: list[dict]):
    """Collect text and data parts from an A2A result (Message or Task, v0.3 or v1 shapes)."""
    if isinstance(obj, dict):
        kind = obj.get("kind")
        if obj.get("role") in ("user", "ROLE_USER"):
            return  # never read our own echoed request from history
        if kind == "text" and isinstance(obj.get("text"), str):
            texts.append(obj["text"])
            return
        if kind == "data" and isinstance(obj.get("data"), dict):
            datas.append(obj["data"])
            return
        if "text" in obj and isinstance(obj["text"], str) and set(obj) <= {"text", "metadata", "mediaType", "media_type"}:
            texts.append(obj["text"])
            return
        if "data" in obj and isinstance(obj["data"], dict) and kind is None and set(obj) <= {"data", "metadata", "mediaType", "media_type"}:
            d = obj["data"]
            datas.append(d.get("data") if isinstance(d.get("data"), dict) and len(d) == 1 else d)
            return
        for k, v in obj.items():
            if k == "history":
                continue
            _walk_parts(v, texts, datas)
    elif isinstance(obj, list):
        for v in obj:
            _walk_parts(v, texts, datas)


def _find_payload(datas: list[dict], nid: str, nonce: str) -> dict | None:
    def rec(d):
        if isinstance(d, dict):
            if d.get("negotiation_id") == nid and d.get("nonce") == nonce:
                return d
            for v in d.values():
                r = rec(v)
                if r is not None:
                    return r
        elif isinstance(d, list):
            for v in d:
                r = rec(v)
                if r is not None:
                    return r
        return None

    for d in datas:
        r = rec(d)
        if r is not None:
            return r
    return None


class SupplierClient:
    def __init__(self, supplier_id: str, base_url: str, card: dict, record, card_fp: str, verified: bool):
        self.id = supplier_id
        self.base_url = base_url
        self.card = card
        self.record = record
        self.card_fingerprint = card_fp
        self.verified = verified
        self.name = getattr(record, "name", None) or card.get("name") or supplier_id

    @classmethod
    def load(cls, supplier_id: str) -> "SupplierClient":
        """Fetch the agent card and compare its fingerprint with the registry (R2). Raises if unreachable."""
        rec = trust.supplier(supplier_id)
        base = base_url_for(supplier_id, rec)
        if not base:
            raise SupplierUnavailable(f"no URL for supplier {supplier_id}")
        try:
            card = fetch_card(base)
        except Exception as e:
            raise SupplierUnavailable(f"{supplier_id}: card fetch failed: {e}") from e
        fp = trust.card_fingerprint(card)
        verified = trust.verify_card(supplier_id, card)
        if not verified and rec is not None:
            # a cached card may be stale after a supplier restart; refetch once before judging
            card = fetch_card(base, use_cache=False)
            fp = trust.card_fingerprint(card)
            verified = trust.verify_card(supplier_id, card)
        return cls(supplier_id, base, card, rec, fp, verified)

    def send(self, negotiation_id: str, data: dict, text: str, nonce: str | None = None) -> Reply:
        nonce = nonce or uuid.uuid4().hex
        payload = {**data, "negotiation_id": negotiation_id, "nonce": nonce}
        msg = {
            "kind": "message",
            "role": "user",
            "messageId": uuid.uuid4().hex,
            "parts": [{"kind": "text", "text": text}, {"kind": "data", "data": payload}],
            "metadata": {"negotiation_id": negotiation_id, "nonce": nonce},
        }
        body = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "message/send",
                "params": {"message": msg, "configuration": {"blocking": True}}}
        url = _rpc_url(self.card, self.base_url)
        last_err: Exception | None = None
        for _attempt in range(2):  # retried once with the same nonce (SM-4)
            try:
                r = httpx.post(url, json=body, headers={**_auth_headers(self.base_url), "Content-Type": "application/json"},
                               timeout=settings().a2a_timeout_s)
                r.raise_for_status()
                resp = r.json()
                break
            except Exception as e:
                last_err = e
        else:
            raise SupplierUnavailable(f"{self.id}: A2A send failed: {last_err}")
        if "error" in resp and resp.get("error"):
            raise SupplierUnavailable(f"{self.id}: A2A error {json.dumps(resp['error'])[:300]}")
        texts: list[str] = []
        datas: list[dict] = []
        _walk_parts(resp.get("result", resp), texts, datas)
        found = _find_payload(datas, negotiation_id, nonce)
        if found is None:
            raise SpoofSuspected(f"{self.id}: reply did not echo negotiation_id/nonce")
        return Reply(self.id, "\n".join(texts).strip(), found, resp, nonce)
