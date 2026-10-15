"""jeff.py <step> [--run YYYY-MM-DD]: dump -> pv -> pools -> review -> (hand review) -> apply -> verify -> guess -> upload."""
import argparse
import datetime as dt
import json
import os
import shutil

from . import config, places, pools, review, upload, verify
from .util import Run, log, previous_runs

ORDER = ["dump", "pv", "pools", "review", "apply", "verify", "guess", "upload"]


def default_since(run):
    """Places first seen after the previous run's dump count as new (the guess pool takes them in any category)."""
    for d in previous_runs(run.date):
        info = json.load(open(os.path.join(d, "run.json"), encoding="utf-8"))["steps"].get("dump")
        if info and info.get("newest_first_seen"):
            return info["newest_first_seen"]
    raise SystemExit("no earlier JeffRun_ folder to take --since from: pass --since YYYY-MM-DD")


def status(run):
    log(f"run folder: {run.dir}")
    steps = run.manifest["steps"]
    for s in ORDER + ["verify_dry_run", "guess_dry_run"]:
        if s in steps:
            info = {k: v for k, v in steps[s].items() if k != "removed"}
            log(f"  {s:15} {json.dumps(info)}")
    nxt = next((s for s in ORDER if s not in steps), None)
    if nxt == "apply":
        log(f"next: hand review -> {run.path('review_decisions.csv')}, then `apply`")
    elif nxt:
        log(f"next: {nxt}")
    else:
        log("all steps done; upload files are in the run folder (upload them from Claude with add_leads_to_campaign)")


def run_all(run, a):
    steps = run.manifest["steps"]
    if "dump" not in steps or a.places_from:
        places.dump(run, a.places_from)
    if a.pv_from:
        places.import_pv(run, a.pv_from)
    if not run.has("plusvibe_leads.json"):
        raise SystemExit("dump PlusVibe first (list_all_leads, workspace " + config.PLUSVIBE_WORKSPACE +
                         ") and pass --pv-from <file>")
    if "pools" not in steps:
        pools.build(run, a.since or default_since(run))
    if "review" not in steps:
        review.sheet(run)
    if "apply" not in steps:
        log(f"\nstop: hand review needed -> {run.path('review_decisions.csv')}, then `apply`, then `run` again")
        return
    verify.verify(run, a.dry_run)
    verify.guess(run, a.dry_run, mx=a.mx)
    if not a.dry_run:
        upload.build(run)


def install_skill(_run, a):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dest = a.dest or os.path.join(os.path.expanduser("~"), ".claude", "skills", "jeff-leads")
    os.makedirs(dest, exist_ok=True)
    shutil.copyfile(os.path.join(here, "SKILL.md"), os.path.join(dest, "SKILL.md"))
    shutil.copyfile(os.path.join(here, "jeff.py"), os.path.join(dest, "jeff.py"))
    pkg = os.path.join(dest, "jeffpipe")
    if os.path.exists(pkg):
        shutil.rmtree(pkg)
    shutil.copytree(os.path.join(here, "jeffpipe"), pkg, ignore=shutil.ignore_patterns("__pycache__"))
    log(f"installed the skill and the pipeline code -> {dest}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jeff.py", description=__doc__)
    ap.add_argument("--run", default=dt.date.today().isoformat(), help="run date = folder JeffRun_<date> (default today)")
    ap.add_argument("--ignore-history", action="append", default=[], metavar="FOLDER",
                    help="leave this project folder out of the dedupe history (to replay an older run)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("dump", help="in-area places from Supabase (scraper venv python), or --from a saved dump")
    p.add_argument("--from", dest="src")
    p = sub.add_parser("pv", help="import the PlusVibe list_all_leads dump (overflow file or plain JSON)")
    p.add_argument("--from", dest="src", required=True)
    p = sub.add_parser("pools", help="rules + dedupe -> on-target / off-target email pools and the guess pool")
    p.add_argument("--since", help="places first seen on/after this are new (default: previous run's newest place)")
    sub.add_parser("review", help="owner-run category rule + the hand-review sheet")
    p = sub.add_parser("apply", help="apply review_decisions.csv -> reviewed_email.csv / reviewed_guess.csv")
    p.add_argument("--allow-unmatched", action="store_true")
    for name in ("verify", "guess"):
        p = sub.add_parser(name, help=f"Reoon {name} on DAILY credits only (--dry-run: no checks)")
        p.add_argument("--dry-run", action="store_true")
        p.add_argument("--batch", type=int, default=config.VERIFY_BATCH if name == "verify" else config.GUESS_BATCH)
        p.add_argument("--pause", type=float, default=config.VERIFY_PAUSE if name == "verify" else config.GUESS_PAUSE)
        p.add_argument("--floor", type=int, default=config.DAILY_FLOOR, help="stop at this many daily credits")
        if name == "guess":
            p.add_argument("--mx", action="store_true", help="dry run: look up MX now (free) to count no-MX domains")
    sub.add_parser("upload", help="build UPLOAD_*.csv + payload json (does not upload)")
    sub.add_parser("status", help="what's done in this run folder and what's next")
    p = sub.add_parser("run", help="every step in order; stops for the hand review; skips finished steps")
    p.add_argument("--places-from")
    p.add_argument("--pv-from")
    p.add_argument("--since")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--mx", action="store_true")
    p = sub.add_parser("install-skill", help="copy SKILL.md + this code to ~/.claude/skills/jeff-leads")
    p.add_argument("--dest")
    a = ap.parse_args(argv)

    if a.cmd == "install-skill":
        return install_skill(None, a)
    run = Run(a.run, a.ignore_history)
    if a.cmd == "dump":
        places.dump(run, a.src)
    elif a.cmd == "pv":
        places.import_pv(run, a.src)
    elif a.cmd == "pools":
        pools.build(run, a.since or default_since(run))
    elif a.cmd == "review":
        review.sheet(run)
    elif a.cmd == "apply":
        review.apply(run, a.allow_unmatched)
    elif a.cmd == "verify":
        verify.verify(run, a.dry_run, a.batch, a.pause, a.floor)
    elif a.cmd == "guess":
        verify.guess(run, a.dry_run, a.batch, a.pause, a.floor, a.mx)
    elif a.cmd == "upload":
        upload.build(run)
    elif a.cmd == "status":
        status(run)
    elif a.cmd == "run":
        run_all(run, a)
    run.save()
