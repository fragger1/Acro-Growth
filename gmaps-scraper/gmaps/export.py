import csv
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from gmaps.emails import export_email, site_domain

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


@dataclass
class Skipped:
    """Leads left out of an export, by reason: Maps category, city (outside the client's area),
    and the junk email domain that was the lead's only email."""

    category: Counter = field(default_factory=Counter)
    area: Counter = field(default_factory=Counter)
    email: Counter = field(default_factory=Counter)

    def __bool__(self):
        return bool(self.category or self.area or self.email)


def export_leads(db, client, *, since=None, keyword=None, include_no_email=False, new_only=False,
                 any_category=False, any_area=False, out_dir: Path, now=None):
    """Write matching leads to a CSV and record them as exported.

    Leaves out, without recording them (so a later export can still pick them up):
    - leads whose Maps category matches none of the client's searches, unless any_category;
    - leads outside the client's service area (in_area from leads_for_export), unless any_area;
    - leads whose only emails are on domains shared by several unrelated websites, unless
      include_no_email. Those junk emails are also dropped from the other leads' email columns.
    Returns (path, count, Skipped).
    """
    client = client.strip().lower()
    now = now or datetime.now(timezone.utc)
    rows = db.fetch_leads(client, since, keyword, include_no_email, new_only)
    skipped = Skipped()
    if not any_category:
        skipped.category.update(r["category"] or "(none)" for r in rows if not r.get("category_match", True))
        rows = [r for r in rows if r.get("category_match", True)]
    if not any_area:
        skipped.area.update(r["city"] or "(no city)" for r in rows if not r.get("in_area", True))
        rows = [r for r in rows if r.get("in_area", True)]
    rows = _clean_emails(rows, db.shared_email_domains(), include_no_email, skipped)
    if not rows:
        return None, 0, skipped
    path = out_dir / f"{client}_{now:%Y%m%d_%H%M%S}.csv"
    write_csv(rows, path)
    filters = {"since": since, "keyword": keyword, "include_no_email": include_no_email, "new_only": new_only,
               "any_category": any_category, "any_area": any_area}
    db.record_export(client, filters, path.name, [r["place_id"] for r in rows])
    return path, len(rows), skipped


def _clean_emails(rows, shared, include_no_email, skipped):
    kept = []
    for r in rows:
        emails = [e for e in (r.get("all_emails") or "").split("; ") if e]
        usable, primary = export_email(emails, site_domain(r.get("website")), r.get("name"), shared)
        if primary is None and r.get("primary_email") and not include_no_email:
            skipped.email[r["primary_email"].rsplit("@", 1)[1]] += 1
            continue
        kept.append({**r, "primary_email": primary, "all_emails": "; ".join(usable)})
    return kept
