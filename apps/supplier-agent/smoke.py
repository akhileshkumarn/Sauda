"""Tiny A2A client: RFQ (2 lines) then COUNTER round 2 against one supplier agent.

  uv run --package supplier-agent python apps/supplier-agent/smoke.py http://localhost:8001
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers.proto_helpers import new_data_part, new_message, new_text_part
from a2a.types import Role, SendMessageRequest
from google.protobuf.json_format import MessageToDict

ATTA, SALT = "8901725200015", "8901058000177"


async def send(client, payload: dict) -> dict:
    msg = new_message(parts=[new_text_part(f"{payload['type']} for negotiation {payload['negotiation_id']}"),
                             new_data_part(payload, media_type="application/json")], role=Role.ROLE_USER)
    out = {}
    async for item in client.send_message(SendMessageRequest(message=msg)):
        m = item.message if item.HasField("message") else None
        if m is None and item.HasField("task") and item.task.status.HasField("message"):
            m = item.task.status.message
        if m is not None:
            out["text"] = [p.text for p in m.parts if p.HasField("text")]
            out["data"] = [MessageToDict(p.data) for p in m.parts if p.HasField("data")]
    return out


async def main(url: str) -> None:
    async with httpx.AsyncClient(timeout=30) as http:
        client = await create_client(url, client_config=ClientConfig(httpx_client=http))
        nid = f"neg-smoke-{uuid.uuid4().hex[:6]}"
        rfq = {"type": "RFQ", "negotiation_id": nid, "nonce": uuid.uuid4().hex,
               "lines": [{"gtin": ATTA, "qty": 20}, {"gtin": SALT, "qty": 40}],
               "deliver_by": "2026-10-25", "max_advance_pct": 20, "respond_by": "2026-10-17T21:00:00+05:30"}
        r1 = await send(client, rfq)
        print("== QUOTE ==", json.dumps(r1, indent=1))
        q = {ln["gtin"]: ln["unit_price_paise"] for ln in r1["data"][0]["lines"]}
        counter = {"type": "COUNTER", "negotiation_id": nid, "nonce": uuid.uuid4().hex, "round": 2,
                   "bundle_note": "Diwali restock, both lines together",
                   "lines": [{"gtin": g, "qty": qty, "target_price_paise": int(q[g] * 0.93),
                              "match_price_paise": int(q[g] * 0.97)} for g, qty in ((ATTA, 20), (SALT, 40))]}
        r2 = await send(client, counter)
        print("== REVISED ==", json.dumps(r2, indent=1))
        for req, rep in ((rfq, r1), (counter, r2)):
            d = rep["data"][0]
            assert d["negotiation_id"] == req["negotiation_id"] and d["nonce"] == req["nonce"], "echo failed"
        print("echo ok")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"))
