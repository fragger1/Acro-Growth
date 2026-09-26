import csv
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
                 out_dir: Path, now=None):
    client = client.strip().lower()
    now = now or datetime.now(timezone.utc)
    rows = db.fetch_leads(client, since, keyword, include_no_email, new_only)
    if not rows:
        return None, 0
    path = out_dir / f"{client}_{now:%Y%m%d_%H%M%S}.csv"
    write_csv(rows, path)
    filters = {"since": since, "keyword": keyword, "include_no_email": include_no_email, "new_only": new_only}
    db.record_export(client, filters, path.name, [r["place_id"] for r in rows])
    return path, len(rows)
