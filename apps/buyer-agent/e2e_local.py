"""End-to-end over HTTP against a local buyer agent (Flows 1-4 + verify).

Prereqs: suppliers on 8001-8003, registry seeded (python -m buyer_agent.registry_seed), buyer on 8080:
  uv run --package buyer-agent uvicorn buyer_agent.main:app --port 8080
Run:
  uv run --package buyer-agent python apps/buyer-agent/e2e_local.py [--base http://localhost:8080] [--pay-utr 123456789012]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

try:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass

MESSAGE = "Diwali restock: 10 atta 5kg, 20 Tata salt, 12 Fortune oil 1L, 24 Parle-G, 24 Maggi"


def sse(client: httpx.Client, base: str, headers: dict, body: dict) -> list[tuple[str, dict]]:
    out = []
    with client.stream("POST", f"{base}/chat", json=body, headers=headers, timeout=600) as r:
        r.raise_for_status()
        ev = None
        for line in r.iter_lines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:") and ev:
                try:
                    data = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    data = {"raw": line[5:]}
                out.append((ev, data))
                show(ev, data)
                ev = None
    return out


def show(ev: str, d: dict) -> None:
    if ev == "agent.text":
        print(f"  [agent] {d.get('text', '')[:400]}")
    elif ev == "offer":
        print(f"  [offer] {d['supplier_id']} r{d['round']} {d.get('direction')} lines={len(d.get('lines', []))} "
              f"adv={d.get('advance_pct')} guard_blocked={d.get('guard_blocked')} gate={d.get('gate_verdict')} {d.get('reasons')}")
    elif ev == "guard.verdict":
        print(f"  [guard] {d['supplier_id']} r{d.get('round')} blocked={d['blocked']} {d.get('categories')}")
    elif ev == "gate.report":
        print(f"  [gate ] {d.get('action')} {d.get('supplier_id', '')} {d['verdict']} {d.get('reasons')}")
    elif ev in ("draft", "cart"):
        print(f"  [{ev}] {len(d.get('lines') or d.get('allocations') or [])} items")
    else:
        print(f"  [{ev}] {json.dumps(d)[:300]}")


def first(events, name):
    return next((d for e, d in events if e == name), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--shop", default=os.environ.get("DEMO_SHOP_ID", "demo"))
    ap.add_argument("--token", default=os.environ.get("DEMO_OWNER_TOKEN"), help="operator token (or env DEMO_OWNER_TOKEN)")
    ap.add_argument("--message", default=MESSAGE)
    ap.add_argument("--no-register", action="store_true", help="skip re-registering local suppliers (clears quarantine)")
    ap.add_argument("--pay-utr", default=None, help="also submit a manual UTR proof (only if you really paid)")
    a = ap.parse_args()
    if not a.token:
        ap.error("no operator token: pass --token or set DEMO_OWNER_TOKEN")
    H = {"Authorization": f"Bearer {a.token}"}
    c = httpx.Client(timeout=120)
    t0 = time.time()
    print("health:", c.get(f"{a.base}/health").json())
    if not a.no_register:
        from buyer_agent.registry_seed import register_all

        print("registry:", [r["supplier_id"] for r in register_all()])

    print("\n== Flow 1: draft ==")
    evs = sse(c, a.base, H, {"shop_id": a.shop, "message": a.message})
    draft = first(evs, "draft")
    assert draft, "no draft event"
    nid = draft["negotiation_id"]
    for l in draft["lines"]:
        print(f"   {l['qty']:>3} x {l['name']} ({l['gtin']}) ceiling ₹{l['ceiling_paise'] / 100:.2f} [{l['ceiling_source']}] - {l['reason']}")
    if draft.get("unmatched"):
        print("   unmatched:", draft["unmatched"])

    print("\n== Flow 1: sign intent mandate ==")
    r = c.post(f"{a.base}/mandates", json={"kind": "intent", "body": draft["suggested_mandate"], "negotiation_id": nid}, headers=H)
    r.raise_for_status()
    m = r.json()
    print("   mandate", m["mandate_id"], "hash", m["body_hash"][:16], "kms v", m["kms_key_version"])
    nid = m["negotiation_id"]

    print("\n== Flow 2/3: negotiate ==")
    evs = sse(c, a.base, H, {"shop_id": a.shop, "message": "Mandate signed. Please negotiate with the suppliers now."})
    conf = first(evs, "confirmation.request")
    qs_reasons = set()
    qs_blocked = False
    for e, d in evs:
        if d.get("supplier_id") == "quickstock":
            if e == "guard.verdict" and d.get("blocked"):
                qs_blocked = True
            if e == "gate.report":
                qs_reasons |= set(d.get("reasons") or [])
    print(f"   quickstock guard_blocked={qs_blocked} gate reasons={sorted(qs_reasons)}")
    assert conf, "no confirmation.request"

    print("\n== Flow 4: confirmation ==")
    v = c.get(f"{a.base}/confirm/{conf['confirmation_id']}", headers=H).json()
    cart = v["cart"]
    print(f"   cart total ₹{cart['total_paise'] / 100:,.2f} saved ₹{cart['savings_paise'] / 100:,.2f} ({cart.get('savings_pct')}%)")
    for w in cart.get("why", []):
        print("   why:", w["text"])
    print("   gate:", v["gate_report"]["verdict"], v["gate_report"].get("reasons"))
    r = c.post(f"{a.base}/confirm", json={"confirmation_id": conf["confirmation_id"], "approved": True}, headers=H, timeout=300)
    print("   confirm ->", r.status_code, r.text[:400])
    r.raise_for_status()
    res = r.json()
    assert res["status"] == "approved" and res["order_ids"], res
    for oid in res["order_ids"]:
        o = c.get(f"{a.base}/orders/{oid}", headers=H).json()
        print(f"   order {oid}: {o['order']['status']} ₹{o['order']['total_paise'] / 100:,.2f} PO ack={(o['order'].get('po_ack') or {}).get('status')}")
        print(f"     payment mandate {o.get('payment_mandate_id')} payee={o.get('payment_mandate', {}).get('payee_vpa')} amount={o.get('payment_mandate', {}).get('amount_paise')}")
        print(f"     {o.get('upi_link')}  qr={'yes' if (o.get('qr_data_url') or '').startswith('data:image') else 'no'}")
        if a.pay_utr:
            amt = o["payment_mandate"]["amount_paise"]
            print("     proof ->", c.post(f"{a.base}/payments/{oid}/proof", json={"utr": a.pay_utr, "amount_paise": amt}, headers=H).json())

    print("\n== Flow 5: verify ==")
    ver = c.get(f"{a.base}/verify/{nid}").json()
    print(f"   chain_ok={ver['chain_ok']} events={len(ver['events'])} first_broken={ver.get('first_broken_seq')}")
    print("   metrics:", c.get(f"{a.base}/metrics/{a.shop}").json())
    print(f"\nnegotiation_id={nid}  elapsed {time.time() - t0:.0f}s")
    ok = ver["chain_ok"] and (qs_blocked or {"ADVANCE_TOO_HIGH", "PAYEE_MISMATCH", "GUARD_BLOCKED"} & qs_reasons)
    print("E2E", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
