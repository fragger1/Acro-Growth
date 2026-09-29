"""Proxy selection and health tracking.

gosom's proxy pool always starts at the first proxy in the list it is given, and
we start one gosom process per search, so handing it the full list means every
search uses the same first few proxies. Instead each search gets a small random
sample of healthy proxies, and proxies that gosom reports as failing are benched
for BENCH_HOURS; after MAX_STRIKES failures a proxy is retired until replaced.
"""

import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

BENCH_HOURS = 24
MAX_STRIKES = 3
UPSTREAM_FAILURE_RE = re.compile(r"Failed to connect to upstream: dial tcp (\d{1,3}(?:\.\d{1,3}){3}:\d+)")


def proxy_key(proxy_url: str) -> str:
    """host:port identity for a proxy URL (never includes credentials)."""
    parts = urlsplit(proxy_url)
    return f"{parts.hostname}:{parts.port}"


def failed_hosts(stderr: str, known: set[str]) -> set[str]:
    """host:port of proxies that gosom reported it could not connect to."""
    return {m for m in UPSTREAM_FAILURE_RE.findall(stderr or "") if m in known}


class ProxyHealth:
    """Strikes and bench times per proxy, persisted to a small JSON file."""

    def __init__(self, path: Path):
        self.path = path
        self.state: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")

    def _available(self, key: str, now: datetime) -> bool:
        entry = self.state.get(key)
        if not entry:
            return True
        if entry.get("strikes", 0) >= MAX_STRIKES:
            return False
        until = entry.get("benched_until")
        return not until or datetime.fromisoformat(until) <= now

    def pick(self, proxies: list[str], k: int, *, now: datetime | None = None,
             rng: random.Random | None = None) -> list[str]:
        """Up to k random healthy proxies (fewer if not enough are healthy)."""
        now = now or datetime.now(timezone.utc)
        rng = rng or random.Random()
        healthy = [p for p in proxies if self._available(proxy_key(p), now)]
        return rng.sample(healthy, min(k, len(healthy)))

    def record_failures(self, keys: set[str], *, now: datetime | None = None) -> None:
        if not keys:
            return
        now = now or datetime.now(timezone.utc)
        for key in keys:
            entry = self.state.setdefault(key, {"strikes": 0})
            entry["strikes"] = entry.get("strikes", 0) + 1
            entry["benched_until"] = (now + timedelta(hours=BENCH_HOURS)).isoformat()
        self._save()

    def benched(self, *, now: datetime | None = None) -> list[str]:
        """Proxies temporarily sidelined (not retired)."""
        now = now or datetime.now(timezone.utc)
        return sorted(k for k, e in self.state.items()
                      if e.get("strikes", 0) < MAX_STRIKES and not self._available(k, now))

    def retired(self) -> list[str]:
        return sorted(k for k, e in self.state.items() if e.get("strikes", 0) >= MAX_STRIKES)
