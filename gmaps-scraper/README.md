# Google Maps lead scraper

Scrapes Google Maps (via gosom v1.18.1) into Supabase, tagged by client, and exports cold-email CSVs.

## Prerequisites (Windows)
- Python 3.13, installed with the `py` launcher available (`py -3.13` must work).
- git on `PATH` (used by `scripts/build-gosom.ps1` to clone gosom and scrapemate).

## Setup (Windows)
1. `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`
2. Copy `.env.example` to `.env` and fill in `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PROXIES_FILE`.
3. `powershell -ExecutionPolicy Bypass -File scripts/register-task.ps1` (nightly 1 AM run)

### Post-merge setup (after pulling changes into the main checkout)
`register-task.ps1` records the absolute path to `.venv\Scripts\gmaps.exe` in the scheduled task,
so after merging a branch into the main checkout, redo setup there in this order:
1. Copy `.env` into the main checkout (it's gitignored and not part of the merge).
2. Run `scripts/setup.ps1` there to (re)build gosom and the venv at that path.
3. Run `scripts/register-task.ps1` there so the scheduled task points at the main checkout's
   `gmaps.exe`, not a worktree that may no longer exist.

### Why gosom is built from source, not downloaded as a release binary
The published gosom v1.18.1 Windows release binary is broken on Windows: it launches Chromium
with `--single-process --no-zygote`, which crashes Chromium on Windows (the page comes back
0 bytes) and every search silently returns 0 results with `"unexpected page type"` in the log.
This is an open, unresolved upstream bug:
https://github.com/gosom/google-maps-scraper/issues/322

`scripts/setup.ps1` therefore calls `scripts/build-gosom.ps1`, which:
- downloads a portable copy of Go into `bin/go` (no system install, no PATH/registry changes),
- clones `gosom/google-maps-scraper` (v1.18.1) and `gosom/scrapemate` (v1.4.0, gosom's browser
  driver dependency) into `bin/src/`,
- applies `patches/scrapemate-v1.4.0-windows-no-single-process.patch`, which only appends
  `--single-process`/`--no-zygote` when `runtime.GOOS != "windows"` (every other Chromium flag
  is unchanged),
- applies `patches/gosom-v1.18.1-wait-for-next-results-page.patch` (see below), and
- builds `bin/google-maps-scraper.exe` against the patched scrapemate via a `go.mod` replace
  directive.

Everything the build needs lives under the gitignored `bin/` folder; nothing is installed
system-wide. After pulling a change to `patches/`, rerun `scripts/build-gosom.ps1` to rebuild
the binary (it applies only the patches that aren't applied yet).

### Searches that stop at exactly 20 results
Maps loads search results 20 at a time and renders them a few per scroll; the next 20 are only
fetched once the previous ones are all on screen. Unpatched gosom stops scrolling the first time
the results list doesn't grow within a fixed ~2 s wait, so whenever that next fetch is slow (a
slow proxy, a slow Google response, a busy machine) it stops at 20 (sometimes at 40 or 60). With
1 s of extra proxy latency the unpatched binary returned exactly 20 every time on searches that have
~90 results. The gosom patch keeps waiting up to 10 s for the list to grow, and stops right away
when Maps shows "You've reached the end of the list".

As a safety net, a search that still comes back with exactly 20 places is retried up to 2 more
times with other proxies, keeping the fullest result (not for searches limited to 20 or fewer
places). Each result line in the log ends with `via IP:port`, the proxy gosom loaded the search
page through.

A search can also legitimately return fewer places on one try than another: Maps sometimes answers
a zip-code search with a short list (15-18 places for "church in Kansas City, KS 66104", ending with
"You've reached the end of the list") and other times with ~100. That list really ends, so the
scraper isn't missing anything on that try, and it isn't retried unless it's exactly 20.

## Use
```
.venv\Scripts\gmaps queue add "dentists" --locations "Austin, TX; Dallas, TX" --client jeff
.venv\Scripts\gmaps run --limit 2000      # or --all, or no flag = settings.nightly_limit
.venv\Scripts\gmaps export --client jeff --new-only
.venv\Scripts\gmaps status
```
Exports leave out off-target places. Maps pads a search with loosely related places once it runs out
of real matches (a "machine shop" search returns crypto ATMs and gas stations), so a lead is exported
only when its primary Maps category contains one of the client's searched keywords, or matches an
extra `ILIKE` pattern in the Supabase `keyword_categories` table for one of those keywords (e.g.
`plumbing contractor` → `Plumber`). The export logs the categories it skipped; add a pattern row to
keep one, or pass `--any-category` to include everything. Skipped leads aren't marked exported.

Exports also leave out leads outside the client's service area: a client with a row in the Supabase
`client_areas` table (centre lat/lng + `radius_miles`) only exports places within that radius, which
works for the ~1 in 5 places Maps gives no address for. Jeff's is 40 miles around Overland Park, which
covers all 60 of his cities (the farthest, Ottawa, is 36 miles out). `--any-area` turns it off.

### Commercial-only leads (site keyword filter)
Maps has no commercial roofer category; commercial and residential roofers are both "Roofing contractor".
`gmaps site-filter` reads an export CSV, fetches each lead's homepage plus up to 3 same-site
service pages (paths containing commercial/industrial/service/roof), and writes the leads whose name or
site mentions a keyword to `<export>_site_match.csv`, with the matched words in a `site_keywords` column:
```
.venv\Scripts\gmaps site-filter exports\acro_20261013_120000.csv
.venv\Scripts\gmaps site-filter exports\acro_20261013_120000.csv --keywords "TPO, EPDM, flat roof"
```
The default keywords are commercial roofing terms (commercial, industrial, TPO, EPDM, flat roof, modified
bitumen, single-ply, roof coating, metal roofing...). Leads with no website are kept only when their name
matches; leads whose site can't be fetched are left out. It needs no Supabase access and doesn't mark
anything exported. The `commercial roofing` search keyword maps to the `Roofing contractor` category
(migration `20261013000001`), so that search isn't dropped as off-target.

### Verifying emails with Reoon
`gmaps verify-emails <csv>` checks each lead's `primary_email` with Reoon's single-email API in power
mode, one request per email (never the bulk endpoint), 10 at a time (`--workers`), and writes the leads Reoon calls `safe` or
`role_account` to `<csv>_verified.csv` with a `reoon_status` column. Every other status (invalid,
catch_all, disposable, unknown, ...) is dropped. Needs `REOON_API_KEY` in `.env`.
```
.venv\Scripts\gmaps verify-emails exports\acro_20261013_134050_site_match.csv
```
Each verdict is appended to `state/reoon_results.jsonl` as it arrives, so rerunning the same command
after Ctrl+C or an error resumes without paying for an email twice. Network errors, 429s and 5xx are
retried with backoff; leads still unchecked go to `<csv>_verify_errors.csv` for the next rerun. A bad key
or running out of credits stops the run immediately.

Junk emails are dropped at export time: an email on a domain that shows up on 3+ unrelated websites
(font foundries, website platforms, placeholders like mystore.com) is ignored unless the domain is the
site's own or carries the business name (a dealer group's domain). The lead falls back to its next
usable email, or is left out if it has none. The export logs what it skipped for each reason.

