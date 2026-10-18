"""Regressions: /verify with malformed events is 400; canonical JSON with non-ASCII text hashes the same in
the browser (apps/owner-app/lib/chain.ts) and on the server; an empty chain does not verify."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from sauda_ledger import build_event, genesis_hash, verify_chain
from sauda_trust.mandates import canonical, sha256_hex

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("events", [
    [{"seq": "x"}],
    [{"seq": {"a": 1}}],
    [{"seq": 1, "negotiation_id": 5, "payload": {}}],
    [{"seq": 1}, {"seq": None}],
])
def test_verify_malformed_events_400(env, events):
    r = env.client.post("/verify", json={"events": events})
    assert r.status_code == 400 and "malformed events" in r.json()["detail"]


def test_verify_non_list_is_422(env):
    assert env.client.post("/verify", json={"events": "nope"}).status_code == 422


def test_empty_chain_does_not_verify():
    assert verify_chain([]).chain_ok is False


TEXTS = {"note": "₹8,000 तक — दस पैकेट आटा, ಉಪ್ಪು, ñ, emoji 🪔", "kéy": "é", "á": 1, "z": [1, "मूल्य", {"y": None}]}


def test_canonical_non_ascii_is_raw_utf8():
    c = canonical(TEXTS).decode()
    assert "₹8,000 तक" in c and "\\u" not in c


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_browser_and_server_hash_agree_on_non_ascii(tmp_path):
    e1 = build_event("neg_ü", 1, genesis_hash("neg_ü"), "offer.received", "sharma", TEXTS)
    script = tmp_path / "h.mjs"
    script.write_text(
        f"import {{ canonical, sha256Hex }} from {json.dumps(str(ROOT / 'apps/owner-app/lib/chain.ts'))};\n"
        "const p = JSON.parse(process.argv[2]);\n"
        "console.log(JSON.stringify({c: canonical(p), h: await sha256Hex(canonical(p)), g: await sha256Hex(process.argv[3])}));\n")
    out = subprocess.run(["node", str(script), json.dumps(e1.payload, ensure_ascii=False), "neg_ü"],
                         capture_output=True, text=True, timeout=30)
    if out.returncode != 0 and "Unknown file extension" in out.stderr:
        pytest.skip("node cannot load .ts")
    assert out.returncode == 0, out.stderr
    js = json.loads(out.stdout)
    assert js["c"] == canonical(e1.payload).decode()
    assert js["h"] == e1.payload_hash == sha256_hex(canonical(TEXTS))
    assert js["g"] == genesis_hash("neg_ü")


def test_verify_body_limits_413(env):
    many = [{"seq": i} for i in range(2001)]
    assert env.client.post("/verify", json={"events": many}).status_code == 413
    big = [{"seq": 1, "payload": {"x": "a" * 1_100_000}}]
    assert env.client.post("/verify", json={"events": big}).status_code == 413
