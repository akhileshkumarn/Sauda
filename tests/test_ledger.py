import copy

from sauda_ledger import build_event, genesis_hash, verify_chain


def _chain(nid="neg_test", n=5):
    evs, prev = [], genesis_hash(nid)
    for i in range(1, n + 1):
        e = build_event(nid, i, prev, "offer.received", f"s{i}", {"round": i, "price_paise": 1000 * i})
        evs.append(e.model_dump())
        prev = e.payload_hash
    return evs


def test_chain_verifies():
    checks = verify_chain(_chain())
    assert checks.chain_ok and len(checks) == 5
    assert all(c.hash_ok and c.link_ok and c.sig_ok for c in checks)


def test_edit_payload_breaks_from_that_seq():
    evs = copy.deepcopy(_chain())
    evs[2]["payload"]["price_paise"] = 1  # seq 3
    checks = verify_chain(evs)
    assert not checks.chain_ok and checks.first_broken_seq == 3
    assert [c.chain_ok for c in checks] == [True, True, False, False, False]
    assert not checks[2].hash_ok and not checks[3].link_ok


def test_reordered_or_deleted_event_breaks():
    evs = _chain()
    del evs[1]
    assert not verify_chain(evs).chain_ok


def test_wrong_key_breaks_signatures():
    from sauda_trust import kms
    evs = _chain()
    other = kms.LocalSigner().public_key_pem()
    assert not any(c.sig_ok for c in verify_chain(evs, public_key_pem=other))


# ---------------------------------------------------------------- v2 signature scope + signed head
import pytest  # noqa: E402
from sauda_ledger import build_head  # noqa: E402
from sauda_ledger.events import link_digest  # noqa: E402


@pytest.mark.parametrize("field,value", [("type", "payment.claimed"), ("actor", "owner"),
                                         ("ts", "2020-01-01T00:00:00+00:00"), ("negotiation_id", "neg_other")])
def test_v2_signature_covers_metadata(field, value):
    evs = copy.deepcopy(_chain())
    assert all(e["sig_version"] == 2 for e in evs)
    evs[1][field] = value
    checks = verify_chain(evs, negotiation_id="neg_test")
    assert not checks.chain_ok and not checks[1].sig_ok and checks[0].sig_ok


def test_legacy_v1_events_still_verify_and_are_labelled():
    from sauda_trust import kms
    nid, prev, evs = "neg_legacy", genesis_hash("neg_legacy"), []
    for i in range(1, 4):
        e = build_event(nid, i, prev, "offer.received", "s", {"i": i}).model_dump()
        s = kms.get_signer()
        e.update(signature=kms.b64(s.sign(link_digest(e["payload_hash"], e["prev_hash"]))), sig_version=1)
        e.pop("sig_version")  # stored legacy docs have no sig_version field at all
        evs.append(e)
        prev = e["payload_hash"]
    checks = verify_chain(evs)
    assert checks.chain_ok and all(c.sig_version == 1 and "legacy" in c.signature_scope for c in checks)
    evs[1]["type"] = "edited"  # legacy scope: metadata edits are not caught (documented residual risk)
    assert verify_chain(evs).chain_ok


def test_head_detects_tail_truncation_and_forgery():
    evs = _chain(n=5)
    good = build_head("neg_test", 5, evs[-1]["payload_hash"])
    checks = verify_chain(evs, head=good)
    assert checks.chain_ok and checks.head_ok is True
    truncated = verify_chain(evs[:3], head=good)
    assert truncated.head_ok is False and not truncated.chain_ok and "head_count" in truncated.head_problem
    forged = {**good, "count": 3, "last_hash": evs[2]["payload_hash"]}  # rewritten without the key
    assert verify_chain(evs[:3], head=forged).head_problem == "head_signature_invalid"
    other = build_head("neg_test", 5, "f" * 64)
    assert verify_chain(evs, head=other).head_problem == "head_last_hash_mismatch"
    assert verify_chain(evs).head_ok is None  # no head (in-memory copy / legacy chain)


def test_verify_route_reports_head_and_catches_truncation(env):
    nid, *_ = env.cart_ready()
    assert env.client.get(f"/verify/{nid}").json()["head_ok"] is True
    env.ledger.chains[nid].pop()  # tail event deleted from the store
    d = env.client.get(f"/verify/{nid}").json()
    assert d["head_ok"] is False and d["chain_ok"] is False
