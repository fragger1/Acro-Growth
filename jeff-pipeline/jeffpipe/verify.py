"""Reoon steps: verify the reviewed email pool, guess generic inboxes on the reviewed guess pool.

Both resume: every answer is logged to a .jsonl in the run folder as it arrives, and a rerun skips what
is already settled (cached answers cost nothing anyway). --dry-run makes no Reoon checks: it reports what
the cache already settles and how many paid checks are left (and reads the free balance endpoint).
"""
import json
import os
import time
from collections import Counter

from . import config, history, reoon, rules
from .util import log, read_csv, write_csv


def _key():
    key = os.environ.get("REOON_API_KEY")
    if not key:
        raise SystemExit("set REOON_API_KEY")
    return key


def _balance_line():
    key = os.environ.get("REOON_API_KEY")
    if not key:
        return "REOON_API_KEY not set (balance not read)"
    try:
        b = reoon.balance(key)
        return f"Reoon balance: daily {b['remaining_daily_credits']}, instant {b['remaining_instant_credits']}"
    except Exception as e:  # noqa: BLE001
        return f"balance check failed: {e}"


def _jsonl(path):
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            try:
                r = json.loads(line)
                out[r["key"]] = r
            except (ValueError, KeyError):
                pass
    return out


def _append(path, rec):
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


# ---------------------------------------------------------------- verify
def verify(run, dry_run=False, batch=config.VERIFY_BATCH, pause=config.VERIFY_PAUSE, floor=config.DAILY_FLOOR):
    rows = read_csv(run.need("reviewed_email.csv", "run `apply` after the hand review first"))
    log_path = run.path("verify_results.jsonl")
    done = _jsonl(log_path)
    emails = list(dict.fromkeys(r["email"].lower() for r in rows))

    def settled(e):
        d = done.get(e)
        return d and (d["status"] not in reoon.RETRY or d.get("attempts", 1) >= 2)

    if dry_run:
        cache = history.load_cache()
        cached = Counter(rules.reoon_label(cache[e]) for e in emails if e in cache)
        todo = [e for e in emails if e not in cache and not settled(e)]
        log(f"{len(emails)} emails: {sum(cached.values())} already in the Reoon cache {dict(cached)}, "
            f"{sum(1 for e in emails if settled(e))} settled in this run, {len(todo)} need a paid check "
            f"(+ up to that many retries for unknown / error)")
        log(_balance_line())
        run.done("verify_dry_run", emails=len(emails), cached=sum(cached.values()), paid_checks=len(todo))
        return

    key = _key()
    budget = reoon.Budget(key, floor)
    checker = reoon.Checker(key, budget)
    s = budget.start
    log(f"{len(emails)} emails. Reoon at start: daily {s['remaining_daily_credits']}, instant {s['remaining_instant_credits']}")

    def record(e, res, attempts):
        if res.get("status") == "not_run":
            return
        rec = {"key": e, "status": res.get("status"), "is_catch_all": bool(res.get("is_catch_all")), "attempts": attempts}
        done[e] = rec
        _append(log_path, rec)

    todo = [e for e in emails if not done.get(e)]
    for e, res in reoon.in_batches(todo, checker.check, batch, pause, budget, "verify"):
        record(e, res, 1)
    retry = [e for e in emails if done.get(e) and done[e]["status"] in reoon.RETRY and done[e].get("attempts", 1) < 2]
    if retry and not budget.stopped:
        log(f"re-checking {len(retry)} unknown / error one at a time after {pause * 2:.0f}s")
        time.sleep(pause * 2)
        for e in retry:
            record(e, checker.check(e, fresh=True), 2)
            if budget.stopped:
                break
            time.sleep(pause / 3)
    end = reoon.balance(key)
    log(f"Reoon now: daily {end['remaining_daily_credits']}, instant {end['remaining_instant_credits']} "
        f"({checker.paid} paid checks)")
    if end["remaining_instant_credits"] < s["remaining_instant_credits"]:
        log("WARNING: instant credits moved during this run")

    keep, removed, statuses = [], [], Counter()
    for r in rows:
        d = done.get(r["email"].lower())
        st = "not_run" if not d else rules.reoon_label(d)
        statuses[st] += 1
        if d and rules.accepted(d):
            keep.append({**r, "email_status": d["status"]})
        else:
            removed.append({**r, "email_status": st, "removed_because": f"Reoon: {st}"})
    write_csv(run.path("reoon_kept.csv"), keep)
    write_csv(run.path("removed_verify.csv"), removed)
    log("statuses:", statuses.most_common())
    log(f"kept {len(keep)} of {len(rows)}" + (f"  STOPPED: {budget.stopped} (rerun to resume)" if budget.stopped else ""))
    run.done("verify", kept=len(keep), of=len(rows), paid=checker.paid, statuses=dict(statuses),
             stopped=budget.stopped, complete=not any(s == "not_run" for s in statuses))


