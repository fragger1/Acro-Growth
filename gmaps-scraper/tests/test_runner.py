from gmaps.runner import run
from gmaps.scraper import ScrapeResult
from tests.fakes import FakeDb, ScriptedScraper, entry, ok, search


def quiet(*_):
    pass


def test_processes_all_searches_when_unlimited():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(entry("a", "i@x.com"), entry("b")), ok(entry("c"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.reset_called
    assert stats.searches_done == 2 and stats.places_scraped == 3 and stats.places_new == 3
    assert stats.places_with_email == 1
    assert [f[1] for f in db.finished_searches] == ["done", "done"]
    assert db.runs[1]["status"] == "done"


def test_stops_when_run_limit_reached_and_leaves_rest_pending():
    db = FakeDb([search(1), search(2), search(3)])
    scraper = ScriptedScraper([ok(entry("a"), entry("b")), ok(entry("c"), entry("d"))])
    stats = run(db, scraper, trigger="scheduled", limit=3, default_depth=12, log=quiet)
    assert stats.places_new == 4
    assert len(db.pending) == 1
    assert db.runs[1]["notes"] == "limit reached"


def test_repeat_places_do_not_count_as_new():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(entry("a")), ok(entry("a"), entry("b"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert stats.places_scraped == 3 and stats.places_new == 2


def test_per_search_limit_truncates_and_sets_depth():
    db = FakeDb([search(1, place_limit=2)])
    scraper = ScriptedScraper([ok(entry("a"), entry("b"), entry("c"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert stats.places_scraped == 2
    assert scraper.calls == [("q1", 1)]


def test_failed_search_marked_and_run_continues():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ScrapeResult([], 1, "boom"), ok(entry("a"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches[0][1] == "failed" and "boom" in db.finished_searches[0][4]
    assert db.finished_searches[1][1] == "done"
    assert stats.failed_searches == 1


def test_nonzero_exit_with_results_still_saves():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ScrapeResult([entry("a")], 1, "partial")])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches[0][1] == "done" and db.finished_searches[0][2] == 1


def test_three_bad_searches_in_a_row_stop_the_run():
    db = FakeDb([search(i) for i in range(1, 6)])
    scraper = ScriptedScraper([ScrapeResult([], 1, "x"), ok(), ScrapeResult([], 1, "y")])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(db.pending) == 2
    assert db.runs[1]["notes"] == "possible proxy block"


def test_good_search_resets_bad_streak():
    db = FakeDb([search(i) for i in range(1, 6)])
    scraper = ScriptedScraper([ok(), ok(), ok(entry("a")), ok(), ok()])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(db.pending) == 0


def test_find_emails_called_before_upsert_and_stats_reflect_enrichment():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ok(entry("a"), entry("b"))])
    calls = []

    def fake_find_emails(places):
        calls.append(list(places))
        # enrich only the first place
        places[0]["primary_email"] = "info@a.com"

    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet,
                find_emails=fake_find_emails)

    assert len(calls) == 1
    assert [p["place_id"] for p in calls[0]] == ["a", "b"]
    assert stats.places_with_email == 1
    assert db.places[("a", "me")]["primary_email"] == "info@a.com"


def test_exception_marks_run_failed_and_reraises():
    class Boom:
        def __call__(self, q, d):
            raise RuntimeError("kaboom")

    db = FakeDb([search(1)])
    try:
        run(db, Boom(), trigger="manual", limit=None, default_depth=12, log=quiet)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    assert db.runs[1]["status"] == "failed" and "kaboom" in db.runs[1]["notes"]
