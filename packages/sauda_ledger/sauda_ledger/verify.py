"""Ledger verification. Accepts a negotiation_id (reads Firestore) or an in-memory list of event dicts
(Trust Console tamper demo verifies an edited client-side copy)."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sauda_trust import kms
from sauda_trust.mandates import canonical, sha256_hex

from .events import genesis_hash, get_head, head_digest, link_digest, list_events, sig_digest_v2


@dataclass
class EventCheck:
    seq: int
    type: str
    hash_ok: bool
    link_ok: bool
    sig_ok: bool
    chain_ok: bool = True  # this event and every earlier one verify
    sig_version: int = 1
    signature_scope: str = "legacy signature scope (payload + link only)"

    @property
    def ok(self) -> bool:
        return self.hash_ok and self.link_ok and self.sig_ok

    def to_dict(self) -> dict:
        return {**asdict(self), "ok": self.ok}


class ChainChecks(list):
    """list[EventCheck] with chain-level summary. head_ok: None = no signed head stored (legacy chain or an
    in-memory copy), True = head signature valid and count/last_hash match, False = truncated or rewritten."""

    head_ok: bool | None = None
    head_problem: str | None = None

    @property
    def chain_ok(self) -> bool:
        # an empty chain proves nothing; a failed head check means events were removed from the tail
        return len(self) > 0 and all(c.ok for c in self) and self.head_ok is not False

    @property
    def first_broken_seq(self) -> int | None:
        return next((c.seq for c in self if not c.ok), None)

    def to_dict(self) -> dict:
        return {"chain_ok": self.chain_ok, "first_broken_seq": self.first_broken_seq, "head_ok": self.head_ok,
                "head_problem": self.head_problem, "events": [c.to_dict() for c in self]}


def _pem_for(key_version: str, cache: dict) -> str:
    if key_version not in cache:
        from sauda_trust.mandates import _signer_for

        signer = kms.get_signer()
        cache[key_version] = (_signer_for(key_version) if key_version else signer).public_key_pem()
    return cache[key_version]


def check_head(head: dict | None, events: list[dict], negotiation_id: str, public_key_pem: str | None = None,
               cache: dict | None = None) -> tuple[bool | None, str | None]:
    if head is None:
        return None, None
    try:
        pem = public_key_pem or _pem_for(str(head.get("key_version", "")), cache if cache is not None else {})
        if not kms.verify_digest(head_digest(negotiation_id, int(head["count"]), str(head["last_hash"])),
                                 kms.unb64(head.get("sig", "")), pem):
            return False, "head_signature_invalid"
    except Exception:
        return False, "head_unreadable"
    if int(head["count"]) != len(events):
        return False, f"head_count_{head['count']}_events_{len(events)}"
    if not events or head["last_hash"] != events[-1].get("payload_hash"):
        return False, "head_last_hash_mismatch"
    return True, None


def verify_chain(source: str | list[dict], public_key_pem: str | None = None, negotiation_id: str | None = None,
                 db=None, head: dict | None = None) -> ChainChecks:
    """Accepts sig_version 2 (signs seq, ts, negotiation_id, type, actor, payload_hash, prev_hash) and legacy
    v1 (payload_hash + prev_hash only), each against the public key of its own key_version."""
    if isinstance(source, str):
        negotiation_id = negotiation_id or source
        events = list_events(source, db=db)
        if head is None:
            try:
                head = get_head(source, db=db)
            except Exception:
                head = None
    else:
        events = [e if isinstance(e, dict) else e.model_dump() for e in source]
    events = sorted(events, key=lambda e: int(e.get("seq", 0)))
    pems: dict[str, str] = {}
    out = ChainChecks()
    prev_recomputed = None
    all_ok = True
    for i, e in enumerate(events):
        nid = negotiation_id or e.get("negotiation_id", "")
        try:
            recomputed = sha256_hex(canonical(e.get("payload", {})))
        except Exception:
            recomputed = None
        hash_ok = recomputed is not None and recomputed == e.get("payload_hash")
        expected_prev = genesis_hash(nid) if i == 0 else prev_recomputed
        link_ok = (e.get("prev_hash") == expected_prev and int(e.get("seq", -1)) == i + 1
                   and e.get("negotiation_id", nid) == nid)
        v = 2 if e.get("sig_version") == 2 else 1
        try:
            pem = public_key_pem or _pem_for(str(e.get("key_version") or ""), pems)
            if v == 2:
                digest = sig_digest_v2(int(e["seq"]), str(e["ts"]), str(e["negotiation_id"]), str(e["type"]),
                                       str(e["actor"]), str(e["payload_hash"]), str(e["prev_hash"]))
            else:
                digest = link_digest(str(e.get("payload_hash")), str(e.get("prev_hash")))
            sig_ok = kms.verify_digest(digest, kms.unb64(e.get("signature", "")), pem)
        except Exception:
            sig_ok = False
        c = EventCheck(int(e.get("seq", 0)), str(e.get("type", "")), hash_ok, link_ok, sig_ok, sig_version=v,
                       signature_scope="full event (v2)" if v == 2 else "legacy signature scope (payload + link only)")
        all_ok = all_ok and c.ok
        c.chain_ok = all_ok
        out.append(c)
        prev_recomputed = recomputed
    if head is not None:
        out.head_ok, out.head_problem = check_head(head, events, negotiation_id or (events[0].get("negotiation_id", "") if events else ""),
                                                    public_key_pem, pems)
    return out
