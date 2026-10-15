"""verify / guess against a fake Reoon: no network, no credits. python tests/test_spend_offline.py (or pytest)."""
import csv
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jeffpipe import config, reoon, util, verify  # noqa: E402


class FakeReoon:
    def __init__(self, answers, instant_drop_after=None):
        self.answers, self.calls, self.instant_drop_after = answers, [], instant_drop_after

    def balance(self, _key):
        paid = len(self.calls)
        instant = 1000 - (1 if self.instant_drop_after is not None and paid >= self.instant_drop_after else 0)
        return {"remaining_daily_credits": 500 - paid, "remaining_instant_credits": instant}

    def reoon(self, email, _key):
        self.calls.append(email)
        seq = self.answers.get(email, ["invalid"])
        st = seq[min(self.calls.count(email) - 1, len(seq) - 1)]
        return {"email": email, "status": st.replace("+ca", ""), "is_catch_all": st.endswith("+ca")}


def _setup(tmp, fake, rows, name):
    config.PROJECTS = tmp
    config.REOON_CACHE = os.path.join(tmp, "cache.jsonl")
    config.BALANCE_EVERY = 1
    reoon.balance, reoon.reoon, reoon.has_mx = fake.balance, fake.reoon, lambda d: d != "nomx.com"
    verify.time.sleep = reoon.time.sleep = lambda s: None
    os.environ["REOON_API_KEY"] = "test"
    run = util.Run("2099-01-01")
    with open(run.path(name), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return run


def test_verify_retry_and_cache():
    with tempfile.TemporaryDirectory() as tmp:
        fake = FakeReoon({"a@x.com": ["safe"], "b@x.com": ["unknown", "role_account"], "c@x.com": ["unknown", "unknown"],
                          "d@x.com": ["safe+ca"], "e@x.com": ["catch_all"]})
        rows = [{"email": e, "name": e, "category": "Warehouse", "pool": "offtarget"} for e in
                ("a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com")]
        run = _setup(tmp, fake, rows, "reviewed_email.csv")
        verify.verify(run, batch=2, pause=0)
        kept = {r["email"] for r in util.read_csv(run.path("reoon_kept.csv"))}
        assert kept == {"a@x.com", "b@x.com"}, kept
        assert fake.calls.count("b@x.com") == 2 and fake.calls.count("c@x.com") == 2  # unknown retried once
        assert fake.calls.count("a@x.com") == 1
        cached = [json.loads(line)["email"] for line in open(config.REOON_CACHE)]
        assert "c@x.com" not in cached and "a@x.com" in cached  # unknown never cached
        n = len(fake.calls)
        verify.verify(run, batch=2, pause=0)  # resume: everything settled, nothing paid
        assert len(fake.calls) == n


def test_instant_credits_stop():
    with tempfile.TemporaryDirectory() as tmp:
        emails = [f"u{i}@x.com" for i in range(8)]
        fake = FakeReoon({e: ["safe"] for e in emails}, instant_drop_after=3)
        run = _setup(tmp, fake, [{"email": e, "name": e, "category": "Warehouse", "pool": "ontarget"} for e in emails],
                     "reviewed_email.csv")
        verify.verify(run, batch=2, pause=0)
        info = run.manifest["steps"]["verify"]
        assert info["stopped"] and not info["complete"], info
        assert len(fake.calls) <= 4, fake.calls  # stops within BALANCE_EVERY of the instant balance moving


def test_guess_outcomes():
    with tempfile.TemporaryDirectory() as tmp:
        fake = FakeReoon({"info@shop.com": ["invalid"], "office@shop.com": ["role_account"],
                          "info@ca.com": ["catch_all"], "office@church.org": ["safe"]})
        rows = [{"domain": d, "name": d, "category": c, "review_count": "1", "pool": "guess"}
                for d, c in (("shop.com", "Hardware store"), ("ca.com", "Bar"), ("nomx.com", "Bar"),
                             ("church.org", "Baptist church"), ("none.com", "Bar"))]
        run = _setup(tmp, fake, rows, "reviewed_guess.csv")
        verify.guess(run, batch=2, pause=0)
        res = {r["domain"]: r["outcome"] for r in util.read_csv(run.path("guess_results.csv"))}
        assert res == {"shop.com": "found", "ca.com": "catch_all", "nomx.com": "no_mx", "church.org": "found",
                       "none.com": "none_valid"}, res
        found = {r["email"] for r in util.read_csv(run.path("guess_found.csv"))}
        assert found == {"office@shop.com", "office@church.org"}
        assert fake.calls[0] in ("office@church.org", "info@shop.com")  # churches go first (GUESS_PRIORITY)


if __name__ == "__main__":
    test_verify_retry_and_cache()
    test_instant_credits_stop()
    test_guess_outcomes()
    print("offline spend tests: ok")
