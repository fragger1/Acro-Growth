"""Owner-run category pass, the hand-review sheet, and applying the hand-review decisions.

`review` (automatic): off-target rows (email pool and guess pool) keep only owner-run categories
(rules.owner_run, the 2026-10-15 rule); on-target rows always stay. Writes
  review_sheet.csv            one compact row per remaining lead: key, pool, name, category, city, email /
                              domain, website, reviews, tier (B = type with 0 interested replies so far)
  review_dropped_categories.csv  what the owner-run rule removed, by category
  review_decisions.csv        empty template: key, drop_reason, company_name, group

The hand review (a cheap subagent's first pass, confirmed by Claude) fills review_decisions.csv with one
row per flagged lead: key = the email (email pools) or domain (guess pool), or any email / website domain
to drop every row on it. drop_reason set -> dropped; company_name / group set -> overrides for upload.
Look for: national chains and franchises the lists missed, inboxes on another company's domain,
government / HOA / school / nonprofit operators, corporate-managed sites, junk or auto-reply addresses,
online-only sellers, a church or business renting someone else's building.

`apply` writes reviewed_email.csv, reviewed_guess.csv and review_dropped_hand.csv (picked up by every later
run's dedupe, so a drop is never reviewed twice).
"""
import os
from collections import Counter

from . import rules
from .util import log, read_csv, write_csv

SHEET = ["key", "pool", "name", "category", "city", "email_or_domain", "website", "reviews", "tier", "cached", "new"]
DECISIONS = ["key", "drop_reason", "company_name", "group"]


def _rows(run):
    on = [{**r, "pool": "ontarget"} for r in read_csv(run.need("pool_ontarget.csv", "run `pools` first"))]
    off = [{**r, "pool": "offtarget"} for r in read_csv(run.path("pool_offtarget.csv"))]
    gp = [{**r, "pool": "guess"} for r in read_csv(run.path("pool_guess.csv"))]
    return on, off, gp


def sheet(run):
    on, off, gp = _rows(run)
    dropped = Counter()
    keep_off = [r for r in off if rules.owner_run(r["category"])]
    keep_gp = [r for r in gp if r["category_match"] == "True" or rules.owner_run(r["category"])]
    for r in off:
        if r not in keep_off:
            dropped[("offtarget", r["category"])] += 1
    for r in gp:
        if r not in keep_gp:
            dropped[("guess", r["category"])] += 1
    write_csv(run.path("review_keep_email.csv"), on + keep_off)
    write_csv(run.path("review_keep_guess.csv"), keep_gp)
    write_csv(run.path("review_dropped_categories.csv"),
              [{"pool": p, "category": c, "count": n} for (p, c), n in dropped.most_common()])
    rows = []
    for r in on + keep_off + keep_gp:
        is_guess = r["pool"] == "guess"
        rows.append({"key": r["domain"] if is_guess else r["email"], "pool": r["pool"], "name": r["name"],
                     "category": r["category"], "city": r["city"],
                     "email_or_domain": r["domain"] if is_guess else r["email"], "website": r["website"],
                     "reviews": r["review_count"], "tier": "B" if rules.TIER_B.search(r["category"] or "") else "",
                     "cached": r.get("cached", ""), "new": "new" if r.get("new") == "True" else ""})
    write_csv(run.path("review_sheet.csv"), rows, SHEET)
    if not run.has("review_decisions.csv"):
        write_csv(run.path("review_decisions.csv"), [], DECISIONS)
    log(f"owner-run rule: off-target {len(off)} -> {len(keep_off)}, guess {len(gp)} -> {len(keep_gp)} "
        f"(on-target {len(on)} all kept)")
    log(f"review sheet: {len(rows)} rows -> {run.path('review_sheet.csv')}")
    log(f"next: hand review into {run.path('review_decisions.csv')}, then `apply`")
    run.done("review", ontarget=len(on), offtarget=len(keep_off), guess=len(keep_gp), sheet=len(rows),
             owner_run_dropped=sum(dropped.values()))


def decisions(run):
    path = run.need("review_decisions.csv", "run `review` and do the hand review first")
    out = {}
    for d in read_csv(path):
        k = (d.get("key") or "").strip().lower()
        if k:
            out[k] = {f: (d.get(f) or "").strip() for f in DECISIONS[1:]}
    return out


def match(dec, email, domain, website):
    """The decision for a row: by exact email, then by email domain, website domain or guess domain."""
    email = (email or "").lower()
    keys = [email, email.split("@")[-1] if "@" in email else "", (domain or "").lower(),
            rules.host_of(website).removeprefix("www.")]
    for k in keys:
        if k and k in dec:
            return k, dec[k]
    return None, None


def apply(run, allow_unmatched=False):
    if not run.manifest["steps"].get("review"):
        raise SystemExit("run `review` first")
    dec = decisions(run)
    used = set()
    out = {}
    hand = []
    for name, src in (("reviewed_email.csv", "review_keep_email.csv"), ("reviewed_guess.csv", "review_keep_guess.csv")):
        keep = []
        for r in read_csv(run.path(src)):
            k, d = match(dec, r.get("email"), r.get("domain"), r.get("website"))
            if k:
                used.add(k)
            if d and d["drop_reason"]:
                hand.append({"email": r.get("email", ""), "domain": r.get("domain", ""), "website": r["website"],
                             "name": r["name"], "category": r["category"], "pool": r["pool"],
                             "removed_because": d["drop_reason"]})
                continue
            if d:
                r["company_name"], r["group_override"] = d["company_name"], d["group"]
            keep.append(r)
        out[name] = keep
    unmatched = sorted(set(dec) - used)
    if unmatched and not allow_unmatched:
        raise SystemExit(f"decision keys that match no row (typo?): {unmatched[:20]}  (--allow-unmatched to ignore)")
    for name, rows in out.items():
        write_csv(run.path(name), rows)
    write_csv(run.path("review_dropped_hand.csv"), hand,
              ["email", "domain", "website", "name", "category", "pool", "removed_because"])
    e, g = out["reviewed_email.csv"], out["reviewed_guess.csv"]
    log(f"hand review dropped {len(hand)}: {Counter(h['pool'] for h in hand)}")
    log(f"reviewed_email.csv: {len(e)} ({Counter(r['pool'] for r in e)})   reviewed_guess.csv: {len(g)} domains")
    if unmatched:
        log("unmatched decision keys:", unmatched)
    run.done("apply", email=len(e), guess=len(g), hand_dropped=len(hand),
             decisions_file=os.path.basename(run.path("review_decisions.csv")))
