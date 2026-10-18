"""POST /mandates validates server-side (contract item 3): 422 with a readable message."""
import pytest


def _post(env, body):
    return env.client.post("/mandates", json={"kind": "intent", "body": body}, headers=env.auth("alice"))


def test_valid_mandate_signs_and_forces_tier_2(env):
    r = _post(env, env.mandate_body(autonomy_tier=3))
    assert r.status_code == 200
    m = env.client.get(f"/mandates/{r.json()['mandate_id']}", headers=env.auth("alice")).json()
    assert m["body"]["autonomy_tier"] == 2 and m["signature_valid"]


def _line(env, **kw):
    b = env.mandate_body()
    b["lines"][0].update(kw)
    return b


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: _line(e, gtin="0000000000000"), "not in the catalogue"),
    (lambda e: _line(e, qty=0), "qty"),
    (lambda e: _line(e, qty=5001), "qty"),
    (lambda e: _line(e, qty=2.5), "qty"),
    (lambda e: _line(e, qty="10"), "qty"),
    (lambda e: _line(e, ceiling_paise=0), "ceiling_paise"),
    (lambda e: _line(e, ceiling_paise=-100), "ceiling_paise"),
    (lambda e: _line(e, ceiling_paise=100.5), "ceiling_paise"),
    (lambda e: _line(e, ceiling_paise=10 ** 9), "above the reference ceiling"),
    (lambda e: {**e.mandate_body(), "lines": []}, "at least one line"),
    (lambda e: {**e.mandate_body(), "lines": [e.mandate_body()["lines"][0]] * 2}, "appears twice"),
    (lambda e: e.mandate_body(budget_paise=0), "budget_paise"),
    (lambda e: e.mandate_body(budget_paise=-5), "budget_paise"),
    (lambda e: e.mandate_body(budget_paise="1000"), "budget_paise"),
    (lambda e: e.mandate_body(budget_paise=1000.5), "budget_paise"),
    (lambda e: e.mandate_body(max_advance_pct=101), "max_advance_pct"),
    (lambda e: e.mandate_body(max_advance_pct=-1), "max_advance_pct"),
    (lambda e: e.mandate_body(deliver_by="2020-01-01"), "deliver_by"),
    (lambda e: e.mandate_body(deliver_by="soon"), "deliver_by"),
    (lambda e: e.mandate_body(expires_at="2020-01-01T00:00:00+05:30"), "future"),
    (lambda e: e.mandate_body(expires_at="2099-01-01T00:00:00+05:30"), "7 days"),
    (lambda e: e.mandate_body(allowed_supplier_ids=["metro", "fake-distributor"]), "registry"),
    (lambda e: e.mandate_body(allowed_supplier_ids=["metro", "metro"]), "distinct"),
    (lambda e: e.mandate_body(allowed_supplier_ids=["metro", "sharma", "quickstock", "x"]), "at most 3"),
])
def test_invalid_mandates_are_422(env, mutate, needle):
    r = _post(env, mutate(env))
    assert r.status_code == 422, r.text
    assert needle in r.json()["detail"]
    assert not env.db.data.get("mandates")  # nothing signed
