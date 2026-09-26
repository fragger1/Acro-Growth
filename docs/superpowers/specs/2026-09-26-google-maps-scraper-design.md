# Google Maps Lead Scraper — Design

**Date:** 2026-09-26
**Status:** Approved in brainstorming, pending written-spec review

## Purpose

Build cold-email lead lists from Google Maps for AcroGrowth ("me") and done-for-you client Jeff. Target volume: ~1,000 places/day, 20–30k/month, with the ability to run larger or unlimited batches on demand. Runs on the owner's Windows 11 laptop. No GPU needed.

## Non-goals

- Email verification, and pushing leads into Smartlead/Instantly (later, separate project).
- Third-party enrichment for places with no website email (later, separate project).
- Any UI or client-facing access. Jeff never touches the system.
- Writing our own Google Maps scraper.

## Approach

Wrap the open-source [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) (Go, headless browser) with a small Python orchestrator. gosom does the scraping and email extraction. Python owns the queue, the limits, the Supabase storage, deduplication, and exports.

Rejected alternatives: gosom's native Postgres mode (its own jsonb schema, awkward to tag or deduplicate, connection-pooler friction) and a custom Playwright scraper (rebuilds gosom and takes on maintenance every time Google changes Maps).

## Components

All project files live under `gmaps-scraper/` in the repo.

```
gmaps/
  config.py      load .env; parse proxies file (ip:port:user:pass -> http://user:pass@ip:port)
  db.py          Supabase client + all table access (the only module that knows table names)
  scraper.py     build gosom command line, run it, stream JSON-lines results
  normalize.py   gosom JSON -> Place record (pure, no I/O)
  emails.py      junk-email filter + primary-email picker (pure)
  runner.py      run loop: pick searches, scrape, upsert, count against limit, close run
  queue.py       add searches (keyword x locations x client) with duplicate check
  export.py      CSV export with filters + export log
  cli.py         `gmaps run | queue add | export | status`
supabase/migrations/   SQL for all tables and views
bin/                   pinned gosom Windows binary (gitignored, fetched by setup script)
scripts/setup.ps1      download gosom at the pinned version, create venv, register scheduled task
tests/                 pytest, using saved gosom output fixtures
```

Stack: Python 3.12+, `supabase` Python client, `python-dotenv`, `pytest`. gosom is pinned to a specific release. Docker is the fallback if the Windows binary misbehaves.

## Data model (Supabase, project `oinbyhfjffhgrucjwzkj`)

**`search_queue`**: one row per keyword + location + client.
- `id`, `keyword`, `location`, `query` (e.g. "dentists in Austin, TX"), `client` (`me` | `jeff`, free text so more clients can be added), `place_limit` (null = everything Google returns), `status` (`pending` | `running` | `done` | `failed`), `run_id`, `found_count`, `new_count`, `error`, `created_at`, `started_at`, `finished_at`.
- Unique on (`query`, `client`) among rows that are `pending` or `running`, so the same search can't be queued twice.

