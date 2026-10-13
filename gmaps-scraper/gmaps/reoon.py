"""Verify the primary email of each lead in a CSV with Reoon's single-email endpoint.

Bulk verification gave errors before, so every email is its own single-email request (several
run in parallel), transient failures are retried, and stops on account problems (bad key,
no credits) instead of burning through the list. Every verdict is appended to a results file as
it arrives, so an interrupted run resumes without paying for the same email twice.
"""
import csv
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

API_URL = "https://emailverifier.reoon.com/api/v1/verify"
MODE = "power"  # quick mode can't tell safe from catch-all/role
KEEP_STATUSES = ("safe", "role_account")
STATUS_COLUMN = "reoon_status"
REQUEST_TIMEOUT = 120  # power mode does a live SMTP check and can take a while
RETRIES = 4
RETRY_BACKOFF = (5, 15, 45, 90)
ACCOUNT_ERROR_WORDS = ("key", "credit", "balance", "quota", "unauthor", "limit exceeded")


class ReoonAccountError(Exception):
    """Reoon refused the request for an account reason (key, credits); retrying won't help."""


class ReoonTransientError(Exception):
    pass


def verify_email(email: str, api_key: str, client) -> str:
    """Reoon's status for email (safe, invalid, catch_all, role_account, ...)."""
    try:
        response = client.get(API_URL, params={"email": email, "key": api_key, "mode": MODE},
                              timeout=REQUEST_TIMEOUT)
    except httpx.HTTPError as exc:
        raise ReoonTransientError(f"{type(exc).__name__}: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    status = str(body.get("status", "")).strip().lower()
    reason = str(body.get("reason") or body.get("message") or response.text[:200])
    if response.status_code == 200 and status and status != "error":
        return status  # any verdict; only KEEP_STATUSES are kept
    if response.status_code == 429 or response.status_code >= 500:
        raise ReoonTransientError(f"HTTP {response.status_code}: {reason}")
    if response.status_code in (401, 402, 403) or any(w in reason.lower() for w in ACCOUNT_ERROR_WORDS):
        raise ReoonAccountError(f"HTTP {response.status_code}: {reason}")
    raise ReoonTransientError(f"HTTP {response.status_code}: {reason}")


def verify_with_retries(email, api_key, client, sleep=time.sleep, log=print) -> str:
    for attempt in range(RETRIES + 1):
        try:
            return verify_email(email, api_key, client)
        except ReoonTransientError as exc:
            if attempt == RETRIES:
                raise
            wait = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
            log(f"  {email}: {exc}; retrying in {wait}s")
            sleep(wait)


def load_results(path: Path) -> dict[str, str]:
    results = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                results[row["email"]] = row["status"]
            except (ValueError, KeyError):
                continue
    return results


@dataclass
class VerifyStats:
    kept: int = 0
    dropped: int = 0
    errors: int = 0
    no_email: int = 0
    statuses: dict = field(default_factory=dict)
    stopped: str | None = None


def verify_csv(in_path: Path, out_path: Path, errors_path: Path, results_path: Path, api_key: str, *,
               workers: int = 10, delay: float = 0.0, client=None, sleep=time.sleep,
               log=print) -> VerifyStats:
    """Write the leads whose primary email Reoon calls safe or role_account to out_path, with
    the verdict in a reoon_status column. Leads Reoon couldn't check go to errors_path (a rerun
    retries them); every other verdict is dropped. Each email is its own single-email request;
    up to `workers` run at once. Stops early on a Reoon account error."""
    with in_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = list(reader)

    results = load_results(results_path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    stats = VerifyStats()
    to_check = list(dict.fromkeys(e for e in (_email(r) for r in rows) if e and e not in results))
    log(f"verify: {len(rows)} leads, {len(to_check)} emails to check with Reoon "
        f"({len(results)} already checked), {workers} at a time")

    owns_client = client is None
    client = client or httpx.Client(headers={"User-Agent": "gmaps-scraper"},
                                    limits=httpx.Limits(max_connections=workers))
    lock = threading.Lock()
    stop = threading.Event()
    done = [0]

    def check(email: str) -> None:
        if stop.is_set():
            return
        if delay:
            sleep(delay)
        try:
            status = verify_with_retries(email, api_key, client, sleep=sleep, log=log)
        except ReoonAccountError as exc:
            if not stop.is_set():
                stop.set()
                stats.stopped = str(exc)
                log(f"verify: stopping, Reoon refused the request: {exc}")
            return
        except ReoonTransientError as exc:
            log(f"  {email}: gave up after {RETRIES} retries: {exc}")
            return
        with lock:
            results[email] = status
            results_file.write(json.dumps({"email": email, "status": status}) + "\n")
            results_file.flush()
            done[0] += 1
            if done[0] % 50 == 0:
                log(f"verify: checked {done[0]}/{len(to_check)}")

    try:
        with results_path.open("a", encoding="utf-8") as results_file:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                list(executor.map(check, to_check))
    finally:
        if owns_client:
            client.close()

    kept, errored = [], []
    for row in rows:
        email = _email(row)
        if not email:
            stats.no_email += 1
            continue
        status = results.get(email)
        if status is None:
            stats.errors += 1
            errored.append(row)
            continue
        stats.statuses[status] = stats.statuses.get(status, 0) + 1
        if status in KEEP_STATUSES:
            stats.kept += 1
            kept.append({**row, STATUS_COLUMN: status})
        else:
            stats.dropped += 1

    _write(out_path, columns + [STATUS_COLUMN], kept)
    if errored:
        _write(errors_path, columns, errored)
    elif errors_path.exists():
        errors_path.unlink()
    return stats


def _email(row: dict) -> str:
    return (row.get("primary_email") or "").strip().lower()


def _write(path: Path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
