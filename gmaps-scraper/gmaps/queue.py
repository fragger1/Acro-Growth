import re
from datetime import datetime, timedelta, timezone

RECENT_DAYS = 30


def parse_locations(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;\n]", text) if part.strip()]


def build_query(keyword: str, location: str) -> str:
    return f"{keyword.strip()} in {location.strip()}"


def _blocks(row: dict, now: datetime, force: bool) -> bool:
    if row["status"] in ("pending", "running"):
        return True
    if force or row["status"] != "done" or not row.get("finished_at"):
        return False
    finished = datetime.fromisoformat(row["finished_at"])
    return finished >= now - timedelta(days=RECENT_DAYS)


def plan_searches(keyword, locations, client, limit, existing, now, force):
    client = client.strip().lower()
    blocked = {row["query"] for row in existing if _blocks(row, now, force)}
    rows, skipped, seen = [], [], set()
    for location in locations:
        query = build_query(keyword, location)
        if query in seen:
            continue
        seen.add(query)
        if query in blocked:
            skipped.append(query)
            continue
        rows.append({
            "keyword": keyword.strip(),
            "location": location.strip(),
            "query": query,
            "client": client,
            "place_limit": limit,
        })
    return rows, skipped


def add_searches(db, keyword, locations_text, client, limit=None, force=False, now=None):
    now = now or datetime.now(timezone.utc)
    locations = parse_locations(locations_text)
    queries = [build_query(keyword, loc) for loc in locations]
    existing = db.existing_searches(client.strip().lower(), queries)
    rows, skipped = plan_searches(keyword, locations, client, limit, existing, now, force)
    return db.insert_searches(rows), skipped
