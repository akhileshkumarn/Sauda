"""Purge ledger chains that still carry an unmasked payee UPI ID (written before payees were masked at write time).

  uv run scripts/purge_demo_ledgers.py            # dry run: prints counts only, deletes nothing
  uv run scripts/purge_demo_ledgers.py --yes      # deletes

Scope: every negotiation of shop "demo", plus the attack chains attack-demo and attack-dev. A chain is tainted if
any event payload string contains a UPI ID that is not masked. A ledger chain cannot be partially deleted (the
links would break), so a tainted chain is removed whole: its ledger_events, its ledger_heads doc, and for a
negotiation also its negotiations, confirmations, orders, offers and cart_drafts docs. Mandates are not touched
(owner-only, never served publicly). The ledger is otherwise append-only; run this only with the owner's approval.
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv

load_dotenv()

from sauda_ledger import list_events  # noqa: E402
from sauda_ledger.events import COLLECTION, HEADS, doc_id  # noqa: E402
from sauda_trust.registry import VPA_RE  # noqa: E402

from buyer_agent import store  # noqa: E402
from buyer_agent.deps import db  # noqa: E402

SHOP = "demo"
ATTACK_CHAINS = ("attack-demo", "attack-dev")


def raw_vpas(v) -> int:
    """Count unmasked UPI IDs in a payload (a masked one reads '79••••357@ybl': skip matches right after '•')."""
    if isinstance(v, dict):
        return sum(raw_vpas(x) for x in v.values())
    if isinstance(v, list):
        return sum(raw_vpas(x) for x in v)
    if isinstance(v, str) and "@" in v:
        return sum(1 for m in VPA_RE.finditer(v) if not (m.start() > 0 and v[m.start() - 1] == "•"))
    return 0


def by_negotiation(coll: str, nid: str) -> list:
    return list(db().collection(coll).where("negotiation_id", "==", nid).stream())


def main(apply: bool) -> int:
    chains = [(n["negotiation_id"], True) for n in store.negotiations_for_shop(SHOP)] + [(c, False) for c in ATTACK_CHAINS]
    totals = {"chains_scanned": 0, "chains_tainted": 0, "raw_vpa_strings": 0, "ledger_events": 0, "ledger_heads": 0,
              "negotiations": 0, "confirmations": 0, "orders": 0, "offers": 0, "cart_drafts": 0}
    for nid, is_neg in chains:
        evs = list_events(nid)
        totals["chains_scanned"] += 1
        hits = sum(raw_vpas(e.get("payload") or {}) for e in evs)
        if not hits:
            continue
        totals["chains_tainted"] += 1
        totals["raw_vpa_strings"] += hits
        totals["ledger_events"] += len(evs)
        head = db().collection(HEADS).document(nid)
        has_head = head.get().exists
        totals["ledger_heads"] += int(has_head)
        related = {}
        if is_neg:
            related = {c: by_negotiation(c, nid) for c in ("confirmations", "orders", "offers", "cart_drafts")}
            totals["negotiations"] += 1
            for c, docs in related.items():
                totals[c] += len(docs)
        if apply:
            for e in evs:
                db().collection(COLLECTION).document(doc_id(nid, int(e["seq"]))).delete()
            if has_head:
                head.delete()
            for c, docs in related.items():
                for d in docs:
                    db().collection(c).document(d.id).delete()
            if is_neg:
                db().collection("negotiations").document(nid).delete()
    print(("DELETED" if apply else "DRY RUN (nothing deleted; pass --yes to delete)") + ":")
    for k, v in totals.items():
        print(f"  {k}: {v}")
    if apply and totals["chains_tainted"]:
        store.update_shop(SHOP, active_negotiation_id=None)
        print(f"  shop {SHOP}: active negotiation cleared")
    return 0


if __name__ == "__main__":
    sys.exit(main("--yes" in sys.argv[1:]))
