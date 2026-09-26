from gmaps.emails import clean_emails, pick_primary, site_domain


def test_clean_lowercases_dedupes_and_strips_mailto():
    assert clean_emails(["Info@Acme.com", "mailto:info@acme.com", " sales@acme.com "]) == [
        "info@acme.com",
        "sales@acme.com",
    ]


def test_clean_drops_junk():
    raw = [
        "logo@2x.png",
        "user@example.com",
        "abc123@sentry.io",
        "x@sentry-next.wixpress.com",
        "not-an-email",
        "yourname@acme.com",
        "real@acme.com",
    ]
    assert clean_emails(raw) == ["real@acme.com"]


def test_clean_drops_personal_inboxes():
    raw = [
        "joe@gmail.com", "a@googlemail.com", "b@yahoo.com", "c@yahoo.co.uk", "d@hotmail.com",
        "e@outlook.com", "f@live.com", "g@aol.com", "h@icloud.com", "i@me.com", "j@comcast.net",
        "k@proton.me", "info@acme.com", "sales@acme.com",
    ]
    assert clean_emails(raw) == ["info@acme.com", "sales@acme.com"]


def test_clean_keeps_business_domains_that_start_like_providers():
    assert clean_emails(["info@livemusicaustin.com", "hi@outlookdental.com"]) == [
        "info@livemusicaustin.com",
        "hi@outlookdental.com",
    ]


def test_clean_handles_none():
    assert clean_emails(None) == []


def test_clean_strips_query_string():
    assert clean_emails(["hello@acme.com?subject=hi"]) == ["hello@acme.com"]


def test_site_domain():
    assert site_domain("https://www.Acme.com/contact") == "acme.com"
    assert site_domain("acme.com") == "acme.com"
    assert site_domain(None) is None
    assert site_domain("") is None


def test_primary_prefers_role_address_on_own_domain():
    emails = ["john@acme.com", "sales@acme.com", "info@acme.com"]
    assert pick_primary(emails, "acme.com") == "info@acme.com"


def test_primary_falls_back_to_first_own_domain():
    assert pick_primary(["x@agency.com", "john@acme.com"], "acme.com") == "john@acme.com"


def test_primary_subdomain_website_matches_root_email():
    assert pick_primary(["office@acme.com"], "shop.acme.com") == "office@acme.com"


def test_primary_falls_back_to_first_any():
    assert pick_primary(["x@agency.com", "b@other.com"], "acme.com") == "x@agency.com"


def test_primary_empty():
    assert pick_primary([], "acme.com") is None
