"""Re-run the email finder on places whose earlier lookup found nothing.

Before the finder fetched sites as Chrome (curl_cffi), bot-protected sites answered 403 and those
places were saved with no emails; runs never revisit known places, so this fills them in.
"""

from dataclasses import dataclass

CHUNK = 200


@dataclass
class RecheckStats:
    checked: int = 0
    with_emails: int = 0
    with_primary: int = 0


def recheck_emails(db, find_emails, *, done: set[str], mark_done, limit: int | None = None,
                   chunk: int = CHUNK, log=print) -> RecheckStats:
    """Look up emails again for places with a website and no emails, skipping place_ids in done.

    Saves each place where emails turn up and calls mark_done(place_ids) after every chunk, so an
    interrupted recheck resumes where it stopped.
    """
    targets = [r for r in db.places_missing_email() if r["place_id"] not in done]
    if limit is not None:
        targets = targets[:limit]
    log(f"recheck: {len(targets)} places with a website and no email to check")
    stats = RecheckStats()
    for i in range(0, len(targets), chunk):
        places = [{**r, "emails": []} for r in targets[i : i + chunk]]
        find_emails(places)
        for p in places:
            if p["emails"]:
                db.save_place_emails(p["place_id"], p["emails"], p.get("primary_email"))
                stats.with_emails += 1
                stats.with_primary += p.get("primary_email") is not None
        stats.checked += len(places)
        mark_done([p["place_id"] for p in places])
        log(f"recheck: {stats.checked}/{len(targets)} checked, {stats.with_primary} now have a usable email")
    return stats
