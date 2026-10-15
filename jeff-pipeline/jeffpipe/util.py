"""Run folder, manifest and CSV helpers."""
import csv
import datetime as dt
import glob
import json
import os

from . import config


def log(*a):
    print(*a, flush=True)


def read_csv(path):
    with open(path, encoding="utf-8-sig", errors="ignore", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, fields=None):
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def now():
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Run:
    """One dated run folder (PROJECTS/JeffRun_<date>/) with its run.json manifest."""

    def __init__(self, date, ignore_history=()):
        self.date = date
        self.dir = os.path.join(config.PROJECTS, config.RUN_PREFIX + date)
        os.makedirs(self.dir, exist_ok=True)
        self.manifest_path = self.path("run.json")
        self.manifest = json.load(open(self.manifest_path, encoding="utf-8")) if os.path.exists(self.manifest_path) else {
            "date": date, "created": now(), "steps": {}}
        # Folders left out of the dedupe history: this run always (its own uploads and drops must not
        # dedupe against themselves), plus any given with --ignore-history (to replay an older run).
        self.exclude = {os.path.normcase(os.path.abspath(self.dir))}
        for f in ignore_history:
            self.exclude.add(os.path.normcase(os.path.abspath(f if os.path.isabs(f) else os.path.join(config.PROJECTS, f))))
        if ignore_history:
            self.manifest["ignore_history"] = sorted(ignore_history)

    def path(self, name):
        return os.path.join(self.dir, name)

    def has(self, name):
        return os.path.exists(self.path(name))

    def need(self, name, hint):
        if not self.has(name):
            raise SystemExit(f"missing {self.path(name)}: {hint}")
        return self.path(name)

    def done(self, step, **info):
        self.manifest["steps"][step] = {"at": now(), **info}
        self.save()

    def save(self):
        with open(self.manifest_path, "w", encoding="utf-8") as fh:
            json.dump(self.manifest, fh, indent=1)


def previous_runs(before_date):
    """Earlier JeffRun_ folders, newest first."""
    out = []
    for d in glob.glob(os.path.join(config.PROJECTS, config.RUN_PREFIX + "*")):
        date = os.path.basename(d)[len(config.RUN_PREFIX):]
        if date < before_date and os.path.exists(os.path.join(d, "run.json")):
            out.append(d)
    return sorted(out, reverse=True)
