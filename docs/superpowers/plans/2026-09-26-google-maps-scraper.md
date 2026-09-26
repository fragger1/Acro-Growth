# Google Maps Lead Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows-laptop CLI (`gmaps`) that works through a Supabase search queue, scrapes Google Maps with gosom (emails + proxies), stores deduplicated places tagged by client, and exports cold-email CSVs.

**Architecture:** Python orchestrator around the pinned gosom v1.18.1 Windows binary. Pure modules (`config`, `emails`, `normalize`, `queue` planning, `export` CSV writing, `runner` loop) are unit-tested offline with fakes. `db.py` is the only module that talks to Supabase. Atomic and set-based work (place upsert with email merge, search claiming, export selection) lives in Postgres functions called over RPC.

**Tech Stack:** Python 3.13 (venv via `py -3.13`), `supabase` 2.x, `python-dotenv`, `pytest`. gosom v1.18.1 (`google_maps_scraper-1.18.1-windows-amd64.exe`). Supabase Postgres 17, project ref `oinbyhfjffhgrucjwzkj`.

**Spec:** `docs/superpowers/specs/2026-09-26-google-maps-scraper-design.md`

## Global Constraints

- All project files live under `gmaps-scraper/` in the repo (the repo is the general AcroGrowth repo). Specs and plans stay in `docs/superpowers/` at the repo root.
- Secrets never enter git: `.env` and proxy files are gitignored. Never print proxy passwords or keys in logs or errors.
- Clients are free-text lowercase strings (`me`, `jeff`, …).
- A limit of `None` means unlimited, everywhere (run limit, per-search `place_limit`, `settings.nightly_limit`).
- Run limits count **new places for the search's client**.
- Stop a run after **3** consecutive failed-or-empty searches (`notes = "possible proxy block"`).
- Skip re-queueing a (query, client) that is pending/running, or finished `done` within **30 days**, unless `--force`.
- gosom JSON quirks: longitude field is spelled `longtitude`; website is `web_site`; the name is `title`; rating is `review_rating`.
- Strip heavy keys from `raw` before storing: `user_reviews`, `user_reviews_extended`, `images`, `popular_times` (keeps the Supabase free tier's 500 MB viable).
- Drop personal-inbox emails entirely (gmail, googlemail, yahoo, hotmail, outlook, live, msn, aol, icloud, me.com, proton, gmx, yandex, and ISP mail like comcast/att/verizon). Generic business inboxes (info@, contact@, …) are wanted.
- Supabase caps RPC/select responses at 1000 rows, so paginate reads with `.range()`.
- All tables have RLS enabled with no policies. Functions are executable by `service_role` only.

## File Structure

```
gmaps-scraper/
  pyproject.toml            package + deps + `gmaps` console script + pytest config
  .env.example              blank template (committed)
  .env                      real secrets (gitignored; moved from repo root in Task 1)
  gmaps/
    __init__.py
    __main__.py             `python -m gmaps`
    config.py               Config dataclass, load_config(), parse_proxy_line()
    emails.py               clean_emails(), site_domain(), pick_primary()
    normalize.py            normalize(entry) -> place dict | None, dedupe_places()
    scraper.py              ScrapeResult, depth_for_limit(), build_command(), parse_results(), GosomScraper
    db.py                   Db class (all Supabase access)
    runner.py               RunStats, run()
    queue.py                parse_locations(), build_query(), plan_searches(), add_searches()
    export.py               COLUMNS, write_csv(), export_leads()
    cli.py                  argparse entry point: run | queue add | export | status
  supabase/migrations/
    20260926000001_init.sql tables, indexes, view, functions, RLS, grants
  scripts/
    setup.ps1               download pinned gosom, create venv, install package
    register-task.ps1       register the nightly Windows scheduled task
  tests/
    fixtures/gosom_sample.jsonl
    fakes.py                FakeDb, fake scraper helpers
    test_config.py test_emails.py test_normalize.py test_scraper.py
    test_runner.py test_queue.py test_export.py
```

---

### Task 1: Project scaffold and config

**Files:**
- Create: `gmaps-scraper/pyproject.toml`, `gmaps-scraper/.env.example`, `gmaps-scraper/gmaps/__init__.py`, `gmaps-scraper/gmaps/__main__.py`, `gmaps-scraper/gmaps/config.py`
- Move: repo-root `.env` → `gmaps-scraper/.env`
- Test: `gmaps-scraper/tests/test_config.py`

**Interfaces:**
- Produces: `Config(supabase_url: str, supabase_key: str, proxies: list[str], gosom_path: Path)`, `load_config() -> Config`, `parse_proxy_line(line: str) -> str | None`, `ROOT: Path` (the `gmaps-scraper/` dir).

- [ ] **Step 1: Create scaffold files**

`gmaps-scraper/pyproject.toml`:
```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "gmaps-scraper"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = ["supabase>=2.10,<3", "python-dotenv>=1.0"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
gmaps = "gmaps.cli:main"

[tool.setuptools]
packages = ["gmaps"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`gmaps-scraper/.env.example`:
```
SUPABASE_URL=
SUPABASE_SECRET_KEY=
# Path to proxies file, one per line: ip:port:user:pass (Webshare export format) or full URLs
PROXIES_FILE=
# Optional override; defaults to bin/google-maps-scraper.exe
GOSOM_PATH=
```

`gmaps-scraper/gmaps/__init__.py` and `gmaps-scraper/tests/__init__.py`: empty files.

`gmaps-scraper/gmaps/__main__.py`:
```python
from gmaps.cli import main

main()
```

Move the secrets file (do not print its contents):
```bash
cd C:/Users/Hi/AcroGrowth/.claude/worktrees/google-maps-scraper-supabase-f9f3eb
mkdir -p gmaps-scraper && mv .env gmaps-scraper/.env && git check-ignore gmaps-scraper/.env
```
Expected: prints `gmaps-scraper/.env` (ignored).

Create the venv and install:
```bash
cd gmaps-scraper && py -3.13 -m venv .venv && .venv/Scripts/python -m pip install -q -e ".[dev]"
```

- [ ] **Step 2: Write the failing test** — `gmaps-scraper/tests/test_config.py`
```python
import pytest

from gmaps.config import parse_proxy_line


def test_webshare_format_becomes_http_url():
    assert parse_proxy_line("1.2.3.4:6754:user:pass\n") == "http://user:pass@1.2.3.4:6754"


def test_host_port_only():
    assert parse_proxy_line("1.2.3.4:8080") == "http://1.2.3.4:8080"


def test_full_url_passes_through():
    assert parse_proxy_line("socks5://u:p@host:1080") == "socks5://u:p@host:1080"


@pytest.mark.parametrize("line", ["", "   ", "# comment"])
def test_blank_and_comment_lines_skipped(line):
    assert parse_proxy_line(line) is None


def test_bad_line_error_does_not_leak_password():
    with pytest.raises(ValueError) as exc:
        parse_proxy_line("1.2.3.4:1:user")
    assert "user" not in str(exc.value)
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: FAIL (`ModuleNotFoundError: gmaps.config`)

- [ ] **Step 4: Implement** — `gmaps-scraper/gmaps/config.py`
```python
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_key: str
    proxies: list[str]
    gosom_path: Path


def parse_proxy_line(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = line.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    raise ValueError(f"Unrecognized proxy line for host {parts[0]!r}; expected ip:port:user:pass")


def _load_proxies(path: str | None) -> list[str]:
    if not path:
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [p for p in (parse_proxy_line(line) for line in lines) if p]


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in gmaps-scraper/.env")
    gosom = os.environ.get("GOSOM_PATH", "").strip()
    return Config(
        supabase_url=url,
        supabase_key=key,
        proxies=_load_proxies(os.environ.get("PROXIES_FILE", "").strip() or None),
        gosom_path=Path(gosom) if gosom else ROOT / "bin" / "google-maps-scraper.exe",
    )
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_config.py -v`
Expected: 7 passed. Also run `.venv/Scripts/python -c "from gmaps.config import load_config; c=load_config(); print(len(c.proxies), c.supabase_url)"` and expect `10 https://oinbyhfjffhgrucjwzkj.supabase.co`.

- [ ] **Step 6: Commit**
```bash
git add gmaps-scraper/pyproject.toml gmaps-scraper/.env.example gmaps-scraper/gmaps gmaps-scraper/tests
git status --short   # confirm no .env staged
git commit -m "feat(gmaps): project scaffold and config loading"
```

---

### Task 2: Email cleaning and primary-email picking

**Files:**
- Create: `gmaps-scraper/gmaps/emails.py`
- Test: `gmaps-scraper/tests/test_emails.py`

**Interfaces:**
- Produces: `clean_emails(raw: list[str] | None) -> list[str]`, `site_domain(website: str | None) -> str | None`, `pick_primary(emails: list[str], domain: str | None) -> str | None`

- [ ] **Step 1: Write the failing test** — `tests/test_emails.py`
```python
from gmaps.emails import clean_emails, pick_primary, site_domain


def test_clean_lowercases_dedupes_and_strips_mailto():
    assert clean_emails(["Info@Acme.com", "mailto:info@acme.com", " sales@acme.com "]) == [
        "info@acme.com",
        "sales@acme.com",
    ]


def test_clean_drops_junk():
    raw = [
        "logo@2x.png",
        "user@example.com",
        "abc123@sentry.io",
        "x@sentry-next.wixpress.com",
        "not-an-email",
        "yourname@acme.com",
        "real@acme.com",
    ]
    assert clean_emails(raw) == ["real@acme.com"]


def test_clean_drops_personal_inboxes():
    raw = [
        "joe@gmail.com", "a@googlemail.com", "b@yahoo.com", "c@yahoo.co.uk", "d@hotmail.com",
        "e@outlook.com", "f@live.com", "g@aol.com", "h@icloud.com", "i@me.com", "j@comcast.net",
        "k@proton.me", "info@acme.com", "sales@acme.com",
    ]
    assert clean_emails(raw) == ["info@acme.com", "sales@acme.com"]


def test_clean_keeps_business_domains_that_start_like_providers():
    assert clean_emails(["info@livemusicaustin.com", "hi@outlookdental.com"]) == [
        "info@livemusicaustin.com",
        "hi@outlookdental.com",
    ]


def test_clean_handles_none():
    assert clean_emails(None) == []


def test_clean_strips_query_string():
    assert clean_emails(["hello@acme.com?subject=hi"]) == ["hello@acme.com"]


def test_site_domain():
    assert site_domain("https://www.Acme.com/contact") == "acme.com"
    assert site_domain("acme.com") == "acme.com"
    assert site_domain(None) is None
    assert site_domain("") is None


def test_primary_prefers_role_address_on_own_domain():
    emails = ["john@acme.com", "sales@acme.com", "info@acme.com"]
    assert pick_primary(emails, "acme.com") == "info@acme.com"


def test_primary_falls_back_to_first_own_domain():
    assert pick_primary(["x@agency.com", "john@acme.com"], "acme.com") == "john@acme.com"


def test_primary_subdomain_website_matches_root_email():
    assert pick_primary(["office@acme.com"], "shop.acme.com") == "office@acme.com"


def test_primary_falls_back_to_first_any():
    assert pick_primary(["x@agency.com", "b@other.com"], "acme.com") == "x@agency.com"


def test_primary_empty():
    assert pick_primary([], "acme.com") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_emails.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** — `gmaps/emails.py`
```python
import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
FILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".js", ".css", ".pdf")
BLOCKED_DOMAINS = {
    "example.com", "example.org", "domain.com", "email.com", "yourdomain.com", "yoursite.com",
    "mysite.com", "company.com", "test.com", "sentry.io", "wixpress.com", "wix.com",
    "squarespace.com", "godaddy.com", "cloudflare.com", "sentry-next.wixpress.com",
}
BLOCKED_LOCAL_PARTS = {
    "example", "yourname", "your.name", "name", "email", "youremail", "your.email",
    "user", "username", "test", "johndoe", "john.doe",
}
PREFERRED_LOCAL_PARTS = ("info", "contact", "office", "hello", "admin")

