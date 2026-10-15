"""rules.py must say exactly what the dated scripts said. Needs the old folders under config.PROJECTS.

    python tests/test_rules_parity.py      (or pytest)
"""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from jeffpipe import config, rules  # noqa: E402

P = config.PROJECTS
PLACES = os.path.join(P, "JeffRerun_2026-10-15", "places_2026-10-15.json")


def _load(name, *path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(P, *path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _old():
    sys.path.insert(0, os.path.join(P, "MidwestRoofing_EmailFinder"))
    sys.path.insert(0, os.path.join(P, "JeffRuns7-8_Clean"))
    b2 = _load("b2", "JeffRuns19-20_2026-10-09", "clean_batch2.py")
    return {"b2": b2, "cr": b2.cr, "bp": b2.cr.bp, "bf": b2.cr.bf, "rv": b2.cr.rv,
            "rev15": _load("rev15", "JeffRerun_2026-10-15", "review.py"),
            "g11": _load("g11", "JeffLeads_2026-10-11", "guess.py"),
            "v11": _load("v11", "JeffLeads_2026-10-11", "verify.py"),
            "up11": _load("up11", "JeffLeads_2026-10-11", "build_upload.py")}


def test_constants():
    o = _old()
    import build_pool as mbp  # MidwestRoofing_EmailFinder
    import clean_leads as cl  # JeffRuns7-8_Clean
    assert rules.AREA == o["cr"].AREA
    assert rules.CHAINS == set(mbp.CHAINS)
    assert rules.CHAIN_DOMAINS == o["bp"].CHAIN_DOMAINS | o["bf"].EXTRA_CHAIN_DOMAINS
    assert rules.REVIEW_NATIONAL == o["rv"].NATIONAL
    assert rules.PLATFORMS == mbp.PLATFORMS and rules.WEBSITE_HOSTS == o["bp"].WEBSITE_HOSTS
    pairs = {"ROOFING": cl.ROOFING, "NATIONAL": cl.NATIONAL, "NATIONAL_EXTRA": o["bp"].NATIONAL_EXTRA,
             "GOV_DOMAIN": o["bp"].GOV_DOMAIN, "GOV_NAME": o["bp"].GOV_NAME, "MOBILE": o["bp"].MOBILE,
             "HOME_DAYCARE": o["bp"].HOME_DAYCARE, "HOME_SERVICE": o["cr"].HOME_SERVICE, "TENANT": o["cr"].TENANT,
             "PROPERTY": o["cr"].PROPERTY, "SMALL_ROOF": o["b2"].SMALL_ROOF, "RENTER_ADDR": o["b2"].RENTER_ADDR,
             "PERSONAL": cl.PERSONAL, "PERSONAL_EXTRA": o["cr"].PERSONAL_EXTRA, "JUNK_LOCAL": cl.JUNK_LOCAL,
             "JUNK_DOMAIN": cl.JUNK_DOMAIN, "JUNK_ROLE": o["cr"].JUNK_ROLE, "PLATFORM_INBOX": o["v11"].PLATFORM,
             "TIER_B": o["v11"].TIER_B, "CHURCH": o["up11"].CHURCH, "NOT_OWNER_SHOP": o["rev15"].NOT_OWNER_SHOP,
             "OWNER_EXCEPTIONS": o["rev15"].OWNER_EXCEPTIONS, "GUESS_PRIORITY": o["g11"].PRIORITY}
    for name, old in pairs.items():
        new = getattr(rules, name)
        assert (new.pattern, new.flags) == (old.pattern, old.flags), name
    assert rules.NAME_FIX == o["up11"].NAME_FIX
    assert [(rx, p) for rx, p in rules.GUESS_PREFIXES] == [(r.pattern, p) for r, p in o["g11"].PREFIXES]


def test_functions_on_10_15_places():
    """Same verdict as clean_batch2.reason / pick_email / review.owner_run on every 10/15 place."""
    o = _old()
    b2, cr = o["b2"], o["cr"]
    places = json.load(open(PLACES, encoding="utf-8"))
    known = {"kcmo.org", "example.com"}
    n = 0
    for p in places:
        r = {**p, "all_emails": "; ".join(p["emails"] or []), "review_count": p["review_count"] or 0}
        dom_old = cr.bp.site_domain({"domain": cr.host_of(p["website"])})
        dom = rules.site_domain(p["website"])
        assert dom == dom_old, p["website"]
        new_why, old_why = rules.reason(r, dom, known), b2.reason(r, dom_old, known)
        if old_why is None and new_why == "government / public school":
            pe = (p["primary_email"] or "").lower()
            assert rules.SCHOOL_GOV.search(dom or "") or rules.SCHOOL_GOV.search(pe.split("@")[-1])  # the 10/15 addition
        else:
            assert new_why == old_why, p["name"]
        old_email = b2.pick_email(r, dom_old)
        new_email = rules.pick_email(r, dom)
        if old_email and rules.PLATFORM_INBOX.search(old_email.split("@")[1]):
            assert new_email is None  # the one intended change: platform / agency / gov inboxes go to the guess
        else:
            assert new_email == old_email, (p["name"], old_email, new_email)
        assert rules.owner_run(p["category"]) == o["rev15"].owner_run(p["category"])
        assert rules.guess_prefixes(p["category"]) == o["g11"].prefixes(p["category"])
        n += 1
    assert n > 30000


if __name__ == "__main__":
    test_constants()
    print("constants: ok")
    test_functions_on_10_15_places()
    print("functions on 10/15 places: ok")
