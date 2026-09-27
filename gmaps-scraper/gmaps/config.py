import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    supabase_url: str
    supabase_key: str
    proxies: list[str]
    gosom_path: Path


def parse_proxy_line(line: str) -> str | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = line.split(":")
    if len(parts) == 2:
        host, port = parts
        return f"http://{host}:{port}"
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{user}:{password}@{host}:{port}"
    raise ValueError(f"Unrecognized proxy line for host {parts[0]!r}")


def _load_proxies(path: str | None) -> list[str]:
    if not path:
        return []
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [p for p in (parse_proxy_line(line) for line in lines) if p]


def load_config() -> Config:
    load_dotenv(ROOT / ".env")
    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SECRET_KEY", "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in gmaps-scraper/.env")
    gosom = os.environ.get("GOSOM_PATH", "").strip()
    return Config(
        supabase_url=url,
        supabase_key=key,
        proxies=_load_proxies(os.environ.get("PROXIES_FILE", "").strip() or None),
        gosom_path=Path(gosom) if gosom else ROOT / "bin" / "google-maps-scraper.exe",
    )
