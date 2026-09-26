import re
from urllib.parse import urlparse

EMAIL_RE = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$")
FILE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".js", ".css", ".pdf")
BLOCKED_DOMAINS = {
    "example.com", "example.org", "domain.com", "email.com", "yourdomain.com", "yoursite.com",
    "mysite.com", "company.com", "test.com", "sentry.io", "wixpress.com", "wix.com",
    "squarespace.com", "godaddy.com", "cloudflare.com", "sentry-next.wixpress.com",
}
BLOCKED_LOCAL_PARTS = {
    "example", "yourname", "your.name", "name", "email", "youremail", "your.email",
    "user", "username", "test", "johndoe", "john.doe",
}
PREFERRED_LOCAL_PARTS = ("info", "contact", "office", "hello", "admin")

# Personal inboxes are never wanted for cold email. Generic business inboxes are fine.
PERSONAL_BRANDS = {
    "gmail", "googlemail", "yahoo", "ymail", "rocketmail", "hotmail", "outlook", "live", "msn",
    "aol", "icloud", "gmx", "yandex", "protonmail",
}
PERSONAL_DOMAINS = {
    "me.com", "mac.com", "proton.me", "pm.me", "mail.com", "comcast.net", "att.net",
    "sbcglobal.net", "verizon.net", "bellsouth.net", "cox.net", "charter.net", "earthlink.net",
    "optonline.net", "frontier.com", "windstream.net", "rogers.com", "shaw.ca", "sympatico.ca",
    "btinternet.com", "sky.com", "qq.com", "163.com",
}
PERSONAL_SUFFIXES = {
    "com", "net", "org", "co.uk", "ca", "fr", "de", "it", "es", "ie", "nl", "be", "ch", "at",
    "se", "dk", "no", "fi", "pl", "pt", "gr", "ru", "in", "co.in", "jp", "co.jp", "com.au",
    "com.br", "com.mx", "com.ar", "co.nz", "co.za",
}


def _is_personal(domain: str) -> bool:
    if domain in PERSONAL_DOMAINS:
        return True
    brand, _, suffix = domain.partition(".")
    # brand + known personal provider suffix: yahoo.com, yahoo.co.uk, live.fr (not live.info, livemusicaustin.com)
    return brand in PERSONAL_BRANDS and suffix in PERSONAL_SUFFIXES


def _domain_blocked(domain: str) -> bool:
    return _is_personal(domain) or any(domain == d or domain.endswith("." + d) for d in BLOCKED_DOMAINS)


def clean_emails(raw: list[str] | None) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        email = (item or "").strip().lower().removeprefix("mailto:").split("?")[0]
        if email.endswith(FILE_EXTENSIONS) or not EMAIL_RE.match(email):
            continue
        local, domain = email.rsplit("@", 1)
        if _domain_blocked(domain) or local in BLOCKED_LOCAL_PARTS:
            continue
        if email not in out:
            out.append(email)
    return out


def site_domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website if "://" in website else "http://" + website).hostname or ""
    host = host.lower().removeprefix("www.")
    return host or None


def _on_domain(email: str, domain: str | None) -> bool:
    if not domain:
        return False
    email_domain = email.rsplit("@", 1)[1]
    return (
        email_domain == domain
        or email_domain.endswith("." + domain)
        or domain.endswith("." + email_domain)
    )


def pick_primary(emails: list[str], domain: str | None) -> str | None:
    if not emails:
        return None
    own = [e for e in emails if _on_domain(e, domain)]
    for preferred in PREFERRED_LOCAL_PARTS:
        for email in own:
            if email.split("@", 1)[0] == preferred:
                return email
    return own[0] if own else emails[0]
