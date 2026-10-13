"""Keep only the leads in an export CSV whose name or website mentions given keywords.

Maps has no "commercial roofer" category, so commercial roofers are told apart from residential
ones by what their site says (TPO, EPDM, flat roofs, commercial...). This reads an export,
fetches each lead's homepage plus up to MAX_SERVICE_LINKS same-site pages whose path looks like
a services page, and writes the leads that mention any keyword to a new CSV.
"""
import csv
import html
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

from gmaps.email_finder import BINARY_EXTENSIONS, HREF_RE, _fetch_html, _site_host, new_session

COMMERCIAL_ROOFING_KEYWORDS = (
    "commercial", "industrial", "TPO", "EPDM", "PVC roofing", "flat roof", "modified bitumen",
    "built-up roof", "single-ply", "roof coating", "metal roofing", "standing seam", "warehouse",
)
SERVICE_PATH_RE = re.compile(r"commercial|industrial|service|roof", re.IGNORECASE)
MAX_SERVICE_LINKS = 3
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
MATCH_COLUMN = "site_keywords"


def page_text(html_text: str) -> str:
    """Visible-ish text of a page: scripts, styles and tags removed, entities decoded."""
    return html.unescape(TAG_RE.sub(" ", SCRIPT_STYLE_RE.sub(" ", html_text or "")))


def keyword_patterns(keywords) -> list[tuple[str, re.Pattern]]:
    # Word boundaries so "TPO" doesn't match inside "teapot"; spaces and hyphens are interchangeable.
    patterns = []
    for kw in keywords:
        body = r"[\s-]+".join(re.escape(part) for part in re.split(r"[\s-]+", kw.strip()) if part)
        if body:
            patterns.append((kw.strip(), re.compile(rf"\b{body}", re.IGNORECASE)))
    return patterns


def matching_keywords(text: str, patterns) -> list[str]:
    return [kw for kw, pattern in patterns if pattern.search(text or "")]


def service_links(html_text: str, base_url: str) -> list[str]:
    base_host = _site_host(base_url)
    links: list[str] = []
    for href in HREF_RE.findall(html_text or ""):
        absolute = urljoin(base_url, href).split("#", 1)[0]
        path = urlparse(absolute).path
        if _site_host(absolute) != base_host or path.lower().endswith(BINARY_EXTENSIONS):
            continue
        if not SERVICE_PATH_RE.search(path) or absolute in links:
            continue
        links.append(absolute)
        if len(links) >= MAX_SERVICE_LINKS:
            break
    return links


def site_keywords(website: str, session, patterns) -> list[str] | None:
    """Keywords found on the site's homepage and service pages, or None if the homepage
    couldn't be fetched."""
    if "://" not in website:
        website = "http://" + website
    homepage = _fetch_html(session, website)
    if homepage is None:
        return None
    homepage_html, final_url = homepage
    found = set(matching_keywords(page_text(homepage_html), patterns))
    for link in service_links(homepage_html, final_url):
        if len(found) == len(patterns):
            break
        fetched = _fetch_html(session, link)
        if fetched and _site_host(fetched[1]) == _site_host(final_url):
            found.update(matching_keywords(page_text(fetched[0]), patterns))
    return [kw for kw, _ in patterns if kw in found]


@dataclass
class FilterStats:
    matched: int = 0
    no_match: int = 0
    unreachable: int = 0
    no_website: int = 0
    keyword_counts: dict = field(default_factory=dict)


def filter_csv(in_path: Path, out_path: Path, keywords=COMMERCIAL_ROOFING_KEYWORDS, *,
               max_workers: int = 16, session=None) -> FilterStats:
    """Write the rows of in_path whose name or website mentions a keyword to out_path, with
    the keywords found in a site_keywords column. Leads with no website are kept only when
    their name matches; leads whose site can't be fetched are left out."""
    patterns = keyword_patterns(keywords)
    with in_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    def check(row: dict) -> tuple[str, list[str]]:
        found = set(matching_keywords(row.get("name", ""), patterns))
        website = (row.get("website") or "").strip()
        if not website:
            return ("matched" if found else "no_website"), [kw for kw, _ in patterns if kw in found]
        try:
            on_site = site_keywords(website, session, patterns)
        except Exception:
            on_site = None
        if on_site is None and not found:
            return "unreachable", []
        found.update(on_site or [])
        return ("matched" if found else "no_match"), [kw for kw, _ in patterns if kw in found]

    owns_session = session is None
    if owns_session:
        session = new_session()
    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(check, rows))
    finally:
        if owns_session:
            session.close()

    stats = FilterStats()
    kept = []
    for row, (outcome, found) in zip(rows, results):
        setattr(stats, outcome, getattr(stats, outcome) + 1)
        if outcome == "matched":
            kept.append({**row, MATCH_COLUMN: "; ".join(found)})
            for kw in found:
                stats.keyword_counts[kw] = stats.keyword_counts.get(kw, 0) + 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns + [MATCH_COLUMN], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)
    return stats
