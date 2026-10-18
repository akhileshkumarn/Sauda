"""Supplier agent service: A2A (agent card + JSON-RPC at /) + GET /catalog + GET /health.

Run from the repo root:
  SUPPLIER_PROFILE=metro PORT=8001 uv run --package supplier-agent python -m supplier_agent.main
"""

from __future__ import annotations

import logging
import os

from .profile import REPO_ROOT, load_profile

try:  # local dev: pick up repo .env without overriding real env
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)
except Exception:  # noqa: BLE001
    pass

import uvicorn
from a2a.types import AgentCard
from google.adk.a2a.utils.agent_to_a2a import to_a2a
from google.protobuf.json_format import ParseDict
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from . import catalog
from .agent import SupplierExecutor, build_agent

PORT = int(os.environ.get("PORT", "8080"))
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{PORT}").rstrip("/")


def card_from_profile(profile: dict) -> AgentCard:
    skill = lambda sid, name, desc, tags: {
        "id": sid, "name": name, "description": desc, "tags": tags,
        "input_modes": ["application/json", "text/plain"], "output_modes": ["application/json", "text/plain"]}
    return ParseDict({
        "name": profile["id"],
        "description": f"{profile['name']}: {profile['description']}",
        "version": "1.0.0",
        "supported_interfaces": [{"url": PUBLIC_URL, "protocol_binding": "JSONRPC", "protocol_version": "1.0"}],
        "provider": {"organization": profile["name"], "url": PUBLIC_URL},
        "documentation_url": f"{PUBLIC_URL}/catalog",
        "capabilities": {"streaming": False, "push_notifications": False},
        "default_input_modes": ["application/json", "text/plain"],
        "default_output_modes": ["application/json", "text/plain"],
        "skills": [
            skill("quote", "Quote", "RFQ -> QUOTE (SPEC 11.2) from the deterministic quote engine", ["rfq", "quote"]),
            skill("revise", "Revise", "COUNTER -> REVISED with the published concession schedule", ["counter", "negotiation"]),
            skill("accept_po", "Accept PO", "PO -> PO_ACK", ["po", "order"]),
        ],
    }, AgentCard())


def build_app():
    profile = load_profile()
    app = to_a2a(build_agent(), port=PORT, agent_card=card_from_profile(profile),
                 agent_executor_factory=lambda runner: SupplierExecutor(runner))

    async def get_catalog(_: Request):
        return JSONResponse(catalog.build_catalog(profile))

    async def health(_: Request):
        return JSONResponse({"status": "ok", "supplier_id": profile["id"], "products": len(catalog.products()),
                             "products_source": catalog.products_path().name})

    app.router.routes.extend([Route("/catalog", get_catalog), Route("/health", health)])
    return app




def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    uvicorn.run(build_app(), host=os.environ.get("HOST", "0.0.0.0"), port=PORT)


if __name__ == "__main__":
    main()