# Personal inboxes are never wanted for cold email. Generic business inboxes are fine.
PERSONAL_BRANDS = {
    "gmail", "googlemail", "yahoo", "ymail", "rocketmail", "hotmail", "outlook", "live", "msn",
    "aol", "icloud", "gmx", "yandex", "protonmail",
}
PERSONAL_DOMAINS = {
    "me.com", "mac.com", "proton.me", "pm.me", "mail.com", "comcast.net", "att.net",
    "sbcglobal.net", "verizon.net", "bellsouth.net", "cox.net", "charter.net", "earthlink.net",
    "optonline.net", "frontier.com", "windstream.net", "rogers.com", "shaw.ca", "sympatico.ca",
    "btinternet.com", "sky.com", "qq.com", "163.com",
}


def _is_personal(domain: str) -> bool:
    if domain in PERSONAL_DOMAINS:
        return True
    brand, _, suffix = domain.partition(".")
    # brand + short public suffix only: yahoo.com, yahoo.co.uk, live.fr (not livemusicaustin.com)
    return brand in PERSONAL_BRANDS and len(suffix) <= 6


def _domain_blocked(domain: str) -> bool:
    return _is_personal(domain) or any(domain == d or domain.endswith("." + d) for d in BLOCKED_DOMAINS)


def clean_emails(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        email = (item or "").strip().lower().removeprefix("mailto:").split("?")[0]
        if email.endswith(FILE_EXTENSIONS) or not EMAIL_RE.match(email):
            continue
        local, domain = email.rsplit("@", 1)
        if _domain_blocked(domain) or local in BLOCKED_LOCAL_PARTS:
            continue
        if email not in out:
            out.append(email)
    return out


def site_domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "://" in website else "http://" + website).hostname or ""
    host = host.lower().removeprefix("www.")
    return host or None


def _on_domain(email: str, domain: str | None) -> bool:
    if not domain:
        return False
    email_domain = email.rsplit("@", 1)[1]
    return (
        email_domain == domain
        or email_domain.endswith("." + domain)
        or domain.endswith("." + email_domain)
    )


def pick_primary(emails: list[str], domain: str | None) -> str | None:
    if not emails:
        return None
    own = [e for e in emails if _on_domain(e, domain)]
    for preferred in PREFERRED_LOCAL_PARTS:
        for email in own:
            if email.split("@", 1)[0] == preferred:
                return email
    return own[0] if own else emails[0]
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_emails.py -v`
Expected: all pass

- [ ] **Step 5: Commit**
```bash
git add gmaps-scraper/gmaps/emails.py gmaps-scraper/tests/test_emails.py
git commit -m "feat(gmaps): email cleaning and primary email selection"
```

---

### Task 3: Normalize gosom entries

**Files:**
- Create: `gmaps-scraper/gmaps/normalize.py`, `gmaps-scraper/tests/fixtures/gosom_sample.jsonl`
- Test: `gmaps-scraper/tests/test_normalize.py`

**Interfaces:**
- Consumes: `clean_emails`, `site_domain`, `pick_primary` (Task 2)
- Produces: `normalize(entry: dict) -> dict | None` returning a dict whose keys are exactly `PLACE_KEYS`; `dedupe_places(places: list[dict | None]) -> list[dict]` (drops `None`, keeps the first per `place_id`); `PLACE_KEYS: tuple[str, ...]`

- [ ] **Step 1: Create fixture** — `tests/fixtures/gosom_sample.jsonl` (one JSON object per line, 4 lines)
```
{"input_id":"q1","link":"https://www.google.com/maps/place/Acme+Coffee","cid":"111","title":"Acme Coffee","categories":["Coffee shop","Cafe"],"category":"Coffee shop","address":"100 Main St, Austin, TX 78701","open_hours":{"Monday":["7 AM-5 PM"]},"popular_times":{"Monday":{"7":20}},"web_site":"https://www.acmecoffee.com/","phone":"(512) 555-0100","plus_code":"","review_count":214,"review_rating":4.6,"reviews_per_rating":{"5":150},"latitude":30.2672,"longtitude":-97.7431,"status":"Open","description":"","reviews_link":"","thumbnail":"","timezone":"America/Chicago","price_range":"$","data_id":"0x1:0x2","place_id":"ChIJacme","images":[{"title":"x","image":"y"}],"complete_address":{"borough":"","street":"100 Main St","city":"Austin","postal_code":"78701","state":"Texas","country":"US"},"user_reviews":[{"Name":"a"}],"user_reviews_extended":[],"emails":["logo@2x.png","Info@AcmeCoffee.com","owner@gmail.com"]}
{"input_id":"q1","link":"https://www.google.com/maps/place/No+Site","cid":"222","title":"No Site Bakery","categories":["Bakery"],"category":"Bakery","address":"5 Elm St, Austin, TX","open_hours":{},"web_site":"","phone":"","review_count":0,"review_rating":0,"latitude":30.1,"longtitude":-97.1,"place_id":"ChIJnosite","complete_address":{"city":"Austin","state":"Texas","postal_code":"","country":"US"},"emails":[]}
{"input_id":"q1","title":"Missing Id","place_id":"","emails":[]}
{"input_id":"q1","link":"https://www.google.com/maps/place/Acme+Coffee","title":"Acme Coffee DUP","place_id":"ChIJacme","emails":[]}
```

- [ ] **Step 2: Write the failing test** — `tests/test_normalize.py`
```python
import json
from pathlib import Path

