import csv
from datetime import datetime, timezone

from gmaps.export import COLUMNS, export_leads
from tests.fakes import FakeDb

NOW = datetime(2026, 9, 26, 13, 5, 0, tzinfo=timezone.utc)
LEAD = {"place_id": "P1", "name": "Acme", "category": "Dentist", "primary_email": "info@acme.com",
        "all_emails": "info@acme.com; a@acme.com", "phone": "1", "website": "https://acme.com",
        "address": "1 Main", "city": "Austin", "state": "Texas", "postal_code": "78701",
        "rating": 4.5, "review_count": 10, "maps_url": "https://maps", "category_match": True, "in_area": True}
OFF_TARGET = {**LEAD, "place_id": "P2", "name": "Coin ATM", "category": "Crypto ATM", "category_match": False}


def test_export_writes_csv_and_records(tmp_path):
    db = FakeDb(leads=[LEAD])
    path, count, skipped = export_leads(db, "Jeff", since="2026-09-01", keyword="dentists", new_only=True,
                                        out_dir=tmp_path, now=NOW)
    assert count == 1 and not skipped
    assert path.name == "jeff_20260926_130500.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0].keys()) == COLUMNS
    assert "place_id" not in rows[0] and "category_match" not in rows[0]
    assert rows[0]["primary_email"] == "info@acme.com"
    assert db.fetch_args == ("jeff", "2026-09-01", "dentists", False, True)
    client, filters, file_name, place_ids = db.exports[0]
    assert client == "jeff" and file_name == path.name and place_ids == ["P1"]
    assert filters["new_only"] is True


def test_export_with_no_rows_writes_nothing(tmp_path):
    db = FakeDb(leads=[])
    path, count, skipped = export_leads(db, "me", out_dir=tmp_path, now=NOW)
    assert path is None and count == 0 and not skipped
    assert db.exports == []
    assert list(tmp_path.iterdir()) == []


def test_off_target_categories_are_skipped_and_not_recorded(tmp_path):
    db = FakeDb(leads=[LEAD, OFF_TARGET])
    path, count, skipped = export_leads(db, "jeff", out_dir=tmp_path, now=NOW)
    assert count == 1
    assert skipped.category == {"Crypto ATM": 1}
    assert db.exports[0][3] == ["P1"]


def test_any_category_keeps_off_target_leads(tmp_path):
    db = FakeDb(leads=[LEAD, OFF_TARGET])
    path, count, skipped = export_leads(db, "jeff", any_category=True, out_dir=tmp_path, now=NOW)
    assert count == 2 and not skipped
    assert db.exports[0][3] == ["P1", "P2"]
    assert db.exports[0][1]["any_category"] is True


def test_only_off_target_leads_writes_nothing(tmp_path):
    db = FakeDb(leads=[OFF_TARGET])
    path, count, skipped = export_leads(db, "jeff", out_dir=tmp_path, now=NOW)
    assert path is None and count == 0
    assert skipped.category == {"Crypto ATM": 1}
    assert db.exports == []


FAR_AWAY = {**LEAD, "place_id": "P3", "city": "Topeka", "in_area": False}


def test_out_of_area_leads_are_skipped_and_not_recorded(tmp_path):
    db = FakeDb(leads=[LEAD, FAR_AWAY])
    path, count, skipped = export_leads(db, "jeff", out_dir=tmp_path, now=NOW)
    assert count == 1
    assert skipped.area == {"Topeka": 1}
    assert db.exports[0][3] == ["P1"]


def test_any_area_keeps_out_of_area_leads(tmp_path):
    db = FakeDb(leads=[LEAD, FAR_AWAY])
    path, count, skipped = export_leads(db, "jeff", any_area=True, out_dir=tmp_path, now=NOW)
    assert count == 2 and not skipped
    assert db.exports[0][1]["any_area"] is True


def _rows(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def test_junk_shared_email_is_replaced_by_the_next_usable_one(tmp_path):
    lead = {**LEAD, "website": "https://acmetires.com", "primary_email": "team@latofonts.com",
            "all_emails": "team@latofonts.com; office@acmesister.com"}
    db = FakeDb(leads=[lead], shared={"latofonts.com"})
    path, count, skipped = export_leads(db, "jeff", out_dir=tmp_path, now=NOW)
    row = _rows(path)[0]
    assert row["primary_email"] == "office@acmesister.com"
    assert row["all_emails"] == "office@acmesister.com"


def test_lead_whose_only_email_is_junk_is_skipped(tmp_path):
    lead = {**LEAD, "website": "https://acmetires.com", "primary_email": "x@mystore.com",
            "all_emails": "x@mystore.com"}
    db = FakeDb(leads=[LEAD, lead])
    path, count, skipped = export_leads(db, "jeff", out_dir=tmp_path, now=NOW)
    assert count == 1
    assert skipped.email == {"mystore.com": 1}
    assert db.exports[0][3] == ["P1"]


def test_shared_domain_named_after_the_business_is_kept(tmp_path):
    lead = {**LEAD, "name": "Cable Dahmer Buick GMC", "website": "https://cabledahmerbuick.com",
            "primary_email": "sales@cabledahmer.com", "all_emails": "sales@cabledahmer.com"}
    db = FakeDb(leads=[lead], shared={"cabledahmer.com"})
    path, count, skipped = export_leads(db, "jeff", out_dir=tmp_path, now=NOW)
    assert count == 1 and _rows(path)[0]["primary_email"] == "sales@cabledahmer.com"
