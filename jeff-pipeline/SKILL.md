---
name: jeff-leads
description: Turn Jeff's (Midwest Roofing, Kansas City) new Google Maps scrape results into PlusVibe upload files in one dated run - place dump and PlusVibe dedupe, every filter rule, owner-run and hand review, Reoon verify and generic-inbox guess on daily credits only, UPLOAD csv + payloads. Use when the user says "process Jeff's new leads", "clean Jeff's new scrape / batch", "run the Reoon checker for Jeff", "get Jeff more leads from the scraper", or a Jeff scraper run just finished. Not for other clients, copywriting, or PlusVibe reply handling.
---

# Jeff lead pipeline

One CLI replaces the per-date script folders (JeffRerun_2026-10-15 and earlier). Every step writes into
`C:\Users\Hi\Documents\Claude\Projects\AcroGrowth\JeffRun_<date>\` and can be rerun or resumed; all filter
rules live in `jeffpipe/rules.py`. Never copy scripts into a dated folder again: change rules.py (and
tell the user) instead.

```
PY=C:\Users\Hi\AcroGrowth\scraper\gmaps-scraper\.venv\Scripts\python.exe
J=C:\Users\Hi\.claude\skills\jeff-leads\jeff.py
```
Global options go before the step: `$PY $J --run 2026-10-16 pools` (default run date: today). `$PY $J status` shows what's done and what's next.
Source of truth for the code: `jeff-pipeline/` in the scraper repo (fragger1/Acro-Growth); after editing
it there, `$PY jeff-pipeline\jeff.py install-skill` refreshes this folder.

## Hard rules (the user's, not defaults)
- **Reoon: daily credits only.** The budget stops by itself if instant credits move or daily credits hit the
  floor. Daily spend is routine and needs no extra OK; never work around a stop - rerun tomorrow to resume.
- Keep only Reoon `safe` / `role_account` that is **not catch-all**. Never keep catch_all or unknown.
- No personal / ISP inboxes; one lead per email domain; nothing already in PlusVibe or delivered.
- **Hand-filter before spending credits** (the user asked on 10/14): the review step comes before verify.
- **Never upload without the user's explicit yes** on the final counts.

## Steps

1. **PlusVibe dump** (fresh every run). Call the PlusVibe MCP `list_all_leads` for workspace
   `6a8708da7b065e030fbe57d7` with limit 10000. It overflows to a tool-results file; pass that file:
   `$PY $J pv --from "<tool-results file>"` (it skips the header line and finds the JSON). Check the
   count looks like the workspace total (5,597 on 10/15).
2. **Places**: `$PY $J dump` (Supabase, every place within 45 mi of Jeff; ~1 min).
3. **Pools**: `$PY $J pools` (`--since` defaults to the previous run's newest place). Writes
   `pool_ontarget.csv`, `pool_offtarget.csv`, `pool_guess.csv`, `pools_removed.csv` (reason per place).
   Dedupe = this PlusVibe dump + every earlier dump and UPLOAD / final / verified file + earlier hand-review
   drops + finished guesses + the shared Reoon cache.
4. **Review sheet**: `$PY $J review` applies the owner-run rule to off-target rows (2026-10-15: email an
   off-target business only when the shop is most likely owned by the person running it) and writes
   `review_sheet.csv` (key, pool, name, category, city, email_or_domain, website, reviews, tier).
5. **Hand review** (the expensive judgment step; do it in two passes):
   - Give the first pass to ONE cheap subagent (model `haiku`, or `sonnet` for a big sheet; tell the
     user the rough time first). Brief it with the sheet path and this checklist, and have it write
     `review_flags_draft.csv` (key, drop_reason) in the run folder, flagging only - not deciding:
     national chains and franchises the lists missed (Winmark, Bruster's, Kendra Scott, J.Crew ...), an
     inbox on another company's domain (agency, platform, parent, foreign affiliate, `*.onmicrosoft.com`,
     `replies.` / auto-reply subdomains), government / HOA / school / city-run / chamber-run operators,
     nonprofits and arts foundations with no shop, corporate-managed sites (Hyatt-run hotel, mall owner),
     online-only brands, junk addresses or junk domains, and churches or shops renting someone else's building.
   - Then confirm every flag yourself (open the website when it isn't obvious) and add what it missed.
     Write the result to `review_decisions.csv`: `key` = the email (email pools) or domain (guess pool), or
     any email / website domain to drop all its rows; `drop_reason` to drop; optional `company_name` /
     `group` (`church` or `8/20`) overrides for the upload. An empty file means nothing dropped.
   - `$PY $J apply` -> `reviewed_email.csv`, `reviewed_guess.csv`, and `review_dropped_hand.csv`, which every
     later run reads, so a drop is never reviewed twice. Unknown keys stop it (typo guard).
6. **Verify**: `$PY $J verify --dry-run` (cache hits, paid checks needed, free balance read), then
   `$PY $J verify` **in the background** (batches of 10, 2 workers, 15 s pauses; ~350 emails take
   ~15 min). Unknown / error are retried once alone at the end. Rerun to resume after a stop.
7. **Guess**: `$PY $J guess --dry-run [--mx]`, then `$PY $J guess` in the background (skips no-MX domains,
   tries category prefixes, first safe / role_account wins, catch-all ends the domain).
8. **Upload files**: `$PY $J upload` -> `UPLOAD_8-20_<date>.csv`, `UPLOAD_churches_<date>.csv`,
   `payload_8-20.json`, `payload_churches.json`. Eyeball the company names (listing names carry "| tagline",
   "- City", "Clinic: Dr ..."), fix any with `company_name` in review_decisions.csv + `apply` + rerun
   verify (cached, free) + upload. Show the user the counts and a sample, and **upload only on their yes**:
   `add_leads_to_campaign` with `skip_if_in_workspace`, 8/20 = `6a8708ef8c214cfc9078c566`,
   Churches = `6aba4d3c6b77606edf92fa00`, fields email / company_name / city / company_website /
   phone_number / address_line.

`$PY $J run [--pv-from FILE] [--dry-run]` chains the steps, skips finished ones, and stops before the
hand review; after `apply`, `run` again continues with verify, guess and upload.

## After a run
Add a short dated entry to the `jeff-reoon-generic-inbox-pipeline` memory: counts per stage, credits
used, review drops worth a new rule, anything uploaded. When a hand-review drop pattern repeats, add it
to rules.py (CHAIN_DOMAINS, REVIEW_NATIONAL, NOT_OWNER_SHOP ...) in the repo and re-install.

## Replaying an old run
`--ignore-history <folder>` leaves a project folder out of the dedupe; `JEFF_REOON_CACHE` points at a
different cache copy. `tests/test_rules_parity.py` (in the repo) checks rules.py against the old scripts.
