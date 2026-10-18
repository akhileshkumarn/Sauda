import pytest
from sauda_trust import kms


@pytest.fixture(autouse=True)
def local_signer():
    s = kms.LocalSigner()
    kms.set_signer(s)
    yield s
    kms.set_signer(None)


# ---------------------------------------------------------------- buyer-agent API test environment
import itertools  # noqa: E402

REG = {
    "sharma": {"supplier_id": "sharma", "name": "Sharma Traders", "agent_card_url": "http://sharma", "fingerprint": "fp_sharma",
               "payout_vpa": "sharma.registered@ybl", "status": "allowlisted"},
    "metro": {"supplier_id": "metro", "name": "Metro Wholesale", "agent_card_url": "http://metro", "fingerprint": "fp_metro",
              "payout_vpa": "metro.registered@ybl", "status": "allowlisted"},
    "quickstock": {"supplier_id": "quickstock", "name": "QuickStock", "agent_card_url": "http://qs", "fingerprint": "fp_qs",
                   "payout_vpa": "quickstock.registered@ybl", "status": "allowlisted"},
}


class Env:
    """Handles for one API test: fake db/ledger, a TestClient, and helpers to reach a pending confirmation."""

    def __init__(self, db, ledger, client, sends):
        self.db, self.ledger, self.client, self.sends = db, ledger, client, sends
        self._n = itertools.count(1)

    @staticmethod
    def auth(uid):
        return {"Authorization": f"Bearer uid-{uid}"}

    def products(self):
        from buyer_agent import store
        return list(store.products().items())

    def mandate_body(self, shop="demo", **kw):
        from datetime import datetime, timedelta, timezone
        ist = timezone(timedelta(hours=5, minutes=30))
        (g1, p1), (g2, p2) = self.products()[:2]
        body = {"kind": "intent", "shop_id": shop, "budget_paise": 1_000_000,
                "allowed_supplier_ids": ["metro", "sharma", "quickstock"],
                "lines": [{"gtin": g1, "qty": 10, "ceiling_paise": int(p1["mrp_paise"]), "ceiling_source": "mrp"},
                          {"gtin": g2, "qty": 5, "ceiling_paise": int(p2["mrp_paise"]), "ceiling_source": "mrp"}],
                "max_advance_pct": 20, "deliver_by": (datetime.now(ist).date() + timedelta(days=5)).isoformat(),
                "autonomy_tier": 2, "expires_at": (datetime.now(ist) + timedelta(hours=24)).replace(microsecond=0).isoformat()}
        body.update(kw)
        return body

    def cart_ready(self, uid="alice", shop="demo", factor=0.9, **mandate_kw):
        """Signed intent mandate + negotiation + clean sharma quote + cart draft + pending confirmation."""
        from buyer_agent import store, trust
        from buyer_agent.services import confirm
        body = self.mandate_body(shop, **mandate_kw)
        m = trust.create_mandate("intent", {**body, "owner_uid": uid}, uid)
        n = store.create_negotiation(shop, uid, nid=f"neg_test{next(self._n):06d}")
        nid = n["negotiation_id"]
        lines = [{"gtin": l["gtin"], "name": l["gtin"], "qty": l["qty"], "unit_price_paise": int(l["ceiling_paise"] * factor),
                  "opening_price_paise": l["ceiling_paise"], "ceiling_paise": l["ceiling_paise"], "ceiling_source": "mrp"}
                 for l in body["lines"]]
        store.save_offer({"negotiation_id": nid, "supplier_id": "sharma", "round": 1, "direction": "quote",
                          "lines": lines, "guard_verdict": "clean"})
        cart = {"allocations": [{"supplier_id": "sharma", "supplier_name": "Sharma Traders", "lines": lines,
                                 "subtotal_paise": sum(l["qty"] * l["unit_price_paise"] for l in lines),
                                 "delivery_days": 2, "advance_pct": 0, "payout_vpa": None}],
                "total_paise": sum(l["qty"] * l["unit_price_paise"] for l in lines), "savings_paise": 0,
                "opening_cost_paise": 0, "dropped_lines": [], "why": [], "status": "cart_ready"}
        cid = store.save_cart_draft(nid, cart)
        store.update_negotiation(nid, intent_mandate_id=m.mandate_id, status="cart_ready", cart_draft_id=cid)
        store.update_shop(shop, active_negotiation_id=nid)
        c = confirm.request(nid, cid, session_id="s", user_id=uid, mode="direct")
        return nid, cid, c["confirmation_id"], m.mandate_id

    def approve(self, conf_id, uid="alice", approved=True):
        return self.client.post("/confirm", json={"confirmation_id": conf_id, "approved": approved}, headers=self.auth(uid))


