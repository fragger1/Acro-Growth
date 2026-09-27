from datetime import datetime, timedelta, timezone

from gmaps.queue import add_searches, build_query, parse_locations, plan_searches
from tests.fakes import FakeDb

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def test_parse_locations():
    assert parse_locations("Austin, TX; Dallas, TX\nHouston, TX ;; ") == ["Austin, TX", "Dallas, TX", "Houston, TX"]


def test_build_query():
    assert build_query(" dentists ", " Austin, TX ") == "dentists in Austin, TX"


def test_plan_creates_rows():
    rows, skipped = plan_searches("dentists", ["Austin, TX"], "Jeff", 200, [], NOW, False)
    assert rows == [{"keyword": "dentists", "location": "Austin, TX", "query": "dentists in Austin, TX",
                     "client": "jeff", "place_limit": 200}]
    assert skipped == []


def test_plan_skips_active_and_recent_but_not_old():
    existing = [
        {"query": "dentists in A", "status": "pending", "finished_at": None},
        {"query": "dentists in B", "status": "done", "finished_at": (NOW - timedelta(days=5)).isoformat()},
        {"query": "dentists in C", "status": "done", "finished_at": (NOW - timedelta(days=45)).isoformat()},
        {"query": "dentists in D", "status": "failed", "finished_at": (NOW - timedelta(days=1)).isoformat()},
    ]
    rows, skipped = plan_searches("dentists", ["A", "B", "C", "D"], "me", None, existing, NOW, False)
    assert [r["location"] for r in rows] == ["C", "D"]
    assert skipped == ["dentists in A", "dentists in B"]


def test_force_overrides_recent_but_not_active():
    existing = [
        {"query": "dentists in A", "status": "running", "finished_at": None},
        {"query": "dentists in B", "status": "done", "finished_at": (NOW - timedelta(days=5)).isoformat()},
    ]
    rows, skipped = plan_searches("dentists", ["A", "B"], "me", None, existing, NOW, True)
    assert [r["location"] for r in rows] == ["B"]
    assert skipped == ["dentists in A"]


def test_plan_dedupes_repeated_locations():
    rows, _ = plan_searches("dentists", ["A", "A"], "me", None, [], NOW, False)
    assert len(rows) == 1


def test_add_searches_inserts():
    db = FakeDb()
    added, skipped = add_searches(db, "roofers", "Tampa, FL; Miami, FL", "me", now=NOW)
    assert added == 2 and skipped == []
    assert db.inserted[1]["query"] == "roofers in Miami, FL"