Tunables live in the Supabase `settings` table: `nightly_limit` (null = unlimited), `concurrency`, `depth`.
Logs: `logs/gmaps.log`. Exports: `exports/`.

### Email lookups
For each new place with a website, the email finder fetches the homepage plus up to 4 contact/about
pages. It fetches them with `curl_cffi` impersonating Chrome, because a lot of small-business sites sit
behind bot protection that answers 403 to any client whose TLS fingerprint isn't a browser's, no
matter what User-Agent it sends. To check how much that matters, run
`.venv\Scripts\python scripts\measure_fetch_block.py --sample 50`. It fetches homepages of
places that have a website but no email with both plain httpx and curl_cffi, then prints how many each
one gets through. Per-URL results go to `tmp/`.

Runs only look up emails for places they haven't seen before, so places saved with no email before
the switch to curl_cffi stay that way. `.venv\Scripts\gmaps recheck-emails` (optionally `--limit N`,
`--workers N`, default 16) looks them up again and saves any emails found. Finished place IDs are
appended to `state/email_recheck_done.txt`, so re-running it resumes; delete that file to recheck
everything again.

### Proxy rotation
gosom's proxy pool always starts at the first proxy it's given, and we start one gosom per search, so
passing the whole list would put every search on the same first few proxies. Instead:
- each search gets **5 random healthy proxies** from `PROXIES_FILE`, spreading load across the whole list;
- when gosom logs `Failed to connect to upstream: dial tcp IP:port`, that proxy gets a strike and is
  **benched for 1h**; after **10 strikes** it is **retired** (state in `state/proxy_health.json`, IP:port only).
  Strikes reset once a proxy goes 24h past its last bench without failing — most failures are transient
  connect errors, and a 24h bench per strike once sidelined 98 of 100 proxies in a single 17h run;
- runs pause a random **2–6 s** between searches so traffic isn't bursty.

`.venv\Scripts\gmaps proxies` lists benched and retired proxies; replace retired ones in the Webshare
dashboard, then delete their entries from `state/proxy_health.json` (or the whole file) to reset.
If every proxy is benched/retired, searches fail with "no healthy proxies available" and the run
stops after 3 in a row — it never falls back to your own IP.

Only one `gmaps run` can be active at a time (a file lock at `tmp/run.lock`); a second run started
while one is in progress logs "another gmaps run is active" and exits immediately without error.

Failed searches are **not** retried automatically. A search that ends up `failed` (0 results, a
gosom error, or a per-search exception) stays `failed` in `search_queue`; re-add it with
`gmaps queue add ...` to try it again — failed searches don't block that keyword/location/client
combination from being queued again the way a recent `done` search does.

The scheduled task's 12-hour execution time limit only kills the parent `gmaps.exe` process if a
run is still going at that point; it does not otherwise stop or pause a run early. For very large
`--all` batches that might run long, prefer a manual `gmaps run --all` you can watch, rather than
relying on the nightly scheduled run.
