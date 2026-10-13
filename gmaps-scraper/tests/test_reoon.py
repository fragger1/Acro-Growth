import csv
import json

import httpx
import pytest

from gmaps import reoon
from gmaps.reoon import ReoonAccountError, verify_csv, verify_email

COLUMNS = ["name", "primary_email", "website"]


class FakeResponse:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self.body = body
        self.text = text or json.dumps(body or {})

    def json(self):
        if self.body is None:
            raise ValueError("no json")
        return self.body


class FakeClient:
    """Answers each email from a dict of email -> list of responses (or exceptions), in order."""

    def __init__(self, answers):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params["email"])
        answer = self.answers[params["email"]].pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def ok(status):
    return FakeResponse(200, {"email": "x", "status": status})


def _write(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def _read(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _paths(tmp_path):
    return tmp_path / "in.csv", tmp_path / "out.csv", tmp_path / "err.csv", tmp_path / "state" / "res.jsonl"


def test_verify_email_uses_power_mode_and_returns_status():
    client = FakeClient({"a@a.com": [ok("safe")]})
    assert verify_email("a@a.com", "KEY", client) == "safe"


@pytest.mark.parametrize("response", [
    FakeResponse(401, {"status": "error", "reason": "Invalid API key"}),
    FakeResponse(200, {"status": "error", "reason": "Not enough credits"}),
])
def test_verify_email_account_errors(response):
    with pytest.raises(ReoonAccountError):
        verify_email("a@a.com", "KEY", FakeClient({"a@a.com": [response]}))


def test_keeps_only_safe_and_role(tmp_path):
    in_path, out_path, err_path, res_path = _paths(tmp_path)
    _write(in_path, [
        {"name": "A", "primary_email": "a@a.com", "website": "a.com"},
        {"name": "B", "primary_email": "info@b.com", "website": "b.com"},
        {"name": "C", "primary_email": "c@c.com", "website": "c.com"},
        {"name": "D", "primary_email": "d@d.com", "website": "d.com"},
        {"name": "E", "primary_email": "", "website": "e.com"},
    ])
    client = FakeClient({"a@a.com": [ok("safe")], "info@b.com": [ok("role_account")],
                         "c@c.com": [ok("catch_all")], "d@d.com": [ok("invalid")]})
    sleeps = []
    stats = verify_csv(in_path, out_path, err_path, res_path, "KEY", delay=2, client=client,
                       sleep=sleeps.append, log=lambda m: None)
    rows = _read(out_path)
    assert [(r["name"], r["reoon_status"]) for r in rows] == [("A", "safe"), ("B", "role_account")]
    assert (stats.kept, stats.dropped, stats.errors, stats.no_email) == (2, 2, 0, 1)
    assert sleeps == [2, 2, 2]  # one pause between each of the 4 calls, never concurrent
    assert not err_path.exists()


def test_transient_errors_retry_then_resume_without_rechecking(tmp_path):
    in_path, out_path, err_path, res_path = _paths(tmp_path)
    _write(in_path, [
        {"name": "A", "primary_email": "a@a.com", "website": "a.com"},
        {"name": "B", "primary_email": "b@b.com", "website": "b.com"},
    ])
    flaky = [httpx.ConnectError("boom")] * (reoon.RETRIES + 1)
    client = FakeClient({"a@a.com": [FakeResponse(503, text="busy"), ok("safe")], "b@b.com": flaky})
    stats = verify_csv(in_path, out_path, err_path, res_path, "KEY", client=client,
                       sleep=lambda s: None, log=lambda m: None)
    assert (stats.kept, stats.errors) == (1, 1)
    assert [r["name"] for r in _read(err_path)] == ["B"]

    # Rerun: a@a.com comes from the results file, only b@b.com is sent to Reoon again.
    client = FakeClient({"b@b.com": [ok("role_account")]})
    stats = verify_csv(in_path, out_path, err_path, res_path, "KEY", client=client,
                       sleep=lambda s: None, log=lambda m: None)
    assert client.calls == ["b@b.com"]
    assert [r["name"] for r in _read(out_path)] == ["A", "B"]
    assert stats.errors == 0 and not err_path.exists()


def test_account_error_stops_and_leaves_rest_for_rerun(tmp_path):
    in_path, out_path, err_path, res_path = _paths(tmp_path)
    _write(in_path, [
        {"name": "A", "primary_email": "a@a.com", "website": "a.com"},
        {"name": "B", "primary_email": "b@b.com", "website": "b.com"},
        {"name": "C", "primary_email": "c@c.com", "website": "c.com"},
    ])
    client = FakeClient({"a@a.com": [ok("safe")],
                         "b@b.com": [FakeResponse(402, {"status": "error", "reason": "Insufficient credits"})]})
    stats = verify_csv(in_path, out_path, err_path, res_path, "KEY", client=client,
                       sleep=lambda s: None, log=lambda m: None)
    assert client.calls == ["a@a.com", "b@b.com"]  # c@c.com never sent
    assert stats.stopped and stats.kept == 1 and stats.errors == 2
    assert [r["name"] for r in _read(err_path)] == ["B", "C"]
