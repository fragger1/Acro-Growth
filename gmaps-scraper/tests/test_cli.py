import argparse
import logging

import pytest

import gmaps.db as db_module
from gmaps import cli
from gmaps.config import Config


def test_positive_int_accepts_positive():
    assert cli.positive_int("1") == 1
    assert cli.positive_int("500") == 500


@pytest.mark.parametrize("value", ["0", "-1", "-500"])
def test_positive_int_rejects_zero_and_negative(value):
    with pytest.raises(argparse.ArgumentTypeError):
        cli.positive_int(value)


def test_positive_int_rejects_non_integer():
    with pytest.raises(argparse.ArgumentTypeError):
        cli.positive_int("abc")


def test_run_limit_argument_uses_positive_int(capsys):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    cli._build_run_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--limit", "0"])


def test_queue_add_limit_argument_uses_positive_int():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")
    cli._build_queue_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["queue", "add", "dentists", "--locations", "x", "--client", "me", "--limit", "-3"])


class _FakeLog:
    def __init__(self):
        self.lines = []

    def info(self, msg):
        self.lines.append(msg)

    def error(self, msg):
        self.lines.append(msg)

    def exception(self, msg):
        self.lines.append(msg)


class _FakeDbForRun:
    def __init__(self, nightly_limit=None):
        self._nightly_limit = nightly_limit

    def get_setting(self, key, default=None):
        if key == "nightly_limit":
            return self._nightly_limit
        if key == "concurrency":
            return 3
        if key == "depth":
            return 12
        return default

    def reset_stale(self):
        return 0

    def create_run(self, trigger, limit):
        return 1

    def claim_next_search(self, run_id):
        return None

    def finish_run(self, run_id, status, stats, notes):
        pass


def _cfg(tmp_path, gosom_exists=True):
    gosom = tmp_path / "gosom.exe"
    if gosom_exists:
        gosom.write_text("", encoding="utf-8")
    return Config(supabase_url="https://x", supabase_key="key", proxies=[], gosom_path=gosom)


def test_cmd_run_rejects_zero_nightly_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    args = argparse.Namespace(all=False, limit=None, scheduled=False)
    log = _FakeLog()
    db = _FakeDbForRun(nightly_limit=0)
    with pytest.raises(SystemExit):
        cli.cmd_run(args, db, _cfg(tmp_path), log)
    assert any("nightly_limit" in line for line in log.lines)


def test_cmd_run_rejects_negative_nightly_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    args = argparse.Namespace(all=False, limit=None, scheduled=False)
    log = _FakeLog()
    db = _FakeDbForRun(nightly_limit=-5)
    with pytest.raises(SystemExit):
        cli.cmd_run(args, db, _cfg(tmp_path), log)


def test_cmd_run_logs_unlimited_only_when_limit_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr("gmaps.runner.run", lambda *a, **k: "stats")
    monkeypatch.setattr("gmaps.scraper.GosomScraper", lambda cfg, concurrency: None)

    args = argparse.Namespace(all=True, limit=None, scheduled=False)
    log = _FakeLog()
    db = _FakeDbForRun(nightly_limit=None)
    cli.cmd_run(args, db, _cfg(tmp_path), log)
    assert any("limit=unlimited" in line for line in log.lines)


def test_cmd_run_second_instance_exits_quietly(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    (tmp_path / "tmp").mkdir()

    from gmaps.lock import run_lock

    args = argparse.Namespace(all=True, limit=None, scheduled=False)
    log = _FakeLog()
    db = _FakeDbForRun(nightly_limit=None)

    with run_lock(tmp_path / "tmp" / "run.lock"):
        cli.cmd_run(args, db, _cfg(tmp_path), log)

    assert any("another gmaps run is active" in line for line in log.lines)


def test_main_logs_and_reraises_on_command_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda: _cfg(tmp_path))

    class FailingDb:
        def status_summary(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(db_module.Db, "connect", classmethod(lambda cls, cfg: FailingDb()))
    logging.getLogger("gmaps").handlers.clear()

    with caplog.at_level(logging.ERROR, logger="gmaps"):
        with pytest.raises(RuntimeError):
            cli.main(["status"])

    assert any("gmaps command failed" in r.message for r in caplog.records)
