from gmaps.scraper import ScrapeResult


class FakeDb:
    def __init__(self, searches=None, existing=None, leads=None):
        self.pending = list(searches or [])
        self.existing = existing or []
        self.leads = leads or []
        self.places: dict[tuple[str, str], dict] = {}
        self.finished_searches: list[tuple] = []
        self.runs: dict[int, dict] = {}
        self.inserted: list[dict] = []
        self.exports: list[tuple] = []
        self.reset_called = False

    def reset_stale(self):
        self.reset_called = True
        return 0

    def create_run(self, trigger, limit):
        run_id = len(self.runs) + 1
        self.runs[run_id] = {"trigger": trigger, "limit": limit}
        return run_id

    def finish_run(self, run_id, status, stats, notes):
        self.runs[run_id].update(status=status, stats=stats, notes=notes)

    def claim_next_search(self, run_id):
        return self.pending.pop(0) if self.pending else None

    def finish_search(self, search_id, status, found, new, error=None):
        self.finished_searches.append((search_id, status, found, new, error))

    def known_place_ids(self, place_ids):
        stored = {pid for pid, _client in self.places}
        return {pid for pid in place_ids if pid in stored}

    def upsert_places(self, places, client, search_id):
        new = 0
        for p in places:
            key = (p["place_id"], client)
            if key not in self.places:
                new += 1
            self.places[key] = p
        return new

    def existing_searches(self, client, queries):
        return [e for e in self.existing if e["query"] in queries]

    def insert_searches(self, rows):
        self.inserted += rows
        return len(rows)

    def fetch_leads(self, client, since, keyword, include_no_email, new_only):
        self.fetch_args = (client, since, keyword, include_no_email, new_only)
        return self.leads

    def record_export(self, client, filters, file_name, place_ids):
        self.exports.append((client, filters, file_name, place_ids))
        return len(self.exports)


def entry(pid, email=None):
    return {"place_id": pid, "title": pid, "web_site": "https://x.com", "emails": [email] if email else []}


def search(sid, client="me", place_limit=None):
    return {"id": sid, "query": f"q{sid}", "client": client, "place_limit": place_limit}


class ScriptedScraper:
    """Returns queued ScrapeResults in order; records (query, depth) calls."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, query, depth):
        self.calls.append((query, depth))
        return self.results.pop(0)


def ok(*entries):
    return ScrapeResult(list(entries), 0, "")
