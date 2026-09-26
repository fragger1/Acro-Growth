import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gmaps.config import ROOT, Config

RESULTS_PER_SCROLL = 8
TIMEOUT_SECONDS = 60 * 60


@dataclass
class ScrapeResult:
    entries: list[dict]
    returncode: int
    stderr_tail: str


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
        "-email",
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
    def __init__(self, cfg: Config, concurrency: int):
        self.cfg = cfg
        self.concurrency = concurrency

    def __call__(self, query: str, depth: int) -> ScrapeResult:
        (ROOT / "tmp").mkdir(exist_ok=True)
        work = Path(tempfile.mkdtemp(prefix="gosom_", dir=ROOT / "tmp"))
        try:
            input_file = work / "input.txt"
            results_file = work / "results.json"
            input_file.write_text(query + "\n", encoding="utf-8")
            proxies_file = None
            if self.cfg.proxies:
                proxies_file = work / "proxies.txt"
                proxies_file.write_text("\n".join(self.cfg.proxies) + "\n", encoding="utf-8")
            cmd = build_command(
                self.cfg.gosom_path, input_file, results_file, proxies_file, self.concurrency, depth
            )
            try:
                proc = subprocess.run(
                    cmd, cwd=work, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=TIMEOUT_SECONDS,
                )
                returncode, stderr = proc.returncode, proc.stderr or ""
            except subprocess.TimeoutExpired as exc:
                returncode = -1
                partial = exc.stderr if isinstance(exc.stderr, str) else ""
                stderr = f"timeout after {TIMEOUT_SECONDS}s\n{partial}"
            text = results_file.read_text(encoding="utf-8", errors="replace") if results_file.exists() else ""
            return ScrapeResult(parse_results(text), returncode, stderr[-2000:])
        finally:
            shutil.rmtree(work, ignore_errors=True)
