import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

from curl_cffi import CurlError
from curl_cffi import requests as curl_requests

from gmaps.emails import clean_emails, pick_primary

EMAIL_CANDIDATE_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
CF_EMAIL_RE = re.compile(r'''data-cfemail=["']([0-9a-fA-F]+)["']''')
HREF_RE = re.compile(r'''href=["']([^"']+)["']''', re.IGNORECASE)
CONTACT_PATH_RE = re.compile(r"contact|about|connect|wholesale|catering|info", re.IGNORECASE)
CONTACT_FALLBACKS = ("/contact", "/contact-us", "/about")
BINARY_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".zip", ".mp4", ".doc", ".docx",
)
MAX_CONTACT_LINKS = 4
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
REQUEST_TIMEOUT = 10
FETCH_DEADLINE_SECONDS = 20
# Many small-business sites sit behind bot protection that 403s any client whose TLS/HTTP2
# fingerprint isn't a real browser's, whatever User-Agent it sends, so fetch as Chrome
# (curl_cffi sets Chrome's headers, User-Agent included, to match).
IMPERSONATE = "chrome"


def _site_host(url: str) -> str:
    return (urlparse(url).netloc or "").lower().removeprefix("www.")


def _decode_cf_email(hex_value: str) -> str | None:
    try:
        data = bytes.fromhex(hex_value)
    except ValueError:
        return None
    if len(data) < 2:
        return None
    key = data[0]
    decoded = "".join(chr(b ^ key) for b in data[1:])
    return decoded


def extract_emails(html_text: str) -> list[str]:
    text = html.unescape(html_text or "")
    found = EMAIL_CANDIDATE_RE.findall(text)
    for hex_value in CF_EMAIL_RE.findall(html_text or ""):
        decoded = _decode_cf_email(hex_value)
        if decoded:
            found.append(decoded)
    return found


def contact_links(html_text: str, base_url: str) -> list[str]:
    base_host = _site_host(base_url)
    links: list[str] = []
    for href in HREF_RE.findall(html_text or ""):
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if _site_host(absolute) != base_host:
            continue
        if parsed.path.lower().endswith(BINARY_EXTENSIONS):
            continue
        if not CONTACT_PATH_RE.search(parsed.path):
            continue
        if absolute not in links:
            links.append(absolute)
        if len(links) >= MAX_CONTACT_LINKS:
            break
    for path in CONTACT_FALLBACKS:
        absolute = urljoin(base_url, path)
        if absolute not in links:
            links.append(absolute)
    return links


def _fetch_html(session: curl_requests.Session, url: str) -> tuple[str, str] | None:
    """GET url (redirects allowed), guarding against non-HTML content and oversized bodies.

    Returns (html_text, final_url) on a 200 HTML-ish response, else None. Never raises.
    """
    started = time.monotonic()
    try:
        with session.stream("GET", url, allow_redirects=True, max_redirects=MAX_REDIRECTS,
                            timeout=REQUEST_TIMEOUT) as response:
            if response.status_code != 200:
                return None
            content_type = response.headers.get("content-type", "")
            if content_type and "html" not in content_type.lower():
                return None
            body = bytearray()
            for chunk in response.iter_content():
                body.extend(chunk)
                if len(body) >= MAX_BYTES:
                    break
                if time.monotonic() - started >= FETCH_DEADLINE_SECONDS:
                    break
            try:
                text = bytes(body).decode(response.encoding, errors="replace")
            except LookupError:  # unknown charset in the Content-Type header
                text = bytes(body).decode("utf-8", errors="replace")
            return text, response.url
    except CurlError:
        return None


def find_emails(website: str, session: curl_requests.Session) -> list[str]:
    if "://" not in website:
        website = "http://" + website
    homepage = _fetch_html(session, website)
    if homepage is None:
        return []
    homepage_html, homepage_final_url = homepage
    site_host = _site_host(homepage_final_url)

    candidates = list(extract_emails(homepage_html))

    for link in contact_links(homepage_html, homepage_final_url):
        page = _fetch_html(session, link)
        if page is None:
            continue
        page_html, page_final_url = page
        if _site_host(page_final_url) != site_host:
            continue
        candidates.extend(extract_emails(page_html))

    return clean_emails(candidates)


def new_session() -> curl_requests.Session:
    return curl_requests.Session(impersonate=IMPERSONATE, timeout=REQUEST_TIMEOUT,
                                 max_redirects=MAX_REDIRECTS)


def enrich_places(places: list[dict], max_workers: int = 8) -> None:
    targets = [p for p in places if p.get("website") and not p.get("emails")]
    if not targets:
        return

    # One Session shared by all workers (curl_cffi gives each thread its own curl handle).
    with new_session() as session:
        def process(place: dict) -> None:
            try:
                emails = find_emails(place["website"], session)
            except Exception:
                emails = []
            place["emails"] = emails
            place["primary_email"] = pick_primary(emails, place.get("domain"))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(process, targets))
