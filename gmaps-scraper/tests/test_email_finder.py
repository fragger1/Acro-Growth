import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from curl_cffi.requests.exceptions import ReadTimeout

from gmaps import email_finder
from gmaps.email_finder import contact_links, enrich_places, extract_emails, find_emails
from tests.fakes import FakeSession, page, redirect


def _cf_encode(email: str, key: int) -> str:
    encoded = [key]
    for ch in email:
        encoded.append(ord(ch) ^ key)
    return "".join(f"{b:02x}" for b in encoded)


def test_extract_emails_plain():
    assert extract_emails("contact us at hello@acme.com please") == ["hello@acme.com"]


def test_extract_emails_html_entity_encoded():
    assert extract_emails("mail: info&#64;acme.com") == ["info@acme.com"]


def test_extract_emails_cloudflare_protected():
    hex_value = _cf_encode("hi@acme.com", 0x42)
    html = f'<a href="/cdn-cgi/l/email-protection#{hex_value}" data-cfemail="{hex_value}">[email protected]</a>'
    assert extract_emails(html) == ["hi@acme.com"]


def test_extract_emails_no_filtering_returns_junk_too():
    # extract_emails does no filtering (that's clean_emails' job)
    result = extract_emails("test@test.com and real@acme.com")
    assert "test@test.com" in result
    assert "real@acme.com" in result


def test_contact_links_same_host_only_and_max_four_plus_fallbacks():
    html = """
    <a href="https://example.com/contact">Contact</a>
    <a href="https://facebook.com/contact">FB Contact</a>
    <a href="https://example.com/about">About</a>
    <a href="https://example.com/connect">Connect</a>
    <a href="https://example.com/wholesale">Wholesale</a>
    <a href="https://example.com/catering">Catering</a>
    <a href="https://example.com/info">Info</a>
    """
    links = contact_links(html, "https://example.com/")
    same_host_matches = [l for l in links if "facebook.com" not in l]
    assert links == same_host_matches
    # first 4 in-page matches, deduped, plus 3 fallbacks appended
    assert links[:4] == [
        "https://example.com/contact",
        "https://example.com/about",
        "https://example.com/connect",
        "https://example.com/wholesale",
    ]
    # /contact and /about are already present; only the new fallback is appended
    assert links[4:] == ["https://example.com/contact-us"]


def test_contact_links_never_follows_other_hosts():
    html = '<a href="https://facebook.com/contact">Contact</a>'
    links = contact_links(html, "https://example.com/")
    assert all("facebook.com" not in l for l in links)


def test_contact_links_www_insensitive_both_directions():
    # base has no www, link does: still same site.
    html = '<a href="https://www.acme.com/contact-us">Contact</a>'
    links = contact_links(html, "https://acme.com/")
    assert "https://www.acme.com/contact-us" in links

    # base has www, link doesn't: still same site.
    html2 = '<a href="https://acme.com/contact-us">Contact</a>'
    links2 = contact_links(html2, "https://www.acme.com/")
    assert "https://acme.com/contact-us" in links2


def test_contact_links_skips_binary_extensions():
    html = (
        '<a href="https://example.com/about.pdf">About PDF</a>'
        '<a href="https://example.com/contact">Contact</a>'
    )
    links = contact_links(html, "https://example.com/")
    assert "https://example.com/about.pdf" not in links
    assert "https://example.com/contact" in links


def test_href_and_cfemail_accept_single_quotes():
    html = "<a href='https://acme.com/contact'>Contact</a>"
    links = contact_links(html, "https://acme.com/")
    assert "https://acme.com/contact" in links

    hex_value = _cf_encode("hi@acme.com", 0x42)
    cf_html = f"<span data-cfemail='{hex_value}'>[email protected]</span>"
    assert extract_emails(cf_html) == ["hi@acme.com"]


def test_find_emails_follows_contact_link_and_cleans_junk():
    session = FakeSession({
        "https://acme.com": page('<a href="https://acme.com/contact-us-now">Contact</a>'),
        "https://acme.com/contact-us-now": page("info@acme.com or joe@gmail.com"),
    })
    assert find_emails("https://acme.com", session) == ["info@acme.com"]