@pytest.fixture
def env(monkeypatch):
    import sauda_ledger
    import sauda_ledger.verify
    from fakes import FakeFirestore, FakeLedger
    from sauda_trust import settings as ts

    for k, v in {"AUTH_MODE": "firebase", "DEMO_OWNER_TOKEN": "op-token-for-tests", "DEMO_SHOP_ID": "demo",
                 "USE_MODEL_ARMOR": "false", "AGENT_MODE": "direct", "DEMO_PAY_AMOUNT_PAISE": ""}.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("DEMO_PAY_AMOUNT_PAISE")
    from buyer_agent import deps
    deps.settings.cache_clear()
    db = FakeFirestore()
    ledger = FakeLedger(db)
    ts.set_client("firestore", db)
    monkeypatch.setattr(sauda_ledger, "append", ledger.append)
    monkeypatch.setattr(sauda_ledger, "list_events", ledger.list_events)
    monkeypatch.setattr(sauda_ledger.verify, "list_events", ledger.list_events)

    from buyer_agent import main, store
    from buyer_agent.agent import tools
    from buyer_agent.services import demand, orders
    from sauda_data.products import load_csv

    for r in load_csv():
        if r.get("mrp_paise"):
            db.collection("products").document(str(r["gtin"])).set({**r, "gtin": str(r["gtin"])})
    for s in REG.values():
        db.collection("suppliers").document(s["supplier_id"]).set(dict(s))
    db.collection("shops").document("demo").set({"shop_id": "demo", "name": "Demo Kirana"})
    db.collection("shops").document("shopB").set({"shop_id": "shopB", "name": "Bob Stores", "owner_uid": "bob"})
    monkeypatch.setattr(store, "_products_cache", None)
    monkeypatch.setattr(demand, "_refs", lambda: {})
    monkeypatch.setattr(store, "claim_confirmation",
                        lambda cid, expected, **f: db.cas("confirmations", cid, "status", expected, f))

    def verify_fb(token):
        if token.startswith("uid-"):
            return token[4:]
        raise ValueError("bad token")
    monkeypatch.setattr(main, "_verify_firebase", verify_fb)
    monkeypatch.setattr(tools, "_card_fps", lambda sids: {s: REG[s]["fingerprint"] for s in sids if s in REG})

    sends = []

    class FakeSupplier:
        ack_status = "accepted"

        @classmethod
        def load(cls, sid):
            c = cls()
            c.sid = sid
            return c

        def send(self, nid, po, text, nonce):
            sends.append((self.sid, po["order_id"]))
            return type("R", (), {"data": {"type": "PO_ACK", "status": FakeSupplier.ack_status, "order_id": po["order_id"]}})()

    monkeypatch.setattr(orders, "SupplierClient", FakeSupplier)
    main._attack_hits.clear()
    main._owner_hits.clear()
    from fastapi.testclient import TestClient
    e = Env(db, ledger, TestClient(main.app, raise_server_exceptions=False), sends)
    e.FakeSupplier = FakeSupplier
    yield e
    ts.set_client("firestore", None)
    deps.settings.cache_clear()
