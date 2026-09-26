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