@pytest.mark.parametrize("status_code", [403, 500])
def test_find_emails_homepage_error_status_returns_empty(status_code):
    session = FakeSession({"https://blocked.com/": page("info@blocked.com", status_code=status_code)})
    assert find_emails("https://blocked.com/", session) == []


def test_find_emails_homepage_raises_returns_empty():
    session = FakeSession({"https://unreachable.com": CurlConnectionError("boom")})
    assert find_emails("https://unreachable.com", session) == []


def test_find_emails_follows_cross_host_homepage_redirect():
    session = FakeSession({
        "https://oldsite.com/": redirect("https://newdomain.com/"),
        "https://newdomain.com/": page("info@newdomain.com"),
    })
    assert find_emails("https://oldsite.com/", session) == ["info@newdomain.com"]


def test_find_emails_skips_contact_page_that_redirects_to_other_host():
    session = FakeSession({
        "https://acme.com/": page('<a href="https://acme.com/contact">Contact</a>'),
        "https://acme.com/contact": redirect("https://forms.thirdparty.com/x", status_code=302),
        "https://forms.thirdparty.com/x": page("leak@thirdparty.com"),
    })
    assert find_emails("https://acme.com/", session) == []


def test_find_emails_homepage_non_html_content_type_returns_empty():
    session = FakeSession({"https://acme.com/": page(b"%PDF-1.4 email@acme.com", content_type="application/pdf")})
    assert find_emails("https://acme.com/", session) == []


def test_find_emails_skips_non_html_contact_page():
    session = FakeSession({
        "https://acme.com/": page('<a href="/contact">Contact</a>'),
        "https://acme.com/contact": page(b"%PDF-1.4 leak@acme.com", content_type="application/pdf"),
    })
    assert find_emails("https://acme.com/", session) == []


def test_find_emails_prefixes_schemeless_website_with_http():
    session = FakeSession(lambda url: page("info@acme.com"))
    assert find_emails("acme.com", session) == ["info@acme.com"]
    assert session.requested[0] == "http://acme.com"


def test_fetch_html_passes_redirect_and_timeout_limits():
    session = FakeSession({"https://acme.com/": page("hi")})
    email_finder._fetch_html(session, "https://acme.com/")
    assert session.stream_kwargs == [{
        "allow_redirects": True,
        "max_redirects": email_finder.MAX_REDIRECTS,
        "timeout": email_finder.REQUEST_TIMEOUT,
    }]


def test_fetch_html_too_many_redirects_returns_none():
    session = FakeSession({"https://acme.com/loop": redirect("https://acme.com/loop")})
    assert email_finder._fetch_html(session, "https://acme.com/loop") is None


def test_fetch_html_stops_after_wall_clock_deadline(monkeypatch):
    # Simulate a slow-trickling response: the monotonic clock jumps past the
    # 20s deadline right after the first chunk is read, so _fetch_html should
    # stop reading further chunks and return only what it already has,
    # instead of reading forever.
    times = iter([0.0])  # request-start timestamp

    def fake_monotonic():
        try:
            return next(times)
        except StopIteration:
            return 25.0  # every check after the first chunk reports "deadline passed"

    monkeypatch.setattr(email_finder.time, "monotonic", fake_monotonic)

    response = page(None, chunks=[b"first-chunk@acme.com ", b"second-chunk@acme.com"])
    session = FakeSession({"https://acme.com/": response})
    result = email_finder._fetch_html(session, "https://acme.com/")
    assert result is not None
    text, _final_url = result
    assert "first-chunk@acme.com" in text
    assert "second-chunk@acme.com" not in text
    assert response.chunks_read == 1


def test_fetch_html_stops_reading_at_max_bytes(monkeypatch):
    monkeypatch.setattr(email_finder, "MAX_BYTES", 10)
    response = page(None, chunks=[b"a" * 6, b"b" * 6, b"c" * 6])
    session = FakeSession({"https://acme.com/": response})
    text, _final_url = email_finder._fetch_html(session, "https://acme.com/")
    assert text == "a" * 6 + "b" * 6
    assert response.chunks_read == 2


