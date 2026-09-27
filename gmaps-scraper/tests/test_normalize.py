import json
from pathlib import Path

from gmaps.normalize import PLACE_KEYS, dedupe_places, normalize

FIXTURE = Path(__file__).parent / "fixtures" / "gosom_sample.jsonl"


def load():
    return [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines() if line]


def test_full_entry():
    p = normalize(load()[0])
    assert set(p) == set(PLACE_KEYS)
    assert p["place_id"] == "ChIJacme"
    assert p["name"] == "Acme Coffee"
    assert p["category"] == "Coffee shop"
    assert p["categories"] == ["Coffee shop", "Cafe"]
    assert p["city"] == "Austin" and p["state"] == "Texas" and p["postal_code"] == "78701"
    assert p["website"] == "https://www.acmecoffee.com/"
    assert p["domain"] == "acmecoffee.com"
    assert p["phone"] == "(512) 555-0100"
    assert p["rating"] == 4.6 and p["review_count"] == 214
    assert p["lat"] == 30.2672 and p["lng"] == -97.7431
    assert p["maps_url"].startswith("https://www.google.com/maps/")
    assert p["hours"] == {"Monday": ["7 AM-5 PM"]}
    assert p["emails"] == ["info@acmecoffee.com"]  # logo@2x.png and owner@gmail.com dropped
    assert p["primary_email"] == "info@acmecoffee.com"


def test_raw_strips_heavy_keys():
    raw = normalize(load()[0])["raw"]
    for key in ("user_reviews", "user_reviews_extended", "images", "popular_times"):
        assert key not in raw
    assert raw["cid"] == "111"


def test_empty_values_become_none():
    p = normalize(load()[1])
    assert p["website"] is None and p["domain"] is None and p["phone"] is None
    assert p["rating"] is None and p["review_count"] == 0
    assert p["hours"] is None and p["postal_code"] is None
    assert p["emails"] == [] and p["primary_email"] is None


def test_missing_place_id_returns_none():
    assert normalize(load()[2]) is None


def test_dedupe_keeps_first_and_drops_none():
    places = dedupe_places([normalize(e) for e in load()])
    assert [p["place_id"] for p in places] == ["ChIJacme", "ChIJnosite"]
    assert places[0]["name"] == "Acme Coffee"