from gmaps.normalize import PLACE_KEYS, dedupe_places, normalize

FIXTURE = Path(__file__).parent / "fixtures" / "gosom_sample.jsonl"


def load():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def test_full_entry():
    p = normalize(load()[0])
    assert set(p) == set(PLACE_KEYS)
    assert p["place_id"] == "ChIJacme"
    assert p["name"] == "Acme Coffee"
    assert p["category"] == "Coffee shop"
    assert p["categories"] == ["Coffee shop", "Cafe"]
    assert p["city"] == "Austin" and p["state"] == "Texas" and p["postal_code"] == "78701"
    assert p["website"] == "https://www.acmecoffee.com/"
    assert p["domain"] == "acmecoffee.com"
    assert p["phone"] == "(512) 555-0100"
    assert p["rating"] == 4.6 and p["review_count"] == 214
    assert p["lat"] == 30.2672 and p["lng"] == -97.7431
    assert p["maps_url"].startswith("https://www.google.com/maps/")
    assert p["hours"] == {"Monday": ["7 AM-5 PM"]}
    assert p["emails"] == ["info@acmecoffee.com"]  # logo@2x.png and owner@gmail.com dropped
    assert p["primary_email"] == "info@acmecoffee.com"


def test_raw_strips_heavy_keys():
    raw = normalize(load()[0])["raw"]
    for key in ("user_reviews", "user_reviews_extended", "images", "popular_times"):
        assert key not in raw
    assert raw["cid"] == "111"


def test_empty_values_become_none():
    p = normalize(load()[1])
    assert p["website"] is None and p["domain"] is None and p["phone"] is None
    assert p["rating"] is None and p["review_count"] == 0
    assert p["hours"] is None and p["postal_code"] is None
    assert p["emails"] == [] and p["primary_email"] is None


def test_missing_place_id_returns_none():
    assert normalize(load()[2]) is None


def test_dedupe_keeps_first_and_drops_none():
    places = dedupe_places([normalize(e) for e in load()])
    assert [p["place_id"] for p in places] == ["ChIJacme", "ChIJnosite"]
    assert places[0]["name"] == "Acme Coffee"
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_normalize.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 4: Implement** — `gmaps/normalize.py`
```python
from gmaps.emails import clean_emails, pick_primary, site_domain

PLACE_KEYS = (
    "place_id", "name", "category", "categories", "address", "city", "state", "postal_code",
    "country", "phone", "website", "domain", "rating", "review_count", "lat", "lng", "maps_url",
    "hours", "emails", "primary_email", "raw",
)
HEAVY_RAW_KEYS = ("user_reviews", "user_reviews_extended", "images", "popular_times")


def _s(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize(entry: dict) -> dict | None:
    place_id = _s(entry.get("place_id"))
    if not place_id:
        return None
    addr = entry.get("complete_address") or {}
    website = _s(entry.get("web_site"))
    domain = site_domain(website)
    emails = clean_emails(entry.get("emails"))
    review_count = int(entry.get("review_count") or 0)
    rating = entry.get("review_rating")
    return {
        "place_id": place_id,
        "name": _s(entry.get("title")),
        "category": _s(entry.get("category")),
        "categories": list(entry.get("categories") or []),
        "address": _s(entry.get("address")),
        "city": _s(addr.get("city")),
        "state": _s(addr.get("state")),
        "postal_code": _s(addr.get("postal_code")),
        "country": _s(addr.get("country")),
        "phone": _s(entry.get("phone")),
        "website": website,
        "domain": domain,
        "rating": float(rating) if rating and review_count > 0 else None,
        "review_count": review_count,
        "lat": entry.get("latitude"),
        "lng": entry.get("longtitude", entry.get("longitude")),
        "maps_url": _s(entry.get("link")),
        "hours": entry.get("open_hours") or None,
        "emails": emails,
        "primary_email": pick_primary(emails, domain),
        "raw": {k: v for k, v in entry.items() if k not in HEAVY_RAW_KEYS},
    }


def dedupe_places(places: list[dict | None]) -> list[dict]:
    seen: dict[str, dict] = {}
    for place in places:
        if place and place["place_id"] not in seen:
            seen[place["place_id"]] = place
    return list(seen.values())
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_normalize.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**
```bash
git add gmaps-scraper/gmaps/normalize.py gmaps-scraper/tests/test_normalize.py gmaps-scraper/tests/fixtures
git commit -m "feat(gmaps): normalize gosom entries into place records"
```

---

### Task 4: Supabase schema migration

**Files:**
- Create: `gmaps-scraper/supabase/migrations/20260926000001_init.sql`

**Interfaces:**
- Produces (used by Task 5 `db.py`):
  - Tables: `search_queue`, `runs`, `places`, `place_clients`, `settings`, `exports`, `export_items`. View: `leads_export`.
  - `upsert_places(p_places jsonb, p_client text, p_search_id bigint) returns table(out_place_id text, out_is_new boolean)`
  - `claim_next_search(p_run_id bigint) returns setof search_queue`
  - `leads_for_export(p_client text, p_since timestamptz, p_keyword text, p_include_no_email boolean, p_new_only boolean) returns table(place_id, name, category, primary_email, all_emails, phone, website, address, city, state, postal_code, rating, review_count, maps_url)`

- [ ] **Step 1: Write the migration file** — `supabase/migrations/20260926000001_init.sql`
```sql
-- Google Maps lead scraper schema

create table public.runs (
  id bigint generated always as identity primary key,
  trigger text not null check (trigger in ('scheduled', 'manual')),
  place_limit int check (place_limit > 0),
  status text not null default 'running' check (status in ('running', 'done', 'failed')),
  searches_done int not null default 0,
  places_scraped int not null default 0,
  places_new int not null default 0,
  places_with_email int not null default 0,
  failed_searches int not null default 0,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  notes text
);

create table public.search_queue (
  id bigint generated always as identity primary key,
  keyword text not null,
  location text not null,
  query text not null,
  client text not null,
  place_limit int check (place_limit > 0),
  status text not null default 'pending' check (status in ('pending', 'running', 'done', 'failed')),
  run_id bigint references public.runs(id),
  found_count int,
  new_count int,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz
);
create unique index search_queue_active_uniq on public.search_queue (query, client)
  where status in ('pending', 'running');
create index search_queue_status_idx on public.search_queue (status, id);
create index search_queue_client_query_idx on public.search_queue (client, query);

create table public.places (
  place_id text primary key,
  name text,
  category text,
  categories text[] not null default '{}',
  address text,
  city text,
  state text,
  postal_code text,
  country text,
  phone text,
  website text,
  domain text,
  rating numeric(2,1),
  review_count int not null default 0,
  lat double precision,
  lng double precision,
  maps_url text,
  hours jsonb,
  emails text[] not null default '{}',
  primary_email text,
  raw jsonb,
  first_seen_at timestamptz not null default now(),
  last_scraped_at timestamptz not null default now()
);

create table public.place_clients (
  place_id text not null references public.places(place_id) on delete cascade,
  client text not null,
  search_id bigint references public.search_queue(id) on delete set null,
  first_seen_at timestamptz not null default now(),
  primary key (place_id, client)
);
create index place_clients_client_idx on public.place_clients (client, first_seen_at);
create index place_clients_search_idx on public.place_clients (search_id);

create table public.settings (
  key text primary key,
  value jsonb
);
insert into public.settings (key, value) values
  ('nightly_limit', '1000'),
  ('concurrency', '3'),
  ('depth', '12');

create table public.exports (
  id bigint generated always as identity primary key,
  client text not null,
  filters jsonb not null default '{}',
  row_count int not null,
  file_name text not null,
  created_at timestamptz not null default now()
);

