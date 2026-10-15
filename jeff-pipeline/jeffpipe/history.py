"""What earlier work rules out: PlusVibe, delivered files, hand-review drops, finished guesses, Reoon cache.

Everything is read from PROJECTS (every dated folder, old and new), minus the folders in Run.exclude.
Domains are normalised with rules.mail_domain, like the old known_domains() / delivered_domains().
"""
import glob
import json
import os
import re

from . import config, rules
from .util import read_csv


def _folders(exclude, pattern="*"):
    for d in glob.glob(os.path.join(config.PROJECTS, pattern)):
        if os.path.isdir(d) and os.path.normcase(os.path.abspath(d)) not in exclude:
            yield d


def _files(exclude, *patterns, folders="*"):
    for d in _folders(exclude, folders):
        for pat in patterns:
            yield from glob.glob(os.path.join(d, pat))


def _web_host(v):
    return re.sub(r"^https?://", "", (v or "").lower().strip()).split("/")[0].split("?")[0].removeprefix("www.")


def load_pv(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def pv_domains(leads):
    doms = set()
    for lead in leads:
        e = (lead.get("email") or "").lower().strip()
        if "@" in e:
            doms.add(e.split("@")[1])
        if lead.get("company_website"):
            doms.add(_web_host(lead["company_website"]))
    return doms


def delivered_domains(exclude, pv_path=None):
    """Mail domains already in PlusVibe or handed over: this run's PlusVibe dump, every earlier dump
    (leads deleted since were removed on purpose), domain/exclude lists, every UPLOAD / load / final /
    verified file in a Jeff or NameGuess folder, and the 10/06 8/20 cleanup."""
    doms = set()
    dumps = list(_files(exclude, "plusvibe_leads_*.json"))
    if pv_path:
        dumps.append(pv_path)
    for f in dumps:
        doms |= pv_domains(load_pv(f))
    for f in _files(exclude, "plusvibe_domains_*.txt", "exclude_emails_*.txt"):
        for line in open(f, encoding="utf-8", errors="ignore"):
            line = line.strip().lower()
            if line:
                doms.add(line.split("@")[-1])
    files = [f for pat in ("Jeff*", "NameGuess_*")
             for f in _files(exclude, "*.csv", folders=pat)]
    for f in files:
        name = os.path.basename(f).lower()
        if not (name.startswith(("upload_", "load_")) or "final" in name or "verified" in name):
            continue
        for r in read_csv(f):
            e = (r.get("email") or r.get("Email") or "").lower().strip()
            if "@" in e:
                doms.add(e.split("@")[1])
            if name.startswith(("upload_", "load_")):
                doms.add(_web_host(r.get("company_website") or r.get("website")))
    for f in _files(exclude, "removed_leads.csv", folders="Jeff_8-20_Cleanup_*"):
        for r in read_csv(f):
            if "@" in (r.get("email") or ""):
                doms.add(r["email"].lower().split("@")[1])
    return {rules.mail_domain(d) for d in doms if d}


HAND_DROP_FILES = ("review_dropped*.csv", "review_removed*.csv", "found_review_dropped_*.csv",
                   "jeff_nameguess_dropped_*.csv", "jeff_nameguess_review_dropped_*.csv")


def hand_dropped(exclude):
    """Email and website domains a hand review dropped (any folder's review_dropped / review_removed ...)."""
    doms = set()
    for f in _files(exclude, *HAND_DROP_FILES):
        for r in read_csv(f):
            for k in ("email", "Email"):
                if "@" in (r.get(k) or ""):
                    doms.add(r[k].lower().split("@")[1].strip())
            for k in ("website", "company_website", "domain", "mail_domain"):
                v = _web_host(r.get(k))
                if v:
                    doms.add(v)
    return doms


def guessed_domains(exclude):
    """Domains a generic-inbox guess already finished (found / catch_all / none_valid / no_mx / error)."""
    doms = set()
    for f in _files(exclude, "guess_results*.csv"):
        for r in read_csv(f):
            d = (r.get("domain") or r.get("mail_domain") or "").lower().strip()
            if d and (r.get("outcome") or r.get("result") or "x") != "not_run":
                doms.add(d)
    return doms


def load_cache(path=None):
    cache = {}
    path = path or config.REOON_CACHE
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    cache[r["email"].lower()] = r
                except (ValueError, KeyError):
                    pass
    return cache
