"""Reoon verification on DAILY credits only, plus the generic-inbox guess engine.

Reoon spends daily credits first and falls back to the paid instant balance when they run out, so the
budget re-reads the balance every config.BALANCE_EVERY paid checks and stops for good the moment the
instant balance moves (worst case it overshoots by that many checks) or daily credits reach the floor.
Reoon also lags when hit with many checks at once and answers "unknown", so checks go out in small
batches from 2 workers with pauses, and unknown / error answers are retried once, alone, at the end.
Every answer except unknown / error is appended to the shared cache, so nothing is paid for twice.
"""
import json
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import config
from .history import load_cache
from .rules import accepted
from .util import log

API = "https://emailverifier.reoon.com/api/v1"
RETRY = {"unknown", "error"}


def balance(key):
    url = f"{API}/check-account-balance/?" + urllib.parse.urlencode({"key": key})
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def reoon(email, key):
    url = f"{API}/verify?" + urllib.parse.urlencode({"email": email, "key": key, "mode": "power"})
    err = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=90) as r:
                data = json.load(r)
            if "status" in data and data.get("email"):
                return data
            raise RuntimeError(f"unexpected response: {data}")
        except Exception as e:  # noqa: BLE001 - network, JSON or API error: retry, then report
            err = e
            time.sleep(3 * (attempt + 1))
    return {"email": email, "status": "error", "error": str(err)}


def has_mx(domain):
    """True / False from Google DNS; None when the lookup fails (then Reoon decides)."""
    url = f"https://dns.google/resolve?name={domain}&type=MX"
    for _ in range(2):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)
            answers = [a for a in data.get("Answer", []) if a.get("type") == 15]
            return any(not a["data"].strip().endswith(" .") for a in answers)  # "0 ." = null MX
        except Exception:  # noqa: BLE001
            continue
    return None


class Budget:
    def __init__(self, key, floor=None, every=None):
        self.key = key
        self.floor = config.DAILY_FLOOR if floor is None else floor
        self.every = every or config.BALANCE_EVERY
        self.lock, self.calls, self.stopped = threading.Lock(), 0, None
        self.start = balance(key)
        if self.start["remaining_daily_credits"] <= self.floor:
            self.stopped = f"daily credits already at {self.start['remaining_daily_credits']}"

    def allow(self):
        with self.lock:
            if self.stopped:
                return False
            self.calls += 1
            if self.calls % self.every:
                return True
        try:
            b = balance(self.key)
        except Exception as e:  # noqa: BLE001
            why = f"balance check failed: {e}"
        else:
            why = None
            if b["remaining_instant_credits"] < self.start["remaining_instant_credits"]:
                why = "instant (paid) credits started dropping"
            elif b["remaining_daily_credits"] <= self.floor:
                why = f"daily credits down to {b['remaining_daily_credits']}"
        if why:
            with self.lock:
                self.stopped = why
            return False
        return True


class Checker:
    """Cache-first Reoon check; pays only through the budget; appends new answers to the shared cache."""

    def __init__(self, key, budget):
        self.key, self.budget = key, budget
        self.cache = load_cache()
        self.lock = threading.Lock()
        self.paid = 0

    def check(self, email, fresh=False):
        res = None if fresh else self.cache.get(email)
        if res is not None and not fresh and res.get("status") in RETRY:
            res = None  # a cached unknown is re-asked here (the pools step already drops repeat unknowns)
        if res is None:
            if not self.budget.allow():
                return {"email": email, "status": "not_run"}
            res = reoon(email, self.key)
            with self.lock:
                self.paid += 1
                if res.get("status") not in RETRY:
                    self.cache[email] = res
                    with open(config.REOON_CACHE, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(res) + "\n")
        return res


def in_batches(items, fn, batch, pause, budget, label):
    """fn over items, `batch` at a time from config.WORKERS threads, sleeping `pause` between batches.
    Yields (item, result). Stops early (remaining items not yielded) when the budget stops."""
    for i in range(0, len(items), batch):
        chunk = items[i:i + batch]
        with ThreadPoolExecutor(max_workers=config.WORKERS) as ex:
            yield from zip(chunk, ex.map(fn, chunk))
        log(f"  {label}: {min(i + batch, len(items))}/{len(items)}")
        if budget.stopped:
            log("STOPPED:", budget.stopped)
            return
        if i + batch < len(items):
            time.sleep(pause)


def work_domain(domain, prefixes, checker):
    """Guess generic inboxes on one domain (enrich_auto_mfg.work_domain): skip no-MX domains, try the
    prefixes in order, the first safe / role_account that isn't catch-all wins, a catch-all ends it."""
    if has_mx(domain) is False:
        return {"email": "", "email_status": "", "outcome": "no_mx", "tried": ""}
    tried = []
    for p in prefixes:
        email = f"{p}@{domain}"
        res = checker.cache.get(email)
        if res is None:
            res = checker.check(email)
            if res.get("status") == "not_run":
                return {"email": "", "email_status": "", "outcome": "not_run", "tried": " ".join(tried)}
            if res.get("status") == "unknown":  # unknown is a reading for a guess; cache it like before
                with checker.lock:
                    checker.cache[email] = res
                    with open(config.REOON_CACHE, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(res) + "\n")
        tried.append(f"{p}:{res.get('status')}")
        if accepted(res):
            return {"email": email, "email_status": res["status"], "outcome": "found", "tried": " ".join(tried)}
        if res.get("status") == "catch_all" or res.get("is_catch_all"):
            return {"email": "", "email_status": "catch_all", "outcome": "catch_all", "tried": " ".join(tried)}
        if res.get("status") == "error":
            return {"email": "", "email_status": "error", "outcome": "error", "tried": " ".join(tried)}
    return {"email": "", "email_status": "", "outcome": "none_valid", "tried": " ".join(tried)}


def simulate_domain(prefixes, domain, cache):
    """Dry run of work_domain from the cache alone: (outcome or None, uncached checks it could cost)."""
    cost = 0
    for p in prefixes:
        res = cache.get(f"{p}@{domain}")
        if res is None:
            cost += 1
            continue
        if cost:
            continue  # an unpaid prefix comes first, so this cached answer may never be reached
        if accepted(res):
            return "found (cached)", 0
        if res.get("status") == "catch_all" or res.get("is_catch_all"):
            return "catch_all (cached)", 0
    return (None, cost) if cost else ("none_valid (cached)", 0)