create table public.export_items (
  export_id bigint not null references public.exports(id) on delete cascade,
  place_id text not null references public.places(place_id) on delete cascade,
  primary key (export_id, place_id)
);
create index export_items_place_idx on public.export_items (place_id);

create view public.leads_export with (security_invoker = true) as
select pc.client, p.name, p.category, p.primary_email,
       array_to_string(p.emails, '; ') as all_emails, p.phone, p.website, p.address,
       p.city, p.state, p.postal_code, p.rating, p.review_count, p.maps_url,
       pc.first_seen_at, s.keyword, s.location
from public.place_clients pc
join public.places p on p.place_id = pc.place_id
left join public.search_queue s on s.id = pc.search_id;

-- Upsert a batch of places, merge emails, link to client. Returns which were new to the client.
create or replace function public.upsert_places(p_places jsonb, p_client text, p_search_id bigint)
returns table (out_place_id text, out_is_new boolean)
language plpgsql
set search_path = public
as $$
begin
  insert into places as p (
    place_id, name, category, categories, address, city, state, postal_code, country, phone,
    website, domain, rating, review_count, lat, lng, maps_url, hours, emails, primary_email, raw
  )
  select x.place_id, x.name, x.category, coalesce(x.categories, '{}'), x.address, x.city, x.state,
         x.postal_code, x.country, x.phone, x.website, x.domain, x.rating, coalesce(x.review_count, 0),
         x.lat, x.lng, x.maps_url, x.hours, coalesce(x.emails, '{}'), x.primary_email, x.raw
  from jsonb_to_recordset(p_places) as x(
    place_id text, name text, category text, categories text[], address text, city text,
    state text, postal_code text, country text, phone text, website text, domain text,
    rating numeric, review_count int, lat double precision, lng double precision,
    maps_url text, hours jsonb, emails text[], primary_email text, raw jsonb
  )
  on conflict (place_id) do update set
    name = excluded.name,
    category = excluded.category,
    categories = excluded.categories,
    address = excluded.address,
    city = excluded.city,
    state = excluded.state,
    postal_code = excluded.postal_code,
    country = excluded.country,
    phone = coalesce(excluded.phone, p.phone),
    website = coalesce(excluded.website, p.website),
    domain = coalesce(excluded.domain, p.domain),
    rating = excluded.rating,
    review_count = excluded.review_count,
    lat = excluded.lat,
    lng = excluded.lng,
    maps_url = coalesce(excluded.maps_url, p.maps_url),
    hours = coalesce(excluded.hours, p.hours),
    emails = (select coalesce(array_agg(distinct e order by e), '{}')
              from unnest(p.emails || excluded.emails) as e),
    primary_email = coalesce(excluded.primary_email, p.primary_email),
    raw = excluded.raw,
    last_scraped_at = now();

  return query
  with ids as (
    select x.place_id from jsonb_to_recordset(p_places) as x(place_id text)
  ), ins as (
    insert into place_clients (place_id, client, search_id)
    select ids.place_id, p_client, p_search_id from ids
    on conflict (place_id, client) do nothing
    returning place_clients.place_id
  )
  select ids.place_id, exists (select 1 from ins where ins.place_id = ids.place_id)
  from ids;
end;
$$;

-- Atomically claim the oldest pending search for a run.
create or replace function public.claim_next_search(p_run_id bigint)
returns setof public.search_queue
language sql
set search_path = public
as $$
  update search_queue
     set status = 'running', run_id = p_run_id, started_at = now(), error = null
   where id = (
     select id from search_queue where status = 'pending' order by id limit 1 for update skip locked
   )
  returning *;
$$;

-- Rows for a client CSV export.
create or replace function public.leads_for_export(
  p_client text,
  p_since timestamptz default null,
  p_keyword text default null,
  p_include_no_email boolean default false,
  p_new_only boolean default false
)
returns table (
  place_id text, name text, category text, primary_email text, all_emails text, phone text,
  website text, address text, city text, state text, postal_code text, rating numeric,
  review_count int, maps_url text
)
language sql
stable
set search_path = public
as $$
  select p.place_id, p.name, p.category, p.primary_email, array_to_string(p.emails, '; '),
         p.phone, p.website, p.address, p.city, p.state, p.postal_code, p.rating,
         p.review_count, p.maps_url
  from place_clients pc
  join places p on p.place_id = pc.place_id
  left join search_queue s on s.id = pc.search_id
  where pc.client = p_client
    and (p_since is null or pc.first_seen_at >= p_since)
    and (p_keyword is null or s.keyword ilike p_keyword)
    and (p_include_no_email or p.primary_email is not null)
    and (not p_new_only or not exists (
      select 1 from export_items ei join exports e on e.id = ei.export_id
      where e.client = p_client and ei.place_id = p.place_id))
  order by pc.first_seen_at, p.place_id;
$$;

-- Lock down: RLS on, no policies; only service_role executes functions.
alter table public.runs enable row level security;
alter table public.search_queue enable row level security;
alter table public.places enable row level security;
alter table public.place_clients enable row level security;
alter table public.settings enable row level security;
alter table public.exports enable row level security;
alter table public.export_items enable row level security;

revoke all on function public.upsert_places(jsonb, text, bigint) from public, anon, authenticated;
revoke all on function public.claim_next_search(bigint) from public, anon, authenticated;
revoke all on function public.leads_for_export(text, timestamptz, text, boolean, boolean) from public, anon, authenticated;
grant execute on function public.upsert_places(jsonb, text, bigint) to service_role;
grant execute on function public.claim_next_search(bigint) to service_role;
grant execute on function public.leads_for_export(text, timestamptz, text, boolean, boolean) to service_role;
revoke all on public.leads_export from anon, authenticated;
```

- [ ] **Step 2: Apply the migration**

Use the Supabase MCP `apply_migration` tool with `project_id = "oinbyhfjffhgrucjwzkj"`, `name = "init"`, `query = <file contents>`.
Expected: success.

- [ ] **Step 3: Verify with SQL** (MCP `execute_sql`)

```sql
begin;
insert into search_queue (keyword, location, query, client) values ('t', 'x', 't in x', 'me') returning id;
select * from upsert_places(
  '[{"place_id":"T1","name":"A","emails":["b@a.com"],"categories":["c"]},{"place_id":"T2","name":"B","emails":[]}]'::jsonb,
  'me', (select max(id) from search_queue));
select * from upsert_places('[{"place_id":"T1","name":"A2","emails":["a@a.com"]}]'::jsonb, 'me', null);
select place_id, name, emails from places where place_id in ('T1','T2') order by 1;
rollback;
```
Expected: first upsert returns T1 true, T2 true. Second returns T1 false. The final select shows T1 with name `A2`, emails `{a@a.com,b@a.com}`. Then run the MCP `get_advisors` tool (type `security`) and confirm there are no ERROR-level findings for these objects.

- [ ] **Step 4: Commit**
```bash
git add gmaps-scraper/supabase
git commit -m "feat(gmaps): supabase schema, upsert/claim/export functions"
```

---

### Task 5: Database access layer

**Files:**
- Create: `gmaps-scraper/gmaps/db.py`

**Interfaces:**
- Consumes: `Config` (Task 1), SQL functions and tables (Task 4)
- Produces: class `Db` with:
  - `Db.connect(cfg: Config) -> Db`
  - `get_setting(key: str, default=None)`
  - `reset_stale() -> int` (running searches → pending; running runs → failed "interrupted")
  - `create_run(trigger: str, limit: int | None) -> int`
  - `finish_run(run_id: int, status: str, stats: dict, notes: str | None) -> None`
  - `claim_next_search(run_id: int) -> dict | None` (keys: `id`, `query`, `client`, `place_limit`, …)
  - `finish_search(search_id: int, status: str, found: int, new: int, error: str | None = None) -> None`
  - `upsert_places(places: list[dict], client: str, search_id: int) -> int` (new-to-client count)
  - `existing_searches(client: str, queries: list[str]) -> list[dict]` (keys `query`, `status`, `finished_at`)
  - `insert_searches(rows: list[dict]) -> int`
  - `fetch_leads(client, since, keyword, include_no_email, new_only) -> list[dict]`
  - `record_export(client: str, filters: dict, file_name: str, place_ids: list[str]) -> int`
  - `status_summary() -> dict` (`{"queue": {status: count}, "last_run": dict | None}`)

This module is a thin I/O shell. It's verified by the Task 10 live run, and by a quick connectivity check here.

- [ ] **Step 1: Implement** — `gmaps/db.py`
```python
from datetime import datetime, timezone

