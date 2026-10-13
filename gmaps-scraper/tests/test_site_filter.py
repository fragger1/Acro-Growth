import csv

from gmaps.site_filter import (COMMERCIAL_ROOFING_KEYWORDS, filter_csv, keyword_patterns, matching_keywords,
                               page_text, service_links, site_keywords)
from tests.fakes import FakeSession, page

PATTERNS = keyword_patterns(COMMERCIAL_ROOFING_KEYWORDS)
COLUMNS = ["name", "category", "primary_email", "website"]


def _write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_page_text_drops_scripts_styles_and_tags():
    html = "<style>.commercial{}</style><script>var tpo=1</script><p>Flat&nbsp;roof <b>repair</b></p>"
    text = page_text(html)
    assert "commercial" not in text and "tpo" not in text
    assert matching_keywords(text, PATTERNS) == ["flat roof"]


def test_keywords_match_whole_words_case_insensitively_with_space_or_hyphen():
    assert matching_keywords("We install tpo and Single Ply systems", PATTERNS) == ["TPO", "single-ply"]
    assert matching_keywords("built up roofing", PATTERNS) == ["built-up roof"]
    assert matching_keywords("a teapot store", keyword_patterns(["TPO"])) == []


def test_service_links_same_site_paths_only():
    html = """
    <a href="/commercial-roofing">C</a>
    <a href="https://other.com/commercial">X</a>
    <a href="/services#top">S</a>
    <a href="/brochure-roof.pdf">P</a>
    <a href="/blog">B</a>
    <a href="/roof-repair">R</a>
    <a href="/industrial">I</a>
    """
    assert service_links(html, "https://acme.com/") == [
        "https://acme.com/commercial-roofing", "https://acme.com/services", "https://acme.com/roof-repair",
    ]


def test_site_keywords_reads_service_pages():
    session = FakeSession({
        "https://acme.com": page('<p>Roof repair</p><a href="/commercial">Commercial</a>'),
        "https://acme.com/commercial": page("<h1>TPO and EPDM</h1>"),
    })
    assert site_keywords("https://acme.com", session, PATTERNS) == ["commercial", "TPO", "EPDM"]


def test_site_keywords_none_when_homepage_unreachable():
    assert site_keywords("acme.com", FakeSession({}), PATTERNS) is None


def test_filter_csv_keeps_matching_leads(tmp_path):
    in_path, out_path = tmp_path / "in.csv", tmp_path / "out.csv"
    _write(in_path, [
        {"name": "Big Flat Roofs", "category": "Roofing contractor", "primary_email": "a@a.com",
         "website": "https://a.com"},
        {"name": "Home Shingles", "category": "Roofing contractor", "primary_email": "b@b.com",
         "website": "https://b.com"},
        {"name": "Down Site", "category": "Roofing contractor", "primary_email": "c@c.com",
         "website": "https://c.com"},
        {"name": "Industrial Roofing Co", "category": "Roofing contractor", "primary_email": "d@d.com",
         "website": ""},
        {"name": "Joe Roofing", "category": "Roofing contractor", "primary_email": "e@e.com", "website": ""},
    ])
    session = FakeSession({
        "https://a.com": page("<p>Commercial roof coatings</p>"),
        "https://b.com": page("<p>Residential shingles</p>"),
    })
    stats = filter_csv(in_path, out_path, max_workers=2, session=session)
    rows = _read(out_path)
    assert [r["name"] for r in rows] == ["Big Flat Roofs", "Industrial Roofing Co"]
    assert rows[0]["site_keywords"] == "commercial; flat roof; roof coating"
    assert rows[1]["site_keywords"] == "industrial"
    assert list(rows[0].keys()) == COLUMNS + ["site_keywords"]
    assert (stats.matched, stats.no_match, stats.unreachable, stats.no_website) == (2, 1, 1, 1)
    assert stats.keyword_counts["commercial"] == 1