def test_fetch_html_error_mid_body_returns_none():
    response = page(None, chunks=[b"partial@acme.com", ReadTimeout("stalled")])
    session = FakeSession({"https://acme.com/": response})
    assert email_finder._fetch_html(session, "https://acme.com/") is None


def test_fetch_html_decodes_with_response_encoding():
    response = page("café info@acme.com".encode("latin-1"), encoding="iso-8859-1")
    session = FakeSession({"https://acme.com/": response})
    text, _final_url = email_finder._fetch_html(session, "https://acme.com/")
    assert text == "café info@acme.com"


def test_fetch_html_unknown_charset_falls_back_to_utf8():
    response = page("café info@acme.com".encode(), encoding="not-a-real-charset")
    session = FakeSession({"https://acme.com/": response})
    text, _final_url = email_finder._fetch_html(session, "https://acme.com/")
    assert text == "café info@acme.com"


def test_fetch_html_returns_final_url_after_redirect():
    session = FakeSession({
        "http://acme.com": redirect("https://www.acme.com/home"),
        "https://www.acme.com/home": page("hi"),
    })
    assert email_finder._fetch_html(session, "http://acme.com") == ("hi", "https://www.acme.com/home")


class _LocalSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, body=b"", content_type="text/html", location=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        routes = {
            "/": (200, b'<a href="/contact-us-now">Contact</a>', "text/html; charset=utf-8", None),
            "/contact-us-now": (200, b"info@acme.com", "text/html", None),
            "/old": (301, b"", "text/html", "/"),
            "/blocked": (403, b"<h1>Forbidden</h1>", "text/html", None),
            "/file.pdf": (200, b"%PDF-1.4 x@acme.com", "application/pdf", None),
        }
        self._send(*routes.get(self.path, (404, b"not found", "text/html", None)))


@pytest.fixture
def local_site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _LocalSite)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_real_curl_cffi_session_against_local_site(local_site):
    # Exercises the real curl_cffi streaming API (not the fake) end to end.
    with email_finder.new_session() as session:
        assert email_finder._fetch_html(session, f"{local_site}/old") == (
            '<a href="/contact-us-now">Contact</a>', f"{local_site}/"
        )
        assert email_finder._fetch_html(session, f"{local_site}/blocked") is None
        assert email_finder._fetch_html(session, f"{local_site}/file.pdf") is None
        assert email_finder._fetch_html(session, "http://127.0.0.1:1/") is None
        assert find_emails(f"{local_site}/", session) == ["info@acme.com"]


def test_enrich_places_skips_no_website_and_existing_emails(monkeypatch):
    calls = []

    def fake_find_emails(website, session):
        calls.append(website)
        return ["info@acme.com"]

    monkeypatch.setattr(email_finder, "find_emails", fake_find_emails)

    places = [
        {"website": None, "domain": None, "emails": [], "primary_email": None},
        {"website": "https://acme.com", "domain": "already.com", "emails": ["x@already.com"],
         "primary_email": "x@already.com"},
        {"website": "https://acme.com", "domain": "acme.com", "emails": [], "primary_email": None},
    ]
    enrich_places(places)

    assert calls == ["https://acme.com"]
    assert places[0]["emails"] == [] and places[0]["primary_email"] is None
    assert places[1]["emails"] == ["x@already.com"]
    assert places[2]["emails"] == ["info@acme.com"]
    assert places[2]["primary_email"] == "info@acme.com"


def test_enrich_places_shares_one_chrome_impersonating_session(monkeypatch):
    sessions = []

    def fake_find_emails(website, session):
        sessions.append(session)
        return []

    monkeypatch.setattr(email_finder, "find_emails", fake_find_emails)

    places = [{"website": f"https://site{i}.com", "domain": None, "emails": []} for i in range(5)]
    enrich_places(places)

    assert len(sessions) == 5
    assert all(s is sessions[0] for s in sessions)
    assert isinstance(sessions[0], curl_requests.Session)
    assert sessions[0].impersonate == "chrome"
