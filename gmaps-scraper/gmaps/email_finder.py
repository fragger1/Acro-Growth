import html
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

import httpx

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
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


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
    base_host = urlparse(base_url).netloc
    links: list[str] = []
    for href in HREF_RE.findall(html_text or ""):
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.netloc != base_host:
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


def _fetch_html(client: httpx.Client, url: str) -> tuple[str, str] | None:
    """GET url (redirects allowed), guarding against non-HTML content and oversized bodies.

    Returns (html_text, final_url) on a 200 HTML-ish response, else None. Never raises.
    """
    try:
        with client.stream("GET", url, follow_redirects=True, timeout=REQUEST_TIMEOUT) as response:
            if response.status_code != 200:
                return None
            content_type = response.headers.get("content-type", "")
            if content_type and "html" not in content_type.lower():
                return None
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) >= MAX_BYTES:
                    break
            encoding = response.encoding or "utf-8"
            text = bytes(body).decode(encoding, errors="replace")
            return text, str(response.url)
    except httpx.HTTPError:
        return None


def find_emails(website: str, client: httpx.Client) -> list[str]:
    homepage = _fetch_html(client, website)
    if homepage is None:
        return []
    homepage_html, homepage_final_url = homepage
    site_host = _site_host(homepage_final_url)

    candidates = list(extract_emails(homepage_html))

    for link in contact_links(homepage_html, homepage_final_url):
        page = _fetch_html(client, link)
        if page is None:
            continue
        page_html, page_final_url = page
        if _site_host(page_final_url) != site_host:
            continue
        candidates.extend(extract_emails(page_html))

    return clean_emails(candidates)


def enrich_places(places: list[dict], max_workers: int = 8) -> None:
    targets = [p for p in places if p.get("website") and not p.get("emails")]
    if not targets:
        return

    with httpx.Client(follow_redirects=True, timeout=REQUEST_TIMEOUT, max_redirects=MAX_REDIRECTS,
                       headers={"User-Agent": USER_AGENT}) as client:
        def process(place: dict) -> None:
            try:
                emails = find_emails(place["website"], client)
            except Exception:
                emails = []
            place["emails"] = emails
            place["primary_email"] = pick_primary(emails, place.get("domain"))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(process, targets))
