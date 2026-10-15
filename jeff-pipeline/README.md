# Jeff lead pipeline

Turns Jeff's (Midwest Roofing) new Google Maps scrape results into PlusVibe upload files in one dated
run folder, replacing the copy-and-patch script folders (`JeffRerun_2026-10-15` and earlier).

```
dump -> pv -> pools -> review -> [hand review] -> apply -> verify -> guess -> upload
```

| module | what it holds |
| --- | --- |
| `jeffpipe/rules.py` | every filter rule (area, chains, trades, tenants, renters, government, owner-run, email rules) |
| `jeffpipe/history.py` | dedupe sources: PlusVibe dumps, delivered files, hand-review drops, finished guesses, Reoon cache |
| `jeffpipe/reoon.py` | daily-credits-only budget, batched checks, MX lookup, generic-inbox guess engine |
| `jeffpipe/places.py`, `pools.py`, `review.py`, `verify.py`, `upload.py` | the steps |
| `SKILL.md` | the Claude Code skill (`jeff.py install-skill` copies it and the code to `~/.claude/skills/jeff-leads`) |

Run with the scraper venv (the dump step imports `gmaps` and the Supabase client):

```
C:\Users\Hi\AcroGrowth\scraper\gmaps-scraper\.venv\Scripts\python.exe jeff.py --help
```

`tests/test_rules_parity.py` checks rules.py against the old dated scripts (constants and verdicts on all
41,832 places of the 10/15 dump). Run it after changing a rule that was copied from them.

Replay of 2026-10-15 (no Reoon checks): off-target 1,260 -> 440 owner-run -> 344 after the 10/15 hand
drops (10/15 scripts: 1,277 -> 445 -> 346); guess 110 -> 72 -> 52 domains (10/15: 129 -> 89 -> 63; the
12-domain gap is domains guessed on 10/11-10/12 that the 10/15 script missed because the 10/11 results
file names the column `mail_domain`).