from supabase import Client, create_client

from gmaps.config import Config

UPSERT_CHUNK = 200
PAGE = 1000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Db:
    def __init__(self, client: Client):
        self.c = client

    @classmethod
    def connect(cls, cfg: Config) -> "Db":
        return cls(create_client(cfg.supabase_url, cfg.supabase_key))

    # settings
    def get_setting(self, key: str, default=None):
        rows = self.c.table("settings").select("value").eq("key", key).execute().data
        return rows[0]["value"] if rows else default

    # runs
    def reset_stale(self) -> int:
        reset = (
            self.c.table("search_queue")
            .update({"status": "pending", "run_id": None, "started_at": None})
            .eq("status", "running")
            .execute()
            .data
        )
        self.c.table("runs").update(
            {"status": "failed", "finished_at": _now(), "notes": "interrupted"}
        ).eq("status", "running").execute()
        return len(reset)

    def create_run(self, trigger: str, limit: int | None) -> int:
        row = self.c.table("runs").insert({"trigger": trigger, "place_limit": limit}).execute().data[0]
        return row["id"]

    def finish_run(self, run_id: int, status: str, stats: dict, notes: str | None) -> None:
        self.c.table("runs").update(
            {**stats, "status": status, "notes": notes, "finished_at": _now()}
        ).eq("id", run_id).execute()

    # searches
    def claim_next_search(self, run_id: int) -> dict | None:
        rows = self.c.rpc("claim_next_search", {"p_run_id": run_id}).execute().data
        return rows[0] if rows else None

    def finish_search(self, search_id: int, status: str, found: int, new: int, error: str | None = None) -> None:
        self.c.table("search_queue").update(
            {"status": status, "found_count": found, "new_count": new, "error": error, "finished_at": _now()}
        ).eq("id", search_id).execute()

    def existing_searches(self, client: str, queries: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(queries), 100):
            out += (
                self.c.table("search_queue")
                .select("query,status,finished_at")
                .eq("client", client)
                .in_("query", queries[i : i + 100])
                .execute()
                .data
            )
        return out

    def insert_searches(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        return len(self.c.table("search_queue").insert(rows).execute().data)

    # places
    def upsert_places(self, places: list[dict], client: str, search_id: int) -> int:
        new = 0
        for i in range(0, len(places), UPSERT_CHUNK):
            rows = self.c.rpc(
                "upsert_places",
                {"p_places": places[i : i + UPSERT_CHUNK], "p_client": client, "p_search_id": search_id},
            ).execute().data
            new += sum(1 for r in rows if r["out_is_new"])
        return new

    # exports
    def fetch_leads(self, client, since, keyword, include_no_email, new_only) -> list[dict]:
        params = {
            "p_client": client,
            "p_since": since,
            "p_keyword": keyword,
            "p_include_no_email": include_no_email,
            "p_new_only": new_only,
        }
        out: list[dict] = []
        offset = 0
        while True:
            page = self.c.rpc("leads_for_export", params).range(offset, offset + PAGE - 1).execute().data
            out += page
            if len(page) < PAGE:
                return out
            offset += PAGE

    def record_export(self, client: str, filters: dict, file_name: str, place_ids: list[str]) -> int:
        row = self.c.table("exports").insert(
            {"client": client, "filters": filters, "row_count": len(place_ids), "file_name": file_name}
        ).execute().data[0]
        for i in range(0, len(place_ids), 500):
            self.c.table("export_items").insert(
                [{"export_id": row["id"], "place_id": pid} for pid in place_ids[i : i + 500]]
            ).execute()
        return row["id"]

    # status
    def status_summary(self) -> dict:
        queue = {}
        for status in ("pending", "running", "done", "failed"):
            res = self.c.table("search_queue").select("id", count="exact").eq("status", status).limit(1).execute()
            queue[status] = res.count or 0
        runs = self.c.table("runs").select("*").order("id", desc=True).limit(1).execute().data
        return {"queue": queue, "last_run": runs[0] if runs else None}
```

- [ ] **Step 2: Connectivity check**

Run: `.venv/Scripts/python -c "from gmaps.config import load_config; from gmaps.db import Db; d=Db.connect(load_config()); print(d.get_setting('nightly_limit'), d.status_summary())"`
Expected: `1000 {'queue': {'pending': 0, 'running': 0, 'done': 0, 'failed': 0}, 'last_run': None}`

- [ ] **Step 3: Commit**
```bash
git add gmaps-scraper/gmaps/db.py
git commit -m "feat(gmaps): supabase data access layer"
```

---

### Task 6: gosom scraper wrapper

**Files:**
- Create: `gmaps-scraper/gmaps/scraper.py`
- Test: `gmaps-scraper/tests/test_scraper.py`

**Interfaces:**
- Consumes: `Config`, `ROOT` (Task 1)
- Produces:
  - `ScrapeResult(entries: list[dict], returncode: int, stderr_tail: str)`
  - `depth_for_limit(limit: int | None, default_depth: int) -> int`
  - `build_command(gosom: Path, input_file: Path, results_file: Path, proxies_file: Path | None, concurrency: int, depth: int) -> list[str]`
  - `parse_results(text: str) -> list[dict]`
  - `GosomScraper(cfg: Config, concurrency: int)`, callable as `scraper(query: str, depth: int) -> ScrapeResult`

- [ ] **Step 1: Write the failing test** — `tests/test_scraper.py`
```python
from pathlib import Path

from gmaps.scraper import build_command, depth_for_limit, parse_results


def test_depth_for_limit():
    assert depth_for_limit(None, 12) == 12
    assert depth_for_limit(16, 12) == 2
    assert depth_for_limit(1, 12) == 1
    assert depth_for_limit(10_000, 12) == 12


def test_build_command_with_proxies():
    cmd = build_command(Path("g.exe"), Path("in.txt"), Path("out.json"), Path("px.txt"), 3, 10)
    assert cmd[0] == "g.exe"
    joined = " ".join(cmd)
    for part in ("-input in.txt", "-results out.json", "-json", "-email", "-c 3", "-depth 10",
                 "-exit-on-inactivity 3m", "-proxies-file px.txt"):
        assert part in joined


def test_build_command_without_proxies():
    cmd = build_command(Path("g.exe"), Path("in.txt"), Path("out.json"), None, 2, 5)
    assert "-proxies-file" not in cmd


def test_parse_jsonl():
    assert parse_results('{"a":1}\n\n{"a":2}\n') == [{"a": 1}, {"a": 2}]


def test_parse_json_array():
    assert parse_results('[{"a":1},{"a":2}]') == [{"a": 1}, {"a": 2}]


def test_parse_skips_garbage_lines():
    assert parse_results('{"a":1}\nnot json\n{"a":2') == [{"a": 1}]


def test_parse_empty():
    assert parse_results("") == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_scraper.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** — `gmaps/scraper.py`
```python
import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gmaps.config import ROOT, Config

RESULTS_PER_SCROLL = 8
TIMEOUT_SECONDS = 60 * 60


@dataclass
class ScrapeResult:
    entries: list[dict]
    returncode: int
    stderr_tail: str


def depth_for_limit(limit: int | None, default_depth: int) -> int:
    if limit is None:
        return default_depth
    return max(1, min(default_depth, math.ceil(limit / RESULTS_PER_SCROLL)))


def build_command(
    gosom: Path, input_file: Path, results_file: Path, proxies_file: Path | None, concurrency: int, depth: int
) -> list[str]:
    cmd = [
        str(gosom),
        "-input", str(input_file),
        "-results", str(results_file),
        "-json",
        "-email",
        "-c", str(concurrency),
        "-depth", str(depth),
        "-exit-on-inactivity", "3m",
    ]
    if proxies_file is not None:
        cmd += ["-proxies-file", str(proxies_file)]
    return cmd


def parse_results(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            return [e for e in json.loads(text) if isinstance(e, dict)]
        except json.JSONDecodeError:
            pass
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


class GosomScraper:
    def __init__(self, cfg: Config, concurrency: int):
        self.cfg = cfg
        self.concurrency = concurrency

    def __call__(self, query: str, depth: int) -> ScrapeResult:
        (ROOT / "tmp").mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="gosom_", dir=ROOT / "tmp"))
        try:
            input_file = work / "input.txt"
            results_file = work / "results.json"
            input_file.write_text(query + "\n", encoding="utf-8")
            proxies_file = None
            if self.cfg.proxies:
                proxies_file = work / "proxies.txt"
                proxies_file.write_text("\n".join(self.cfg.proxies) + "\n", encoding="utf-8")
            cmd = build_command(
                self.cfg.gosom_path, input_file, results_file, proxies_file, self.concurrency, depth
            )
            try:
                proc = subprocess.run(
                    cmd, cwd=work, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=TIMEOUT_SECONDS,
                )
                returncode, stderr = proc.returncode, proc.stderr or ""
            except subprocess.TimeoutExpired as exc:
                returncode = -1
                partial = exc.stderr if isinstance(exc.stderr, str) else ""
                stderr = f"timeout after {TIMEOUT_SECONDS}s\n{partial}"
            text = results_file.read_text(encoding="utf-8", errors="replace") if results_file.exists() else ""
            return ScrapeResult(parse_results(text), returncode, stderr[-2000:])
        finally:
            shutil.rmtree(work, ignore_errors=True)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_scraper.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**
```bash
git add gmaps-scraper/gmaps/scraper.py gmaps-scraper/tests/test_scraper.py
git commit -m "feat(gmaps): gosom subprocess wrapper and result parsing"
```

---

### Task 7: Run loop

**Files:**
- Create: `gmaps-scraper/gmaps/runner.py`, `gmaps-scraper/tests/fakes.py`
- Test: `gmaps-scraper/tests/test_runner.py`

**Interfaces:**
- Consumes: `normalize`, `dedupe_places` (Task 3); `ScrapeResult`, `depth_for_limit` (Task 6); `Db` methods `reset_stale`, `create_run`, `claim_next_search`, `upsert_places`, `finish_search`, `finish_run` (Task 5)
- Produces: `RunStats` dataclass (`searches_done`, `places_scraped`, `places_new`, `places_with_email`, `failed_searches`), `run(db, scrape, *, trigger: str, limit: int | None, default_depth: int, log=print) -> RunStats`, `MAX_CONSECUTIVE_BAD = 3`

- [ ] **Step 1: Write fakes** — `tests/fakes.py`
```python
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
```

- [ ] **Step 2: Write the failing test** — `tests/test_runner.py`
```python
from gmaps.runner import run
from gmaps.scraper import ScrapeResult
from tests.fakes import FakeDb, ScriptedScraper, entry, ok, search


def quiet(*_):
    pass


def test_processes_all_searches_when_unlimited():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(entry("a", "i@x.com"), entry("b")), ok(entry("c"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.reset_called
    assert stats.searches_done == 2 and stats.places_scraped == 3 and stats.places_new == 3
    assert stats.places_with_email == 1
    assert [f[1] for f in db.finished_searches] == ["done", "done"]
    assert db.runs[1]["status"] == "done"


def test_stops_when_run_limit_reached_and_leaves_rest_pending():
    db = FakeDb([search(1), search(2), search(3)])
    scraper = ScriptedScraper([ok(entry("a"), entry("b")), ok(entry("c"), entry("d"))])
    stats = run(db, scraper, trigger="scheduled", limit=3, default_depth=12, log=quiet)
    assert stats.places_new == 4
    assert len(db.pending) == 1
    assert db.runs[1]["notes"] == "limit reached"


def test_repeat_places_do_not_count_as_new():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ok(entry("a")), ok(entry("a"), entry("b"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert stats.places_scraped == 3 and stats.places_new == 2


def test_per_search_limit_truncates_and_sets_depth():
    db = FakeDb([search(1, place_limit=2)])
    scraper = ScriptedScraper([ok(entry("a"), entry("b"), entry("c"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert stats.places_scraped == 2
    assert scraper.calls == [("q1", 1)]


def test_failed_search_marked_and_run_continues():
    db = FakeDb([search(1), search(2)])
    scraper = ScriptedScraper([ScrapeResult([], 1, "boom"), ok(entry("a"))])
    stats = run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches[0][1] == "failed" and "boom" in db.finished_searches[0][4]
    assert db.finished_searches[1][1] == "done"
    assert stats.failed_searches == 1


def test_nonzero_exit_with_results_still_saves():
    db = FakeDb([search(1)])
    scraper = ScriptedScraper([ScrapeResult([entry("a")], 1, "partial")])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert db.finished_searches[0][1] == "done" and db.finished_searches[0][2] == 1


def test_three_bad_searches_in_a_row_stop_the_run():
    db = FakeDb([search(i) for i in range(1, 6)])
    scraper = ScriptedScraper([ScrapeResult([], 1, "x"), ok(), ScrapeResult([], 1, "y")])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(db.pending) == 2
    assert db.runs[1]["notes"] == "possible proxy block"


def test_good_search_resets_bad_streak():
    db = FakeDb([search(i) for i in range(1, 6)])
    scraper = ScriptedScraper([ok(), ok(), ok(entry("a")), ok(), ok()])
    run(db, scraper, trigger="manual", limit=None, default_depth=12, log=quiet)
    assert len(db.pending) == 0


def test_exception_marks_run_failed_and_reraises():
    class Boom:
        def __call__(self, q, d):
            raise RuntimeError("kaboom")

    db = FakeDb([search(1)])
    try:
        run(db, Boom(), trigger="manual", limit=None, default_depth=12, log=quiet)
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    assert db.runs[1]["status"] == "failed" and "kaboom" in db.runs[1]["notes"]
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_runner.py -v`
Expected: FAIL (`ModuleNotFoundError: gmaps.runner`)

- [ ] **Step 4: Implement** — `gmaps/runner.py`
```python
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


def run(db, scrape, *, trigger: str, limit: int | None, default_depth: int, log=print) -> RunStats:
    db.reset_stale()
    run_id = db.create_run(trigger, limit)
    stats = RunStats()
    status, notes = "done", None
    bad_streak = 0
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
            place_limit = search.get("place_limit")
            log(f"[run {run_id}] scraping: {search['query']} (client={search['client']})")
            result = scrape(search["query"], depth_for_limit(place_limit, default_depth))
            places = dedupe_places([normalize(e) for e in result.entries])
            if place_limit:
                places = places[:place_limit]

            if not places and result.returncode != 0:
                db.finish_search(search["id"], "failed", 0, 0, result.stderr_tail or f"exit {result.returncode}")
                stats.failed_searches += 1
                bad_streak += 1
                log(f"[run {run_id}]   failed (exit {result.returncode})")
                continue

            new = db.upsert_places(places, search["client"], search["id"]) if places else 0
            db.finish_search(search["id"], "done", len(places), new)
            stats.searches_done += 1
            stats.places_scraped += len(places)
            stats.places_new += new
            stats.places_with_email += sum(1 for p in places if p["primary_email"])
            bad_streak = 0 if places else bad_streak + 1
            log(f"[run {run_id}]   {len(places)} places, {new} new (run total new: {stats.places_new})")
    except Exception as exc:
        status, notes = "failed", repr(exc)[:500]
        raise
    finally:
        db.finish_run(run_id, status, asdict(stats), notes)
    return stats
```

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_runner.py -v`
Expected: 9 passed

- [ ] **Step 6: Commit**
```bash
git add gmaps-scraper/gmaps/runner.py gmaps-scraper/tests/fakes.py gmaps-scraper/tests/test_runner.py
git commit -m "feat(gmaps): run loop with limits, failure streak stop, stats"
```

---

### Task 8: Queue adding

**Files:**
- Create: `gmaps-scraper/gmaps/queue.py`
- Test: `gmaps-scraper/tests/test_queue.py`

**Interfaces:**
- Consumes: `Db.existing_searches`, `Db.insert_searches`
- Produces: `parse_locations(text: str) -> list[str]`, `build_query(keyword: str, location: str) -> str`, `plan_searches(keyword, locations, client, limit, existing, now, force) -> tuple[list[dict], list[str]]` (rows to insert, skipped queries), `add_searches(db, keyword, locations_text, client, limit=None, force=False, now=None) -> tuple[int, list[str]]`, `RECENT_DAYS = 30`

- [ ] **Step 1: Write the failing test** — `tests/test_queue.py`
```python
from datetime import datetime, timedelta, timezone

from gmaps.queue import add_searches, build_query, parse_locations, plan_searches
from tests.fakes import FakeDb

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)


def test_parse_locations():
    assert parse_locations("Austin, TX; Dallas, TX\nHouston, TX ;; ") == ["Austin, TX", "Dallas, TX", "Houston, TX"]


def test_build_query():
    assert build_query(" dentists ", " Austin, TX ") == "dentists in Austin, TX"


def test_plan_creates_rows():
    rows, skipped = plan_searches("dentists", ["Austin, TX"], "Jeff", 200, [], NOW, False)
    assert rows == [{"keyword": "dentists", "location": "Austin, TX", "query": "dentists in Austin, TX",
                     "client": "jeff", "place_limit": 200}]
    assert skipped == []


def test_plan_skips_active_and_recent_but_not_old():
    existing = [
        {"query": "dentists in A", "status": "pending", "finished_at": None},
        {"query": "dentists in B", "status": "done", "finished_at": (NOW - timedelta(days=5)).isoformat()},
        {"query": "dentists in C", "status": "done", "finished_at": (NOW - timedelta(days=45)).isoformat()},
        {"query": "dentists in D", "status": "failed", "finished_at": (NOW - timedelta(days=1)).isoformat()},
    ]
    rows, skipped = plan_searches("dentists", ["A", "B", "C", "D"], "me", None, existing, NOW, False)
    assert [r["location"] for r in rows] == ["C", "D"]
    assert skipped == ["dentists in A", "dentists in B"]


def test_force_overrides_recent_but_not_active():
    existing = [
        {"query": "dentists in A", "status": "running", "finished_at": None},
        {"query": "dentists in B", "status": "done", "finished_at": (NOW - timedelta(days=5)).isoformat()},
    ]
    rows, skipped = plan_searches("dentists", ["A", "B"], "me", None, existing, NOW, True)
    assert [r["location"] for r in rows] == ["B"]
    assert skipped == ["dentists in A"]


def test_plan_dedupes_repeated_locations():
    rows, _ = plan_searches("dentists", ["A", "A"], "me", None, [], NOW, False)
    assert len(rows) == 1


def test_add_searches_inserts():
    db = FakeDb()
    added, skipped = add_searches(db, "roofers", "Tampa, FL; Miami, FL", "me", now=NOW)
    assert added == 2 and skipped == []
    assert db.inserted[1]["query"] == "roofers in Miami, FL"
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_queue.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** — `gmaps/queue.py`
```python
import re
from datetime import datetime, timedelta, timezone

RECENT_DAYS = 30


def parse_locations(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]", text) if part.strip()]


def build_query(keyword: str, location: str) -> str:
    return f"{keyword.strip()} in {location.strip()}"


def _blocks(row: dict, now: datetime, force: bool) -> bool:
    if row["status"] in ("pending", "running"):
        return True
    if force or row["status"] != "done" or not row.get("finished_at"):
        return False
    finished = datetime.fromisoformat(row["finished_at"])
    return finished >= now - timedelta(days=RECENT_DAYS)


def plan_searches(keyword, locations, client, limit, existing, now, force):
    client = client.strip().lower()
    blocked = {row["query"] for row in existing if _blocks(row, now, force)}
    rows, skipped, seen = [], [], set()
    for location in locations:
        query = build_query(keyword, location)
        if query in seen:
            continue
        seen.add(query)
        if query in blocked:
            skipped.append(query)
            continue
        rows.append({
            "keyword": keyword.strip(),
            "location": location.strip(),
            "query": query,
            "client": client,
            "place_limit": limit,
        })
    return rows, skipped


def add_searches(db, keyword, locations_text, client, limit=None, force=False, now=None):
    now = now or datetime.now(timezone.utc)
    locations = parse_locations(locations_text)
    queries = [build_query(keyword, loc) for loc in locations]
    existing = db.existing_searches(client.strip().lower(), queries)
    rows, skipped = plan_searches(keyword, locations, client, limit, existing, now, force)
    return db.insert_searches(rows), skipped
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_queue.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**
```bash
git add gmaps-scraper/gmaps/queue.py gmaps-scraper/tests/test_queue.py
git commit -m "feat(gmaps): queue planning with duplicate/recent checks"
```

---

### Task 9: CSV export

**Files:**
- Create: `gmaps-scraper/gmaps/export.py`
- Test: `gmaps-scraper/tests/test_export.py`

**Interfaces:**
- Consumes: `Db.fetch_leads`, `Db.record_export`
- Produces: `COLUMNS: list[str]`, `write_csv(rows: list[dict], path: Path) -> None`, `export_leads(db, client, *, since=None, keyword=None, include_no_email=False, new_only=False, out_dir: Path, now=None) -> tuple[Path | None, int]`

- [ ] **Step 1: Write the failing test** — `tests/test_export.py`
```python
import csv
from datetime import datetime, timezone

from gmaps.export import COLUMNS, export_leads
from tests.fakes import FakeDb

NOW = datetime(2026, 9, 26, 13, 5, 0, tzinfo=timezone.utc)
LEAD = {"place_id": "P1", "name": "Acme", "category": "Dentist", "primary_email": "info@acme.com",
        "all_emails": "info@acme.com; a@acme.com", "phone": "1", "website": "https://acme.com",
        "address": "1 Main", "city": "Austin", "state": "Texas", "postal_code": "78701",
        "rating": 4.5, "review_count": 10, "maps_url": "https://maps"}


def test_export_writes_csv_and_records(tmp_path):
    db = FakeDb(leads=[LEAD])
    path, count = export_leads(db, "Jeff", since="2026-09-01", keyword="dentists", new_only=True,
                               out_dir=tmp_path, now=NOW)
    assert count == 1
    assert path.name == "jeff_20260926_130500.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == COLUMNS
    assert "place_id" not in rows[0]
    assert rows[0]["primary_email"] == "info@acme.com"
    assert db.fetch_args == ("jeff", "2026-09-01", "dentists", False, True)
    client, filters, file_name, place_ids = db.exports[0]
    assert client == "jeff" and file_name == path.name and place_ids == ["P1"]
    assert filters["new_only"] is True


def test_export_with_no_rows_writes_nothing(tmp_path):
    db = FakeDb(leads=[])
    path, count = export_leads(db, "me", out_dir=tmp_path, now=NOW)
    assert path is None and count == 0
    assert db.exports == []
    assert list(tmp_path.iterdir()) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/Scripts/python -m pytest tests/test_export.py -v`
Expected: FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement** — `gmaps/export.py`
```python
import csv
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = [
    "name", "category", "primary_email", "all_emails", "phone", "website", "address",
    "city", "state", "postal_code", "rating", "review_count", "maps_url",
]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_leads(db, client, *, since=None, keyword=None, include_no_email=False, new_only=False,
                 out_dir: Path, now=None):
    client = client.strip().lower()
    now = now or datetime.now(timezone.utc)
    rows = db.fetch_leads(client, since, keyword, include_no_email, new_only)
    if not rows:
        return None, 0
    path = out_dir / f"{client}_{now:%Y%m%d_%H%M%S}.csv"
    write_csv(rows, path)
    filters = {"since": since, "keyword": keyword, "include_no_email": include_no_email, "new_only": new_only}
    db.record_export(client, filters, path.name, [r["place_id"] for r in rows])
    return path, len(rows)
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python -m pytest tests/test_export.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**
```bash
git add gmaps-scraper/gmaps/export.py gmaps-scraper/tests/test_export.py
git commit -m "feat(gmaps): CSV export with export log"
```

---

### Task 10: CLI, setup scripts, and live smoke test

**Files:**
- Create: `gmaps-scraper/gmaps/cli.py`, `gmaps-scraper/scripts/setup.ps1`, `gmaps-scraper/scripts/register-task.ps1`, `gmaps-scraper/README.md`

**Interfaces:**
- Consumes: everything above.
- Produces: `main(argv: list[str] | None = None) -> None` console entry (`gmaps`).

- [ ] **Step 1: Implement CLI** — `gmaps/cli.py`
```python
import argparse
import logging
from logging.handlers import RotatingFileHandler

from gmaps.config import ROOT, load_config


def _setup_logging() -> logging.Logger:
    (ROOT / "logs").mkdir(exist_ok=True)
    logger = logging.getLogger("gmaps")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(message)s")
        file_handler = RotatingFileHandler(ROOT / "logs" / "gmaps.log", maxBytes=5_000_000, backupCount=5,
                                           encoding="utf-8")
        file_handler.setFormatter(fmt)
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        logger.addHandler(file_handler)
        logger.addHandler(console)
    return logger


def _int_or_none(value):
    return None if value in (None, "", "null") else int(value)


def cmd_run(args, db, cfg, log):
    from gmaps.runner import run
    from gmaps.scraper import GosomScraper

    if not cfg.gosom_path.exists():
        raise SystemExit(f"gosom not found at {cfg.gosom_path}; run scripts/setup.ps1")
    if args.all:
        limit = None
    elif args.limit is not None:
        limit = args.limit
    else:
        limit = _int_or_none(db.get_setting("nightly_limit"))
    concurrency = int(db.get_setting("concurrency", 3))
    depth = int(db.get_setting("depth", 12))
    log.info(f"run start: limit={limit or 'unlimited'} concurrency={concurrency} depth={depth} "
             f"proxies={len(cfg.proxies)}")
    stats = run(db, GosomScraper(cfg, concurrency), trigger="scheduled" if args.scheduled else "manual",
                limit=limit, default_depth=depth, log=log.info)
    log.info(f"run finished: {stats}")


def cmd_queue_add(args, db, cfg, log):
    from gmaps.queue import add_searches

    added, skipped = add_searches(db, args.keyword, args.locations, args.client, args.limit, args.force)
    log.info(f"queued {added} searches")
    for query in skipped:
        log.info(f"  skipped (already queued or done in last 30 days): {query}")


def cmd_export(args, db, cfg, log):
    from gmaps.export import export_leads

    path, count = export_leads(db, args.client, since=args.since, keyword=args.search,
                               include_no_email=args.include_no_email, new_only=args.new_only,
                               out_dir=ROOT / "exports")
    log.info(f"exported {count} leads to {path}" if path else "no leads matched; nothing exported")


def cmd_status(args, db, cfg, log):
    summary = db.status_summary()
    print("queue:", summary["queue"])
    print("last run:", summary["last_run"])


def main(argv=None):
    parser = argparse.ArgumentParser(prog="gmaps")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="scrape pending searches")
    group = p_run.add_mutually_exclusive_group()
    group.add_argument("--limit", type=int, help="stop after this many new places")
    group.add_argument("--all", action="store_true", help="no limit; empty the queue")
    p_run.add_argument("--scheduled", action="store_true", help="mark as scheduled run (uses nightly_limit)")
    p_run.set_defaults(func=cmd_run)

    p_queue = sub.add_parser("queue", help="manage search queue")
    qsub = p_queue.add_subparsers(dest="queue_command", required=True)
    p_add = qsub.add_parser("add", help="add keyword x locations")
    p_add.add_argument("keyword")
    p_add.add_argument("--locations", required=True, help='"Austin, TX; Dallas, TX"')
    p_add.add_argument("--client", required=True)
    p_add.add_argument("--limit", type=int, help="max places per search")
    p_add.add_argument("--force", action="store_true", help="re-queue even if done in last 30 days")
    p_add.set_defaults(func=cmd_queue_add)

    p_export = sub.add_parser("export", help="export leads CSV")
    p_export.add_argument("--client", required=True)
    p_export.add_argument("--since", help="YYYY-MM-DD, by first seen for this client")
    p_export.add_argument("--search", help="keyword filter (ILIKE pattern, e.g. dentist%%)")
    p_export.add_argument("--include-no-email", action="store_true")
    p_export.add_argument("--new-only", action="store_true", help="skip leads already exported to this client")
    p_export.set_defaults(func=cmd_export)

    p_status = sub.add_parser("status", help="queue counts and last run")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    log = _setup_logging()
    cfg = load_config()
    from gmaps.db import Db

    args.func(args, Db.connect(cfg), cfg, log)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Setup scripts**

`scripts/setup.ps1`:
```powershell
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Version = "1.18.1"
$Bin = Join-Path $Root "bin"
$Exe = Join-Path $Bin "google-maps-scraper.exe"

New-Item -ItemType Directory -Force $Bin | Out-Null
if (-not (Test-Path $Exe)) {
    $Url = "https://github.com/gosom/google-maps-scraper/releases/download/v$Version/google_maps_scraper-$Version-windows-amd64.exe"
    Write-Host "Downloading gosom v$Version ..."
    Invoke-WebRequest $Url -OutFile $Exe
}
& $Exe -version

if (-not (Test-Path (Join-Path $Root ".venv"))) {
    py -3.13 -m venv (Join-Path $Root ".venv")
}
& (Join-Path $Root ".venv\Scripts\python.exe") -m pip install -q -e "$Root[dev]"
if (-not (Test-Path (Join-Path $Root ".env"))) {
    Write-Warning "No .env found. Copy .env.example to .env and fill it in."
}
Write-Host "Setup complete."
```

`scripts/register-task.ps1`:
```powershell
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Gmaps = Join-Path $Root ".venv\Scripts\gmaps.exe"
if (-not (Test-Path $Gmaps)) { throw "Run scripts/setup.ps1 first." }

$Action = New-ScheduledTaskAction -Execute $Gmaps -Argument "run --scheduled" -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -Daily -At 1am
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "GMaps Scraper Nightly" -Action $Action -Trigger $Trigger `
    -Settings $Settings -Description "Google Maps lead scraper nightly run" -Force | Out-Null
Write-Host "Registered 'GMaps Scraper Nightly' (daily 1:00 AM, runs when available if missed)."
```

- [ ] **Step 3: README** — `gmaps-scraper/README.md`
````markdown
# Google Maps lead scraper

Scrapes Google Maps (via gosom v1.18.1) into Supabase, tagged by client, and exports cold-email CSVs.

## Setup (Windows)
1. `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`
2. Copy `.env.example` to `.env` and fill in `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PROXIES_FILE`.
3. `powershell -ExecutionPolicy Bypass -File scripts/register-task.ps1` (nightly 1 AM run)

## Use
```
.venv\Scripts\gmaps queue add "dentists" --locations "Austin, TX; Dallas, TX" --client jeff
.venv\Scripts\gmaps run --limit 2000      # or --all, or no flag = settings.nightly_limit
.venv\Scripts\gmaps export --client jeff --new-only
.venv\Scripts\gmaps status
```
Tunables live in the Supabase `settings` table: `nightly_limit` (null = unlimited), `concurrency`, `depth`.
Logs: `logs/gmaps.log`. Exports: `exports/`.
````

- [ ] **Step 4: Run full test suite**

Run: `.venv/Scripts/python -m pytest -v`
Expected: all tests pass

- [ ] **Step 5: Install gosom and verify**

Run: `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`
Expected: `bin/google-maps-scraper.exe` exists, and the gosom version prints `1.18.1`. `git status` shows no `bin/`, `.venv/` or `.env`.

- [ ] **Step 6: Live smoke test**

```bash
.venv/Scripts/gmaps queue add "coffee shops" --locations "Austin, TX" --client me --limit 100
.venv/Scripts/gmaps run --limit 100
.venv/Scripts/gmaps status
```
The first gosom run may download a Playwright browser (a few minutes). Expected: the search finishes `done` with `found_count` > 0. Verify with MCP `execute_sql`:
```sql
select count(*) places, count(primary_email) with_email from places;
select * from runs order by id desc limit 1;
select query, status, found_count, new_count, error from search_queue;
```
Record in the run output: places found, % with email, run duration, and any proxy errors in `logs/gmaps.log`. If the search failed or returned 0, check the log. If it shows proxy/CAPTCHA errors, run once with proxies disabled (blank `PROXIES_FILE`) to separate a proxy problem from a gosom problem, and report both results to the user.

Then test export: `.venv/Scripts/gmaps export --client me` → a CSV in `exports/` with rows that have emails.

- [ ] **Step 7: Commit**
```bash
git add gmaps-scraper/gmaps/cli.py gmaps-scraper/scripts gmaps-scraper/README.md
git status --short   # confirm no secrets/bin/venv/exports staged
git commit -m "feat(gmaps): CLI, setup and scheduler scripts, README"
```

- [ ] **Step 8: Scheduler (after merge only)**

Don't register the nightly task from this worktree, because the worktree path goes away after merge. After the branch is merged, from `C:\Users\Hi\AcroGrowth\gmaps-scraper`: copy `.env` over, run `scripts/setup.ps1`, then `scripts/register-task.ps1`. Confirm with `Get-ScheduledTask -TaskName "GMaps Scraper Nightly"`.
