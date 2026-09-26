from gmaps.emails import clean_emails, pick_primary, site_domain

PLACE_KEYS = (
    "place_id", "name", "category", "categories", "address", "city", "state", "postal_code",
    "country", "phone", "website", "domain", "rating", "review_count", "lat", "lng", "maps_url",
    "hours", "emails", "primary_email", "raw",
)
HEAVY_RAW_KEYS = ("user_reviews", "user_reviews_extended", "images", "popular_times")


def _s(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def normalize(entry: dict) -> dict | None:
    place_id = _s(entry.get("place_id"))
    if not place_id:
        return None
    addr = entry.get("complete_address") or {}
    website = _s(entry.get("web_site"))
    domain = site_domain(website)
    emails = clean_emails(entry.get("emails"))
    review_count = int(entry.get("review_count") or 0)
    rating = entry.get("review_rating")
    return {
        "place_id": place_id,
        "name": _s(entry.get("title")),
        "category": _s(entry.get("category")),
        "categories": list(entry.get("categories") or []),
        "address": _s(entry.get("address")),
        "city": _s(addr.get("city")),
        "state": _s(addr.get("state")),
        "postal_code": _s(addr.get("postal_code")),
        "country": _s(addr.get("country")),
        "phone": _s(entry.get("phone")),
        "website": website,
        "domain": domain,
        "rating": float(rating) if rating and review_count > 0 else None,
        "review_count": review_count,
        "lat": entry.get("latitude"),
        "lng": entry.get("longtitude", entry.get("longitude")),
        "maps_url": _s(entry.get("link")),
        "hours": entry.get("open_hours") or None,
        "emails": emails,
        "primary_email": pick_primary(emails, domain),
        "raw": {k: v for k, v in entry.items() if k not in HEAVY_RAW_KEYS},
    }


def dedupe_places(places: list[dict | None]) -> list[dict]:
    seen: dict[str, dict] = {}
    for place in places:
        if place and place["place_id"] not in seen:
            seen[place["place_id"]] = place
    return list(seen.values())
