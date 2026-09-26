import csv
from datetime import datetime, timezone

from gmaps.export import COLUMNS, export_leads
from tests.fakes import FakeDb

NOW = datetime(2026, 9, 26, 13, 5, 0, tzinfo=timezone.utc)
LEAD = {"place_id": "P1", "name": "Acme", "category": "Dentist", "primary_email": "info@acme.com",
        "all_emails": "info@acme.com; a@acme.com", "phone": "1", "website": "https://acme.com",
        "address": "1 Main", "city": "Austin", "state": "Texas", "postal_code": "78701",
        "rating": 4.5, "review_count": 10, "maps_url": "https://maps"}


def test_export_writes_csv_and_records(tmp_path):
    db = FakeDb(leads=[LEAD])
    path, count = export_leads(db, "Jeff", since="2026-09-01", keyword="dentists", new_only=True,
                               out_dir=tmp_path, now=NOW)
    assert count == 1
    assert path.name == "jeff_20260926_130500.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == COLUMNS
    assert "place_id" not in rows[0]
    assert rows[0]["primary_email"] == "info@acme.com"
    assert db.fetch_args == ("jeff", "2026-09-01", "dentists", False, True)
    client, filters, file_name, place_ids = db.exports[0]
    assert client == "jeff" and file_name == path.name and place_ids == ["P1"]
    assert filters["new_only"] is True


def test_export_with_no_rows_writes_nothing(tmp_path):
    db = FakeDb(leads=[])
    path, count = export_leads(db, "me", out_dir=tmp_path, now=NOW)
    assert path is None and count == 0
    assert db.exports == []
    assert list(tmp_path.iterdir()) == []
