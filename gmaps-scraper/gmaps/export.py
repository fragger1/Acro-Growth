import csv
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

COLUMNS = [
    "name", "category", "primary_email", "all_emails", "phone", "website", "address",
    "city", "state", "postal_code", "rating", "review_count", "maps_url",
]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def export_leads(db, client, *, since=None, keyword=None, include_no_email=False, new_only=False,
                 any_category=False, out_dir: Path, now=None):
    """Write matching leads to a CSV and record them as exported.

    Unless any_category is set, leads whose Maps category matches none of the client's searches
    (category_match from leads_for_export) are left out and not recorded, so a later
    --any-category export can still pick them up. Returns (path, count, skipped categories).
    """
    client = client.strip().lower()
    now = now or datetime.now(timezone.utc)
    rows = db.fetch_leads(client, since, keyword, include_no_email, new_only)
    skipped = Counter()
    if not any_category:
        skipped.update(r["category"] or "(none)" for r in rows if not r.get("category_match", True))
        rows = [r for r in rows if r.get("category_match", True)]
    if not rows:
        return None, 0, skipped
    path = out_dir / f"{client}_{now:%Y%m%d_%H%M%S}.csv"
    write_csv(rows, path)
    filters = {"since": since, "keyword": keyword, "include_no_email": include_no_email, "new_only": new_only,
               "any_category": any_category}
    db.record_export(client, filters, path.name, [r["place_id"] for r in rows])
    return path, len(rows), skipped
