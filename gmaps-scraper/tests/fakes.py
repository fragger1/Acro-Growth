from contextlib import contextmanager
from urllib.parse import urljoin

from curl_cffi.requests.exceptions import TooManyRedirects

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


REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class FakeResponse:
    """The parts of a streaming curl_cffi Response the email finder reads.

    chunks may include an exception, raised when iteration reaches it (an error mid-body).
    """

    def __init__(self, status_code=200, body="", headers=None, chunks=None, encoding="utf-8"):
        self.status_code = status_code
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        if chunks is None:
            chunks = [body.encode() if isinstance(body, str) else body]
        self.chunks = chunks
        self.encoding = encoding
        self.url = None
        self.chunks_read = 0

    def iter_content(self):
        for chunk in self.chunks:
            if isinstance(chunk, Exception):
                raise chunk
            self.chunks_read += 1
            yield chunk


def page(body, status_code=200, content_type="text/html", **kwargs):
    return FakeResponse(status_code, body, headers={"content-type": content_type}, **kwargs)


def redirect(location, status_code=301):
    return FakeResponse(status_code, headers={"location": location})


class FakeSession:
    """Stands in for the shared curl_cffi Session: serves routes[url] and follows redirects
    the way curl does, setting the response's final url. A route may be an exception to
    raise instead; unknown urls get a 404. routes may also be a function of the url."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []
        self.stream_kwargs = []

    def _respond(self, url):
        self.requested.append(url)
        response = self.routes(url) if callable(self.routes) else self.routes.get(url, FakeResponse(404))
        if isinstance(response, Exception):
            raise response
        return response

    @contextmanager
    def stream(self, method, url, allow_redirects=True, max_redirects=30, **kwargs):
        self.stream_kwargs.append({"allow_redirects": allow_redirects, "max_redirects": max_redirects, **kwargs})
        response = self._respond(url)
        followed = 0
        while allow_redirects and response.status_code in REDIRECT_STATUSES:
            followed += 1
            if followed > max_redirects:
                raise TooManyRedirects(f"Maximum ({max_redirects}) redirects followed")
            url = urljoin(url, response.headers["location"])
            response = self._respond(url)
        response.url = url
        yield response
