from dataclasses import asdict, dataclass

from gmaps.normalize import dedupe_places, normalize
from gmaps.scraper import depth_for_limit

MAX_CONSECUTIVE_BAD = 3
# Maps returns search results 20 at a time. gosom used to stop scrolling whenever the next 20
# took longer than ~2s to arrive (a slow proxy), so exactly 20 results usually means only the
# first page loaded. The patched gosom waits for it; these retries are a safety net.
FIRST_PAGE_SIZE = 20
CAPPED_RETRIES = 2


def first_page_only(result, place_limit: int | None) -> bool:
    return len(result.entries) == FIRST_PAGE_SIZE and (not place_limit or place_limit > FIRST_PAGE_SIZE)


def _via(result) -> str:
    return f" via {result.proxies[0]}" if result.proxies else ""


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
                depth = depth_for_limit(place_limit, default_depth)
                result = scrape(search["query"], depth)
                for attempt in range(1, CAPPED_RETRIES + 1):
                    if not first_page_only(result, place_limit):
                        break
                    log(f"[run {run_id}]   {FIRST_PAGE_SIZE} places{_via(result)}, likely only the first page "
                        f"loaded; retrying with other proxies ({attempt}/{CAPPED_RETRIES})")
                    if pause is not None:
                        pause()
                    retry = scrape(search["query"], depth)
                    if len(retry.entries) > len(result.entries):
                        result = retry
                places = dedupe_places([normalize(e) for e in result.entries])
                if place_limit:
                    places = places[:place_limit]

                if find_emails is not None and places:
                    # Places already in the db had their websites checked when first saved, and the
                    # upsert keeps their stored emails, so only look up emails for unseen places.
                    known = db.known_place_ids([p["place_id"] for p in places])
                    find_emails([p for p in places if p["place_id"] not in known])

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
                log(f"[run {run_id}]   {len(places)} places, {new} new (run total new: {stats.places_new})"
                    f"{_via(result)}")
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
