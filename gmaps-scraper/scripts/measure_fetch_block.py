"""Compare httpx vs curl_cffi (Chrome impersonation) on homepages of places with no email.

Samples places that have a website but no email from Supabase, fetches each homepage once
with plain httpx (configured like the original email finder) and once with curl_cffi
impersonating Chrome, and prints how often each one gets a 200 vs a 403/blocked response.

    .venv\\Scripts\\python scripts\\measure_fetch_block.py --sample 50
    .venv\\Scripts\\python scripts\\measure_fetch_block.py https://site-a.example/ http://site-b.example/

Per-URL results are written to tmp/ (gitignored) since they contain lead websites.
"""
import argparse
import csv
import random
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import httpx
from curl_cffi import requests as curl_requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gmaps.config import ROOT, load_config  # noqa: E402
from gmaps.db import PAGE, Db  # noqa: E402
from gmaps.email_finder import extract_emails  # noqa: E402
from gmaps.emails import clean_emails  # noqa: E402

TIMEOUT = 10
MAX_REDIRECTS = 5
# The Chrome User-Agent the original httpx-based email finder sent.
HTTPX_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
BLOCKED_STATUSES = {401, 403, 429}


def sample_websites(n: int, seed: int) -> list[str]:
    db = Db.connect(load_config())
    rows: list[dict] = []
    offset = 0
    while True:
        page = (
            db.c.table("places").select("place_id,website")
            .not_.is_("website", "null").neq("website", "").eq("emails", "{}")
            .order("place_id").range(offset, offset + PAGE - 1).execute().data
        )
        rows += page
        if len(page) < PAGE:
            break
        offset += PAGE
    rng = random.Random(seed)
    picked = rng.sample(rows, min(n, len(rows)))
    print(f"sampled {len(picked)} of {len(rows)} places with a website and no email (seed={seed})")
    return [r["website"] for r in picked]


def outcome(status: int | None, error: str | None) -> str:
    if error:
        return "error"
    if status == 200:
        return "200"
    if status in BLOCKED_STATUSES:
        return "blocked"
    return "other"


def fetch_httpx(client: httpx.Client, url: str) -> dict:
    try:
        r = client.get(url)
        return {"status": r.status_code, "error": None, "text": r.text if r.status_code == 200 else ""}
    except Exception as e:  # measurement only: record every failure, never stop the run
        return {"status": None, "error": type(e).__name__, "text": ""}


def fetch_curl(session: curl_requests.Session, url: str) -> dict:
    try:
        r = session.get(url)
        return {"status": r.status_code, "error": None, "text": r.text if r.status_code == 200 else ""}
    except Exception as e:
        return {"status": None, "error": type(e).__name__, "text": ""}


def measure(urls: list[str], workers: int) -> list[dict]:
    client = httpx.Client(follow_redirects=True, timeout=TIMEOUT, max_redirects=MAX_REDIRECTS,
                          headers={"User-Agent": HTTPX_USER_AGENT})
    session = curl_requests.Session(impersonate="chrome", timeout=TIMEOUT, max_redirects=MAX_REDIRECTS)

    def one(item: tuple[int, str]) -> dict:
        i, url = item
        if "://" not in url:
            url = "http://" + url
        # Alternate which client goes first so a site that rate-limits the second hit
        # doesn't bias the comparison against one of them.
        if i % 2 == 0:
            h = fetch_httpx(client, url)
            c = fetch_curl(session, url)
        else:
            c = fetch_curl(session, url)
            h = fetch_httpx(client, url)
        return {
            "url": url,
            "httpx_status": h["status"], "httpx_error": h["error"],
            "httpx_outcome": outcome(h["status"], h["error"]),
            "httpx_emails": len(clean_emails(extract_emails(h["text"]))),
            "curl_status": c["status"], "curl_error": c["error"],
            "curl_outcome": outcome(c["status"], c["error"]),
            "curl_emails": len(clean_emails(extract_emails(c["text"]))),
        }

    try:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            return list(executor.map(one, enumerate(urls)))
    finally:
        client.close()
        session.close()


def report(results: list[dict]) -> None:
    n = len(results)
    print(f"\n{n} homepages fetched with each client")
    order = ["200", "blocked", "other", "error"]
    for name in ("httpx", "curl"):
        counts = Counter(r[f"{name}_outcome"] for r in results)
        statuses = Counter(r[f"{name}_status"] for r in results if r[f"{name}_status"] not in (None, 200))
        errors = Counter(r[f"{name}_error"] for r in results if r[f"{name}_error"])
        label = "httpx    " if name == "httpx" else "curl_cffi"
        print(f"  {label}: " + "  ".join(f"{k}={counts.get(k, 0)}" for k in order))
        if statuses:
            print(f"             non-200 statuses: {dict(statuses.most_common())}")
        if errors:
            print(f"             errors: {dict(errors.most_common())}")

    print("\n  httpx outcome -> curl_cffi outcome")
    pairs = Counter((r["httpx_outcome"], r["curl_outcome"]) for r in results)
    for (h, c), count in sorted(pairs.items(), key=lambda kv: -kv[1]):
        print(f"    {h:>7} -> {c:<7} {count}")

    recovered = [r for r in results if r["httpx_outcome"] != "200" and r["curl_outcome"] == "200"]
    lost = [r for r in results if r["httpx_outcome"] == "200" and r["curl_outcome"] != "200"]
    emails_recovered = [r for r in recovered if r["curl_emails"]]
    print(f"\n  curl_cffi 200 where httpx was not: {len(recovered)}/{n}"
          f" ({len(emails_recovered)} of those have an email on the homepage)")
    print(f"  httpx 200 where curl_cffi was not: {len(lost)}/{n}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("urls", nargs="*", help="websites to test instead of a Supabase sample")
    parser.add_argument("--sample", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20261007)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    urls = args.urls or sample_websites(args.sample, args.seed)
    if not urls:
        raise SystemExit("no websites to test")
    results = measure(urls, args.workers)
    report(results)

    out_dir = ROOT / "tmp"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"fetch_block_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)
    print(f"\nper-URL results: {out}")


if __name__ == "__main__":
    main()
