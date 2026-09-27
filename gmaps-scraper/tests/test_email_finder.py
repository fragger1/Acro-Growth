import httpx
import pytest

from gmaps import email_finder
from gmaps.email_finder import contact_links, enrich_places, extract_emails, find_emails


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


def _make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_find_emails_follows_contact_link_and_cleans_junk():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            html = '<a href="https://acme.com/contact-us-now">Contact</a>'
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        if request.url.path == "/contact-us-now":
            return httpx.Response(200, text="info@acme.com or joe@gmail.com",
                                   headers={"content-type": "text/html"})
        return httpx.Response(404)

    client = _make_client(handler)
    result = find_emails("https://acme.com", client)
    assert result == ["info@acme.com"]


def test_find_emails_homepage_failure_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = _make_client(handler)
    assert find_emails("https://dead.com", client) == []


def test_find_emails_homepage_raises_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = _make_client(handler)
    assert find_emails("https://unreachable.com", client) == []


def test_find_emails_follows_cross_host_homepage_redirect():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oldsite.com" and request.url.path == "/":
            return httpx.Response(301, headers={"location": "https://newdomain.com/"})
        if request.url.host == "newdomain.com" and request.url.path == "/":
            return httpx.Response(200, text="info@newdomain.com", headers={"content-type": "text/html"})
        return httpx.Response(404)

    client = _make_client(handler)
    result = find_emails("https://oldsite.com/", client)
    assert result == ["info@newdomain.com"]


def test_find_emails_skips_contact_page_that_redirects_to_other_host():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "acme.com" and request.url.path == "/":
            html = '<a href="https://acme.com/contact">Contact</a>'
            return httpx.Response(200, text=html, headers={"content-type": "text/html"})
        if request.url.host == "acme.com" and request.url.path == "/contact":
            return httpx.Response(302, headers={"location": "https://forms.thirdparty.com/x"})
        if request.url.host == "forms.thirdparty.com":
            return httpx.Response(200, text="leak@thirdparty.com", headers={"content-type": "text/html"})
        return httpx.Response(404)

    client = _make_client(handler)
    result = find_emails("https://acme.com/", client)
    assert result == []


def test_contact_links_skips_binary_extensions():
    html = (
        '<a href="https://example.com/about.pdf">About PDF</a>'
        '<a href="https://example.com/contact">Contact</a>'
    )
    links = contact_links(html, "https://example.com/")
    assert "https://example.com/about.pdf" not in links
    assert "https://example.com/contact" in links


def test_find_emails_homepage_non_html_content_type_returns_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4 email@acme.com", headers={"content-type": "application/pdf"})

    client = _make_client(handler)
    assert find_emails("https://acme.com/", client) == []


def test_href_and_cfemail_accept_single_quotes():
    html = "<a href='https://acme.com/contact'>Contact</a>"
    links = contact_links(html, "https://acme.com/")
    assert "https://acme.com/contact" in links

    hex_value = _cf_encode("hi@acme.com", 0x42)
    cf_html = f"<span data-cfemail='{hex_value}'>[email protected]</span>"
    assert extract_emails(cf_html) == ["hi@acme.com"]


def test_enrich_places_skips_no_website_and_existing_emails(monkeypatch):
    calls = []

    def fake_find_emails(website, client):
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
