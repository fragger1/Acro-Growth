"""Sort the place dump into what can still become a Jeff lead.

  pool_ontarget.csv   on-target category (export filter), usable own email, passes every rule
  pool_offtarget.csv  same, but the category is outside the export filter (owner-run call comes next)
  pool_guess.csv      one row per website domain with no usable email: places first seen since --since
                      (any category) plus older places whose only email is unusable; never-guessed domains
  pools_removed.csv   in-radius places with an email or website that were ruled out, with the reason

Dedupe: this run's PlusVibe dump + every earlier dump and delivered file (history.delivered_domains),
hand-review drops (history.hand_dropped), finished guesses, and the shared Reoon cache (an email Reoon
already called anything but safe / role_account, or catch-all, is not checked again).
One lead per email domain across both email pools; a guess domain that already has an email lead is skipped.
"""
import json
from collections import Counter

from . import config, history, rules
from .util import log, write_csv

FIELDS = ["place_id", "name", "category", "address", "city", "state", "postal_code", "phone", "website",
          "domain", "email", "primary_email", "all_emails", "rating", "review_count", "maps_url", "miles",
          "category_match", "first_seen_at", "new", "cached"]


def build(run, since):
    places = json.load(open(run.need("places.json", "run `dump` first"), encoding="utf-8"))
    pv_path = run.need("plusvibe_leads.json", "dump PlusVibe (list_all_leads) and run `pv --from <file>` first")
    known = history.delivered_domains(run.exclude, pv_path)
    dropped = history.hand_dropped(run.exclude)
    guessed = history.guessed_domains(run.exclude)
    cache = history.load_cache()
    log(f"history: {len(known)} taken domains, {len(dropped)} hand-dropped, {len(guessed)} guessed, "
        f"{len(cache)} Reoon answers cached")

    emails, guess, removed, why_count = [], {}, [], Counter()

    def drop(r, why):
        why_count[why] += 1
        if r.get("primary_email") or r.get("website"):
            removed.append({**r, "removed_because": why})

    for p in places:
        if (p.get("miles") or 999) > config.POOL_RADIUS:
            continue
        new = (p.get("first_seen_at") or "") >= since
        r = {k: ("" if v is None else v) for k, v in p.items() if k not in ("emails", "categories")}
        r.update(all_emails="; ".join(p.get("emails") or []), review_count=p.get("review_count") or 0, new=new)
        dom = rules.site_domain(p.get("website"))
        why = rules.reason(r, dom, known)
        if not why and dom and dom in dropped:
            why = "dropped in an earlier hand review"
        email = None if why else rules.pick_email(r, dom)
        if email:
            edom = email.split("@")[1]
            if edom in known or rules.mail_domain(edom) in known or edom in dropped:
                why = "email domain already in PlusVibe / delivered / dropped"
        if why:
            drop(r, why)
            continue
        if email:
            res = cache.get(email)
            if res and not rules.accepted(res):
                drop(r, f"Reoon cache: {rules.reoon_label(res)}")
                continue
            emails.append({**r, "email": email, "domain": dom or "", "cached": rules.reoon_label(res) if res else ""})
        elif dom and (new or p.get("primary_email")):
            if dom in guessed:
                drop(r, "domain already guessed")
                continue
            g = guess.get(dom)
            if g is None or r["review_count"] > g["review_count"]:
                guess[dom] = {**r, "domain": dom}
        elif not dom:
            drop(r, "no usable email or website")
        else:
            why_count["no email, not new (earlier guess passes covered these)"] += 1

    # one lead per email domain: on-target first, then the most-reviewed listing
    best = {}
    for r in sorted(emails, key=lambda x: (not x["category_match"], -int(x["review_count"] or 0))):
        k = rules.mail_domain(r["email"].split("@")[1])
        if k in best:
            drop(r, "duplicate listing on the same email domain")
        else:
            best[k] = r
    taken = set(best) | {r["domain"] for r in best.values() if r["domain"]}
    for d in [d for d in guess if d in taken]:
        drop(guess.pop(d), "domain already has an email lead in this run")

    on = sorted((r for r in best.values() if r["category_match"]), key=lambda x: (x["category"], x["name"]))
    off = sorted((r for r in best.values() if not r["category_match"]), key=lambda x: (x["category"], x["name"]))
    gp = sorted(guess.values(), key=lambda x: (x["category"], x["name"]))
    write_csv(run.path("pool_ontarget.csv"), on, FIELDS)
    write_csv(run.path("pool_offtarget.csv"), off, FIELDS)
    write_csv(run.path("pool_guess.csv"), gp, FIELDS)
    write_csv(run.path("pools_removed.csv"), removed, FIELDS + ["removed_because"])
    log(f"on-target email pool: {len(on)}   off-target email pool: {len(off)}   guess pool: {len(gp)} domains "
        f"({sum(bool(g['new']) for g in gp)} new since {since})")
    log("removed:", why_count.most_common())
    log("off-target categories:", Counter(r["category"] for r in off).most_common(30))
    run.done("pools", since=since, ontarget=len(on), offtarget=len(off), guess=len(gp),
             removed=dict(why_count.most_common()))
