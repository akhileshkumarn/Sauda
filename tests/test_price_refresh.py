from datetime import date, timedelta

from sauda_data.price_refs import pick_ref
from sauda_data.refresh import should_replace

T = date(2026, 10, 18)
d = lambda n: (T - timedelta(days=n)).isoformat()  # noqa: E731


def test_same_doc_newer_replaces_older_never():
    assert should_replace(None, {"as_of": d(0)})
    assert should_replace({"as_of": d(1)}, {"as_of": d(0)})
    assert not should_replace({"as_of": d(0)}, {"as_of": d(1)})


def test_fresh_local_beats_newer_india():
    local, india = {"scope": "district", "as_of": d(1)}, {"scope": "india", "as_of": d(0)}
    assert pick_ref([india, local], T) is local


def test_stale_local_loses_to_fresh_india():
    local, india = {"scope": "district", "as_of": d(10)}, {"scope": "india", "as_of": d(0)}
    assert pick_ref([local, india], T) is india


def test_state_beats_india_when_both_fresh():
    st, india = {"scope": "state", "as_of": d(2)}, {"scope": "india", "as_of": d(0)}
    assert pick_ref([india, st], T) is st


def test_all_stale_freshest_wins():
    a, b = {"scope": "district", "as_of": d(30)}, {"scope": "india", "as_of": d(9)}
    assert pick_ref([a, b], T) is b
