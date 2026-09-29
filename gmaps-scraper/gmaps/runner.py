from dataclasses import asdict, dataclass

from gmaps.normalize import dedupe_places, normalize
from gmaps.scraper import depth_for_limit

MAX_CONSECUTIVE_BAD = 3


@dataclass
class RunStats:
    searches_done: int = 0
    places_scraped: int = 0
    places_new: int = 0
    places_with_email: int = 0
    failed_searches: int = 0


def run(db, scrape, *, trigger: str, limit: int | None, default_depth: int, log=print,
        find_emails=None, pause=None) -> RunStats:
    db.reset_stale()
    run_id = db.create_run(trigger, limit)
    stats = RunStats()
    status, notes = "done", None
    bad_streak = 0
    first = True
    try:
        while True:
            if limit is not None and stats.places_new >= limit:
                notes = "limit reached"
                break
            if bad_streak >= MAX_CONSECUTIVE_BAD:
                notes = "possible proxy block"
                break
            search = db.claim_next_search(run_id)
            if search is None:
                break
            if pause is not None and not first:
                pause()
            first = False
            place_limit = search.get("place_limit")
            log(f"[run {run_id}] scraping: {search['query']} (client={search['client']})")
            try:
                result = scrape(search["query"], depth_for_limit(place_limit, default_depth))
                places = dedupe_places([normalize(e) for e in result.entries])
                if place_limit:
                    places = places[:place_limit]

                if find_emails is not None and places:
                    find_emails(places)

                if not places:
                    rc = result.returncode
                    error = result.stderr_tail or (f"exit {rc}" if rc else "0 results")
                    db.finish_search(search["id"], "failed", 0, 0, error)
                    stats.failed_searches += 1
                    bad_streak += 1
                    log(f"[run {run_id}]   failed: {error}")
                    continue

                new = db.upsert_places(places, search["client"], search["id"])
                db.finish_search(search["id"], "done", len(places), new)
                stats.searches_done += 1
                stats.places_scraped += len(places)
                stats.places_new += new
                stats.places_with_email += sum(1 for p in places if p["primary_email"])
                bad_streak = 0
                log(f"[run {run_id}]   {len(places)} places, {new} new (run total new: {stats.places_new})")
            except Exception as exc:
                db.finish_search(search["id"], "failed", 0, 0, repr(exc)[:2000])
                stats.failed_searches += 1
                bad_streak += 1
                log(f"[run {run_id}]   search failed: {exc!r}")
                continue
    except Exception as exc:
        status, notes = "failed", repr(exc)[:500]
        raise
    finally:
        db.finish_run(run_id, status, asdict(stats), notes)
    return stats
