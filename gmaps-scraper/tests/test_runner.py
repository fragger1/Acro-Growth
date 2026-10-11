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
    assert stats.searches_done == 1


def test_nonzero_exit_with_results_still_saves():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ScrapeResult([entry("a")], 1, "partial")])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches[0][1] == "done" and db.finished_searches[0][2] == 1


def test_zero_results_marked_failed_with_reason():
    # rc == 0 but no places found: no stderr, so the error falls back to "0 results".
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ok()])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches[0][1] == "failed"
    assert db.finished_searches[0][4] == "0 results"
    assert stats.failed_searches == 1
    assert stats.searches_done == 0
    assert db.places == {}


def test_three_bad_searches_in_a_row_stop_the_run():
    db = FakeDb([search(i) for i in range(1, 6)])
    scraper = ScriptedScraper([ScrapeResult([], 1, "x"), ok(), ScrapeResult([], 1, "y")])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(db.pending) == 2
    assert db.runs[1]["notes"] == "possible proxy block"
    assert stats.failed_searches == 3
    assert stats.searches_done == 0


def test_good_search_resets_bad_streak():
    db = FakeDb([search(i) for i in range(1, 6)])
    scraper = ScriptedScraper([ok(), ok(), ok(entry("a")), ok(), ok()])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(db.pending) == 0
    assert [f[1] for f in db.finished_searches] == ["failed", "failed", "done", "failed", "failed"]
    assert stats.searches_done == 1
    assert stats.failed_searches == 4


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


def test_find_emails_skips_places_already_in_db():
    # "a" was saved by an earlier search for another client; only "b" is unseen.
    db = FakeDb([search(1, client="jeff")])
    db.places[("a", "me")] = {"place_id": "a", "primary_email": "info@a.com"}
    scraper = ScriptedScraper([ok(entry("a"), entry("b"))])
    calls = []

    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet,
                find_emails=lambda places: calls.append([p["place_id"] for p in places]))

    assert calls == [["b"]]
    assert stats.places_scraped == 2 and stats.places_new == 2


def test_exception_marks_run_failed_and_reraises():
    """A run-level (DB) failure, not a per-search one, still fails the whole run
    and reraises. claim_next_search sits outside the per-search try/except."""

    class DeadDb(FakeDb):
        def claim_next_search(self, run_id):
            raise RuntimeError("kaboom")

    db = DeadDb([search(1)])
    scraper = ScriptedScraper([])
    try:
        run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    assert db.runs[1]["status"] == "failed" and "kaboom" in db.runs[1]["notes"]


def test_search_level_exception_isolated_run_still_done():
    """A per-search exception (e.g. upsert_places raising) fails only that search;
    the run continues and finishes 'done', not 'failed'."""

    class FlakyDb(FakeDb):
        def upsert_places(self, places, client, search_id):
            if search_id == 1:
                raise RuntimeError("db write failed")
            return super().upsert_places(places, client, search_id)

    db = FlakyDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(entry("a")), ok(entry("b"))])

    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)

    assert db.finished_searches[0][1] == "failed"
    assert "db write failed" in db.finished_searches[0][4]
    assert db.finished_searches[1][1] == "done"
    assert stats.failed_searches == 1
    assert stats.searches_done == 1
    assert db.runs[1]["status"] == "done"


def places(n, prefix="p"):
    return [entry(f"{prefix}{i}") for i in range(n)]


def test_first_page_only_result_is_retried_and_fuller_one_kept():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ok(*places(20)), ok(*places(80))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert scraper.calls == [("q1", 12), ("q1", 12)]
    assert db.finished_searches == [(1, "done", 80, 80, None)]
    assert stats.places_scraped == 80 and stats.searches_done == 1


def test_capped_search_retried_at_most_twice_then_kept():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(*places(20, "a")), ok(*places(20, "b")), ok(*places(20, "c")), ok(entry("z"))])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert [c[0] for c in scraper.calls] == ["q1", "q1", "q1", "q2"]
    assert db.finished_searches[0] == (1, "done", 20, 20, None)
    assert {pid for pid, _ in db.places} >= {f"a{i}" for i in range(20)}


def test_retries_keep_the_fullest_result():
    # A retry can come back with Maps' short version of the list; the earlier 20 is kept,
    # and the search is still retried while the best result so far is a capped 20.
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ok(*places(20, "a")), ok(*places(15, "b")), ok(*places(70, "c"))])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(scraper.calls) == 3
    assert db.finished_searches[0][2] == 70


def test_failed_retries_do_not_lose_the_capped_result():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ok(*places(20)), ScrapeResult([], 1, "boom"), ScrapeResult([], 1, "boom")])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches == [(1, "done", 20, 20, None)]
    assert stats.failed_searches == 0


def test_other_counts_are_not_retried():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(*places(19, "a")), ok(*places(21, "b"))])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert [c[0] for c in scraper.calls] == ["q1", "q2"]


def test_search_limited_to_20_or_fewer_places_is_not_retried():
    db = FakeDb([search(1, place_limit=20)])
    scraper = ScriptedScraper([ok(*places(20))])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(scraper.calls) == 1


def test_retry_pauses_first_and_logs_the_proxies_used():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ScrapeResult(places(20), 0, "", ["10.0.0.1:8001", "10.0.0.2:8002"]),
                               ScrapeResult(places(60), 0, "", ["10.0.0.3:8003"])])
    lines, pauses = [], []
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=lines.append,
        pause=lambda: pauses.append(1))
    assert len(pauses) == 1
    assert any("retrying" in line and "10.0.0.1:8001" in line for line in lines)
    assert any("60 places" in line and "10.0.0.3:8003" in line for line in lines)


def test_pause_runs_between_searches_but_not_before_the_first():
    db = FakeDb([search(1), search(2), search(3)])
    scraper = ScriptedScraper([ok(entry("a")), ok(entry("b")), ok(entry("c"))])
    pauses = []
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet, pause=lambda: pauses.append(1))
    assert len(pauses) == 2
