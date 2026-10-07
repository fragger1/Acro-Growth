from gmaps.recheck import recheck_emails


class RecheckDb:
    def __init__(self, places):
        self.places = places
        self.saved = []

    def places_missing_email(self):
        return list(self.places)

    def save_place_emails(self, place_id, emails, primary_email):
        self.saved.append((place_id, emails, primary_email))


def site(pid):
    return {"place_id": pid, "website": f"https://{pid}.com", "domain": f"{pid}.com"}


def finder(found):
    """Fake enrich_places: sets emails/primary_email from found[place_id], else nothing."""
    calls = []

    def find(places):
        calls.append([p["place_id"] for p in places])
        for p in places:
            emails, primary = found.get(p["place_id"], ([], None))
            p["emails"], p["primary_email"] = emails, primary

    find.calls = calls
    return find


def test_saves_only_places_where_emails_turn_up():
    db = RecheckDb([site("a"), site("b"), site("c")])
    find = finder({"a": (["info@a.com"], "info@a.com"), "c": (["joe@gmail.com"], None)})
    stats = recheck_emails(db, find, done=set(), mark_done=lambda ids: None, log=lambda m: None)
    assert db.saved == [("a", ["info@a.com"], "info@a.com"), ("c", ["joe@gmail.com"], None)]
    assert (stats.checked, stats.with_emails, stats.with_primary) == (3, 2, 1)


def test_skips_done_places_and_respects_limit():
    db = RecheckDb([site("a"), site("b"), site("c"), site("d")])
    find = finder({})
    stats = recheck_emails(db, find, done={"a"}, mark_done=lambda ids: None, limit=2, log=lambda m: None)
    assert find.calls == [["b", "c"]]
    assert stats.checked == 2


def test_marks_each_chunk_done_as_it_goes():
    db = RecheckDb([site(str(i)) for i in range(5)])
    marked = []
    recheck_emails(db, finder({}), done=set(), mark_done=marked.append, chunk=2, log=lambda m: None)
    assert marked == [["0", "1"], ["2", "3"], ["4"]]


def test_passes_places_with_empty_emails_so_the_finder_looks_them_up():
    db = RecheckDb([site("a")])
    seen = []
    recheck_emails(db, lambda places: seen.extend(places), done=set(), mark_done=lambda ids: None,
                   log=lambda m: None)
    assert seen[0]["emails"] == [] and seen[0]["website"] == "https://a.com"
