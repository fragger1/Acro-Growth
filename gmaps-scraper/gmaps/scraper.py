import json
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from gmaps.config import ROOT, Config
from gmaps.proxies import ProxyHealth, failed_hosts, proxy_key

PROXIES_PER_SEARCH = 5
RESULTS_PER_SCROLL = 8
TIMEOUT_SECONDS = 60 * 60
CREDENTIALS_RE = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")


def redact(text: str, proxies: list[str]) -> str:
    """Redact proxy credentials from text to prevent password leaks in logs."""
    text = CREDENTIALS_RE.sub(r"\1***:***@", text)
    for proxy in proxies:
        creds = urlsplit(proxy)
        if creds.password:
            text = text.replace(creds.password, "***")
    return text


@dataclass
class ScrapeResult:
    entries: list[dict]
    returncode: int
    stderr_tail: str


def sweep_tmp(root: Path) -> None:
    """Delete leftover gosom_* work directories from a previous crashed/killed
    run (they can contain a proxies.txt, which is never read or logged here)."""
    tmp_dir = root / "tmp"
    if not tmp_dir.exists():
        return
    for entry in tmp_dir.iterdir():
        if entry.is_dir() and entry.name.startswith("gosom_"):
            shutil.rmtree(entry, ignore_errors=True)


def depth_for_limit(limit: int | None, default_depth: int) -> int:
    if limit is None:
        return default_depth
    return max(1, min(default_depth, math.ceil(limit / RESULTS_PER_SCROLL)))


def build_command(
    gosom: Path, input_file: Path, results_file: Path, proxies_file: Path | None, concurrency: int, depth: int
) -> list[str]:
    cmd = [
        str(gosom),
        "-input", str(input_file),
        "-results", str(results_file),
        "-json",
        "-c", str(concurrency),
        "-depth", str(depth),
        "-exit-on-inactivity", "3m",
    ]
    if proxies_file is not None:
        cmd += ["-proxies-file", str(proxies_file)]
    return cmd


def parse_results(text: str) -> list[dict]:
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            return [e for e in json.loads(text) if isinstance(e, dict)]
        except json.JSONDecodeError:
            pass
    entries = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            entries.append(obj)
    return entries


class GosomScraper:
    def __init__(self, cfg: Config, concurrency: int, *, health: ProxyHealth | None = None,
                 proxies_per_search: int = PROXIES_PER_SEARCH, rng: random.Random | None = None):
        self.cfg = cfg
        self.concurrency = concurrency
        self.health = health
        self.proxies_per_search = proxies_per_search
        self.rng = rng or random.Random()

    def _choose_proxies(self) -> list[str]:
        if self.health is not None:
            return self.health.pick(self.cfg.proxies, self.proxies_per_search, rng=self.rng)
        return self.rng.sample(self.cfg.proxies, min(self.proxies_per_search, len(self.cfg.proxies)))

    def __call__(self, query: str, depth: int) -> ScrapeResult:
        chosen = self._choose_proxies() if self.cfg.proxies else []
        if self.cfg.proxies and not chosen:
            return ScrapeResult([], -1, "no healthy proxies available (all benched or retired)")
        (ROOT / "tmp").mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="gosom_", dir=ROOT / "tmp"))
        try:
            input_file = work / "input.txt"
            results_file = work / "results.json"
            input_file.write_text(query + "\n", encoding="utf-8")
            proxies_file = None
            if chosen:
                proxies_file = work / "proxies.txt"
                proxies_file.write_text("\n".join(chosen) + "\n", encoding="utf-8")
            cmd = build_command(
                self.cfg.gosom_path, input_file, results_file, proxies_file, self.concurrency, depth
            )
            try:
                proc = subprocess.Popen(
                    cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace",
                )
                try:
                    _, stderr = proc.communicate(timeout=TIMEOUT_SECONDS)
                    returncode = proc.returncode
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                    else:
                        proc.kill()
                    _, stderr = proc.communicate()
                    returncode = -1
                    stderr = f"timeout after {TIMEOUT_SECONDS}s\n{stderr}"
            except Exception as e:
                returncode = -1
                stderr = str(e)

            if self.health is not None and chosen:
                self.health.record_failures(failed_hosts(stderr, {proxy_key(p) for p in chosen}))
            stderr = redact(stderr, self.cfg.proxies)
            text = results_file.read_text(encoding="utf-8", errors="replace") if results_file.exists() else ""
            return ScrapeResult(parse_results(text), returncode, stderr[-2000:])
        finally:
            shutil.rmtree(work, ignore_errors=True)