**`places`**: one row per business, primary key `place_id` (Google's ID).
- `name`, `category`, `categories[]`, `address`, `city`, `state`, `postal_code`, `country`, `phone`, `website`, `domain`, `rating`, `review_count`, `lat`, `lng`, `maps_url`, `hours` (jsonb), `emails[]`, `primary_email`, `raw` (jsonb, gosom record minus `user_reviews`, `user_reviews_extended`, `images`, `popular_times` to save space). gosom does not extract social links, so there is no socials column., `first_seen_at`, `last_scraped_at`.
- When a place is scraped again, the fields are refreshed and `emails` is the union of old and new, so found emails are never lost.

**`place_clients`**: many-to-many link between places and clients.
- (`place_id`, `client`) primary key, `search_id` (the first search that found it), `first_seen_at`.

**`settings`**: key/value store, e.g. `nightly_limit` (integer, or null = unlimited), `concurrency`, `depth`.

**`runs`**: one row per run.
- `id`, `trigger` (`scheduled` | `manual`), `place_limit` (null = unlimited), `status`, `searches_done`, `places_scraped`, `places_new`, `places_with_email`, `failed_searches`, `started_at`, `finished_at`, `notes`.

**`exports`**: audit log so `--new-only` works.
- `id`, `client`, `filters` (jsonb), `row_count`, `file_name`, `created_at`, plus `export_items(export_id, place_id)`.

**View `leads_export`**: places joined to place_clients, with only CSV-ready columns.

RLS is enabled on every table with no policies. Only the service/secret key (used by the local script) can read or write.

## Run flow

1. **Trigger.** Windows Task Scheduler runs `gmaps run --scheduled` nightly at 01:00, with "run as soon as possible after a missed start" enabled. The limit comes from `settings.nightly_limit`. Manual runs use `gmaps run --limit N` or `gmaps run --all`. A `runs` row is inserted with status `running`.
2. **Recover.** Any `search_queue` rows still `running` from a previous crashed run go back to `pending`.
3. **Pick.** Take the oldest `pending` search and mark it `running` with this `run_id`.
4. **Scrape.** Write the query to a temp input file and run gosom with `-input <file> -json -results <file> -email -proxies-file <temp file> -c <concurrency> -depth <depth> -exit-on-inactivity 3m`. Concurrency defaults to 2–4 while on the 10 datacenter proxies.
5. **Save.** Normalize each result and upsert into `places` by `place_id`, merging emails. Insert into `place_clients` if the link doesn't exist yet. Count found vs new places, where new means the place was new to that client.
6. **Per-search limit.** If `place_limit` is set, stop saving once that many places are reached. gosom `-depth` is also derived from the limit to avoid unneeded scrolling.
7. **Run limit.** After each search, add its new places to the run total. If the total reaches the run limit, stop and leave the remaining searches `pending`. With `--all`, keep going until the queue is empty.
8. **Close.** The search is marked `done` or `failed` with counts and error, and the run row gets its totals and `finished_at`.

**Failure handling**
- gosom exits non-zero, or a search yields 0 results with error output: mark the search `failed` with stderr excerpt, continue with the next search.
- If 3 searches in a row fail, the run stops early with `notes = "possible proxy block"`, so a burned proxy set doesn't waste the whole night.
- A crash or sleep mid-run is recovered by step 2 on the next run. Places already upserted stay saved.

## Adding searches

`gmaps queue add "<keyword>" --locations "Austin, TX; Dallas, TX" --client jeff [--limit N]`
- Creates one row per keyword × location, with `query = "<keyword> in <location>"`.
- Skips a query if the same query for the same client is already pending or running, or finished within the last 30 days. `--force` overrides the 30-day check.
- Claude translates plain-English requests into these commands. Large areas (a whole state, or big metros) get split into cities, or neighbourhoods and zip codes, because Maps returns at most ~120 places per query.

## Exports

`gmaps export --client jeff [--since YYYY-MM-DD] [--search <keyword>] [--include-no-email] [--new-only]`
- Writes to `exports/<client>_<timestamp>.csv`.
- Columns: name, category, primary_email, all_emails, phone, website, address, city, state, postal_code, rating, review_count, maps_url.
- Only rows with an email are included by default.
- `--new-only` excludes places already included in a previous export for that client.
- Each export is recorded in `exports` / `export_items`.

**Email filtering (in `emails.py`)**
- Drop placeholder or example addresses and known platform or tracker domains (sentry, wix, squarespace, godaddy, cloudflare, and similar).
- Drop personal inboxes entirely: Gmail/Googlemail, Yahoo, Hotmail, Outlook, Live, MSN, AOL, iCloud/me.com/mac.com, Proton, GMX, Yandex (including country variants such as yahoo.co.uk), and ISP mailboxes (Comcast, AT&T, Verizon, BT, etc.). Generic business inboxes such as info@ or contact@ are wanted.
- Drop strings that end in image or file extensions, and anything that fails a basic syntax check.
- Lowercase and deduplicate.
- The primary email is the first address on the business's own website domain, preferring `info@`, `contact@`, `office@`, `hello@` or `admin@`. If there is none on their domain, the first remaining address is used.

## Proxies

- Currently 10 Webshare free datacenter proxies (file path in `.env` → `PROXIES_FILE`). They're parsed into gosom's `-proxies` format at runtime and never committed.
- The live test measures the block rate. If datacenter IPs get blocked, switch to rotating residential (Webshare Rotating Residential or DataImpulse, around $1–3.50/GB). That's a config change only.
- The gosom docs don't say whether website email visits also go through the proxy. The test will check. If they do and bandwidth matters later, email extraction could move into a separate step with no proxy (not in this scope).

## Configuration

`.env` (gitignored): `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PROXIES_FILE`. `.env.example` is committed with blank values. Tunables such as `nightly_limit`, `concurrency` and `depth` live in the `settings` table so they can be changed without touching the laptop.

## Testing

- **Unit tests (pytest, offline):** gosom JSON → Place normalization (from a saved fixture file), email filter and primary-email picker, proxy-line parsing, queue duplicate logic, run-limit accounting (runner with fake scraper and fake DB).
- **Live smoke test:** queue one real search ("coffee shops in Austin, TX", limit ~100) and run it. Verify rows in `places` / `place_clients`, the share of places with an email, the run totals, and whether any proxy blocks appear.

## Security notes

- The Supabase secret key was pasted in chat during setup. Rotate it once the system is working and update `.env`.
- A Supabase personal access token was also pasted in chat. Revoke it (it is not used by this system).
