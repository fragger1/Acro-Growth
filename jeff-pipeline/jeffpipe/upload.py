"""Build the PlusVibe upload files. Nothing here talks to PlusVibe.

Inputs: reoon_kept.csv (reviewed email pool, Reoon safe / role_account) and guess_found.csv.
Dedupe again at build time: one lead per mail domain and per website domain, nothing in this run's
PlusVibe dump or any earlier delivered file. Company names get rules.clean_company plus the reviewer's
company_name override; churches go to the Churches campaign, everything else to 8/20.
Output: UPLOAD_8-20_<date>.csv, UPLOAD_churches_<date>.csv (later runs dedupe against these) and
payload_8-20.json / payload_churches.json in the add_leads_to_campaign shape.
"""
import json
from collections import Counter

from . import config, history, rules
from .util import log, read_csv, write_csv

PV_FIELDS = ["email", "first_name", "company_name", "city", "company_website", "phone_number", "address_line"]


def build(run):
    rows = [{**r, "source": r.get("pool", "")} for r in read_csv(run.path("reoon_kept.csv"))] if run.has("reoon_kept.csv") else []
    if run.has("guess_found.csv"):
        rows += [{**r, "source": "guess"} for r in read_csv(run.path("guess_found.csv"))]
    if not rows:
        raise SystemExit("nothing to build: run `verify` and/or `guess` first")
    for step in ("verify", "guess"):
        info = run.manifest["steps"].get(step)
        if info and not info.get("complete", True):
            log(f"note: {step} did not finish (stopped: {info.get('stopped')}); rerun it to add the rest")
    taken = history.delivered_domains(run.exclude, run.path("plusvibe_leads.json"))
    out, seen, skipped = [], set(), Counter()
    for r in rows:
        email = r["email"].lower().strip()
        keys = {rules.mail_domain(email.split("@")[1]), rules.host_of(r["website"]).removeprefix("www.")} - {""}
        if keys & taken:
            skipped["already in PlusVibe / delivered"] += 1
            continue
        if keys & seen:
            skipped["duplicate domain in this run"] += 1
            continue
        seen |= keys
        group = r.get("group_override") or rules.group_of(r["category"], r["name"])
        out.append({"email": email, "first_name": "", "company_name": r.get("company_name") or rules.clean_company(r["name"]),
                    "city": r["city"], "company_website": r["website"], "phone_number": r["phone"],
                    "address_line": (r["address"] or "").removesuffix(", United States"), "category": r["category"],
                    "group": group, "source": r["source"], "email_status": r.get("email_status", "")})
    counts = {}
    for group, tag in (("8/20", "8-20"), ("church", "churches")):
        g = sorted((x for x in out if x["group"] == group), key=lambda x: (x["category"], x["company_name"]))
        write_csv(run.path(f"UPLOAD_{tag}_{run.date}.csv"), g, PV_FIELDS + ["category", "source", "email_status"])
        with open(run.path(f"payload_{tag}.json"), "w", encoding="utf-8") as fh:
            json.dump([{k: x[k] for k in PV_FIELDS} for x in g], fh, indent=1)
        counts[tag] = len(g)
        log(f"-> UPLOAD_{tag}_{run.date}.csv: {len(g)} (campaign {config.CAMPAIGNS[group]})")
    log("skipped:", dict(skipped), " by source:", dict(Counter(x["source"] for x in out)))
    run.done("upload", **counts, skipped=dict(skipped))
