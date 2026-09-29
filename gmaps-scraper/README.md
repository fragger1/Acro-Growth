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
  is unchanged), and
- builds `bin/google-maps-scraper.exe` against the patched scrapemate via a `go.mod` replace
  directive.

Everything the build needs lives under the gitignored `bin/` folder; nothing is installed
system-wide.

## Use
```
.venv\Scripts\gmaps queue add "dentists" --locations "Austin, TX; Dallas, TX" --client jeff
.venv\Scripts\gmaps run --limit 2000      # or --all, or no flag = settings.nightly_limit
.venv\Scripts\gmaps export --client jeff --new-only
.venv\Scripts\gmaps status
```
Tunables live in the Supabase `settings` table: `nightly_limit` (null = unlimited), `concurrency`, `depth`.
Logs: `logs/gmaps.log`. Exports: `exports/`.

### Proxy rotation
gosom's proxy pool always starts at the first proxy it's given, and we start one gosom per search, so
passing the whole list would put every search on the same first few proxies. Instead:
- each search gets **5 random healthy proxies** from `PROXIES_FILE`, spreading load across the whole list;
- when gosom logs `Failed to connect to upstream: dial tcp IP:port`, that proxy gets a strike and is
  **benched for 24h**; after **3 strikes** it is **retired** (state in `state/proxy_health.json`, IP:port only);
- runs pause a random **5–20 s** between searches so traffic isn't bursty.

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
