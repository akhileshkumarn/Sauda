"""In-memory test doubles: a minimal Firestore client (collections, documents, equality queries, create
precondition) and an in-memory ledger built on the real build_event/verify code."""
from __future__ import annotations

import copy
import threading


class Conflict(Exception):
    pass


class _Snap:
    def __init__(self, data):
        self._d = data

    @property
    def exists(self):
        return self._d is not None

    def to_dict(self):
        return copy.deepcopy(self._d) if self._d is not None else None


class _Doc:
    def __init__(self, db, coll, doc_id):
        self.db, self.coll, self.id = db, coll, doc_id

    def get(self, **_):
        return _Snap(self.db.data.get(self.coll, {}).get(self.id))

    def set(self, data, merge=False):
        with self.db.lock:
            c = self.db.data.setdefault(self.coll, {})
            if merge and self.id in c:
                c[self.id].update(copy.deepcopy(data))
            else:
                c[self.id] = copy.deepcopy(data)

    def create(self, data):
        with self.db.lock:
            c = self.db.data.setdefault(self.coll, {})
            if self.id in c:
                raise Conflict(f"{self.coll}/{self.id} already exists")
            c[self.id] = copy.deepcopy(data)

    def update(self, fields):
        with self.db.lock:
            c = self.db.data.setdefault(self.coll, {})
            if self.id not in c:
                raise KeyError(self.id)
            c[self.id].update(copy.deepcopy(fields))


class _Query:
    def __init__(self, db, coll, filters=(), lim=None):
        self.db, self.coll, self.filters, self.lim = db, coll, list(filters), lim

    def where(self, field=None, op=None, value=None, filter=None):  # noqa: A002
        assert op in ("==", None)
        return _Query(self.db, self.coll, self.filters + [(field, value)], self.lim)

    def limit(self, n):
        return _Query(self.db, self.coll, self.filters, n)

    def stream(self, **_):
        rows = [(k, v) for k, v in self.db.data.get(self.coll, {}).items()
                if all(v.get(f) == val for f, val in self.filters)]
        rows = rows[: self.lim] if self.lim else rows
        return [_DocSnap(k, v) for k, v in rows]


class _DocSnap(_Snap):
    def __init__(self, doc_id, data):
        super().__init__(data)
        self.id = doc_id


class _Coll(_Query):
    def document(self, doc_id):
        return _Doc(self.db, self.coll, doc_id)


class FakeFirestore:
    def __init__(self):
        self.data: dict[str, dict[str, dict]] = {}
        self.lock = threading.RLock()

    def collection(self, name):
        return _Coll(self, name)

    # sessions._cas replacement (same semantics as the Firestore transaction: replace only at the expected value)
    def replace_if(self, coll, doc_id, field, expected, doc) -> bool:
        with self.lock:
            d = self.data.get(coll, {}).get(doc_id)
            if d is None or d.get(field) != expected:
                return False
            self.data[coll][doc_id] = copy.deepcopy(doc)
            return True

    # store.claim_confirmation replacement (same compare-and-set semantics as the Firestore transaction)
    def cas(self, coll, doc_id, field, expected, fields) -> bool:
        with self.lock:
            d = self.data.get(coll, {}).get(doc_id)
            if d is None or d.get(field) != expected:
                return False
            d.update(copy.deepcopy(fields))
            return True


class FakeLedger:
    def __init__(self, db: "FakeFirestore | None" = None):
        self.chains: dict[str, list[dict]] = {}
        self.lock = threading.Lock()
        self.db = db

    def append(self, nid, type_, actor, payload, db=None):
        from sauda_ledger import build_event, build_head, genesis_hash

        with self.lock:
            evs = self.chains.setdefault(nid, [])
            prev = evs[-1]["payload_hash"] if evs else genesis_hash(nid)
            e = build_event(nid, len(evs) + 1, prev, type_, actor, payload)
            evs.append(e.model_dump())
            if self.db is not None:  # same signed head the real append writes in its transaction
                self.db.collection("ledger_heads").document(nid).set(build_head(nid, e.seq, e.payload_hash))
            return e

    def list_events(self, nid, db=None):
        return copy.deepcopy(self.chains.get(nid, []))

    def types(self, nid):
        return [e["type"] for e in self.chains.get(nid, [])]
