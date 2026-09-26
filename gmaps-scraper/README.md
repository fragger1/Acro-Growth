# Google Maps lead scraper

Scrapes Google Maps (via gosom v1.18.1) into Supabase, tagged by client, and exports cold-email CSVs.

## Setup (Windows)
1. `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`
2. Copy `.env.example` to `.env` and fill in `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `PROXIES_FILE`.
3. `powershell -ExecutionPolicy Bypass -File scripts/register-task.ps1` (nightly 1 AM run)

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