# ---------------------------------------------------------------- guess
def guess(run, dry_run=False, batch=config.GUESS_BATCH, pause=config.GUESS_PAUSE, floor=config.DAILY_FLOOR, mx=False):
    pool = read_csv(run.need("reviewed_guess.csv", "run `apply` after the hand review first"))
    pool.sort(key=lambda r: (not rules.GUESS_PRIORITY.search(r["category"] or ""), -int(r["review_count"] or 0)))
    log_path = run.path("guess_results.jsonl")
    done = {k: v for k, v in _jsonl(log_path).items() if v["outcome"] != "not_run"}

    if dry_run:
        cache = history.load_cache()
        outcomes, cost, no_mx = Counter(), 0, 0
        for r in pool:
            d = r["domain"]
            if d in done:
                outcomes[f"{done[d]['outcome']} (this run)"] += 1
                continue
            if mx and reoon.has_mx(d) is False:
                outcomes["no_mx"] += 1
                no_mx += 1
                continue
            oc, c = reoon.simulate_domain(rules.guess_prefixes(r["category"]), d, cache)
            outcomes[oc or "needs checks"] += 1
            cost += c
        log(f"{len(pool)} domains: {dict(outcomes)}")
        log(f"worst case {cost} paid checks (6 prefixes per domain; most domains stop early, and no-MX domains"
            f" cost nothing{'' if mx else ' -- add --mx to look those up now, free'})")
        log(_balance_line())
        run.done("guess_dry_run", domains=len(pool), worst_case_checks=cost, outcomes=dict(outcomes))
        return

    key = _key()
    budget = reoon.Budget(key, floor)
    checker = reoon.Checker(key, budget)
    s = budget.start
    log(f"{len(pool)} domains. Reoon at start: daily {s['remaining_daily_credits']}, instant {s['remaining_instant_credits']}")

    def work(r):
        return reoon.work_domain(r["domain"], rules.guess_prefixes(r["category"]), checker)

    def record(r, res, attempts):
        if res["outcome"] == "not_run":
            return
        rec = {"key": r["domain"], **res, "attempts": attempts}
        done[r["domain"]] = rec
        _append(log_path, rec)

    todo = [r for r in pool if r["domain"] not in done]
    for r, res in reoon.in_batches(todo, work, batch, pause, budget, "guess"):
        record(r, res, 1)
    retry = [r for r in pool if done.get(r["domain"], {}).get("outcome") == "error" and done[r["domain"]]["attempts"] < 2]
    if retry and not budget.stopped:
        log(f"re-trying {len(retry)} domains that hit an error, one at a time")
        time.sleep(pause * 2)
        for r in retry:
            record(r, work(r), 2)
            time.sleep(pause / 3)
    end = reoon.balance(key)
    log(f"Reoon now: daily {end['remaining_daily_credits']}, instant {end['remaining_instant_credits']} "
        f"({checker.paid} paid checks)")
    if end["remaining_instant_credits"] < s["remaining_instant_credits"]:
        log("WARNING: instant credits moved during this run")

    found, results = [], []
    for r in pool:
        res = done.get(r["domain"], {"outcome": "not_run", "email": "", "email_status": "", "tried": ""})
        results.append({**r, "outcome": res["outcome"], "email": res["email"], "email_status": res["email_status"],
                        "tried": res["tried"]})
        if res["outcome"] == "found":
            found.append({**r, "email": res["email"], "email_status": res["email_status"]})
    # guess_results.csv (domain + outcome) is what later runs read to skip finished domains
    write_csv(run.path("guess_results.csv"), results)
    write_csv(run.path("guess_found.csv"), found)
    oc = Counter(x["outcome"] for x in results)
    log(f"found {len(found)} of {len(pool)}; outcomes: {oc.most_common()}"
        + (f"  STOPPED: {budget.stopped} (rerun to resume)" if budget.stopped else ""))
    run.done("guess", found=len(found), of=len(pool), paid=checker.paid, outcomes=dict(oc), stopped=budget.stopped,
             complete=not oc.get("not_run"))
