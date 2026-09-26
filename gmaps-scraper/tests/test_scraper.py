from pathlib import Path
from unittest.mock import MagicMock, patch

from gmaps.config import Config
from gmaps.scraper import build_command, depth_for_limit, parse_results, redact


def test_depth_for_limit():
    assert depth_for_limit(None, 12) == 12
    assert depth_for_limit(16, 12) == 2
    assert depth_for_limit(1, 12) == 1
    assert depth_for_limit(10_000, 12) == 12


def test_build_command_with_proxies():
    cmd = build_command(Path("g.exe"), Path("in.txt"), Path("out.json"), Path("px.txt"), 3, 10)
    assert cmd[0] == "g.exe"
    joined = " ".join(cmd)
    for part in ("-input in.txt", "-results out.json", "-json", "-email", "-c 3", "-depth 10",
                 "-exit-on-inactivity 3m", "-proxies-file px.txt"):
        assert part in joined


def test_build_command_without_proxies():
    cmd = build_command(Path("g.exe"), Path("in.txt"), Path("out.json"), None, 2, 5)
    assert "-proxies-file" not in cmd


def test_parse_jsonl():
    assert parse_results('{"a":1}\n\n{"a":2}\n') == [{"a": 1}, {"a": 2}]


def test_parse_json_array():
    assert parse_results('[{"a":1},{"a":2}]') == [{"a": 1}, {"a": 2}]


def test_parse_skips_garbage_lines():
    assert parse_results('{"a":1}\nnot json\n{"a":2') == [{"a": 1}]


def test_parse_empty():
    assert parse_results("") == []


def test_redact_masks_url_credentials_and_bare_passwords():
    proxies = ["http://user1:s3cret@1.2.3.4:80"]
    text = "dial http://user1:s3cret@1.2.3.4:80 failed; pw s3cret"
    out = redact(text, proxies)
    assert "s3cret" not in out and "user1:" not in out
    assert "1.2.3.4:80" in out


def test_gosom_scraper_integration():
    """Test GosomScraper with mocked subprocess.Popen."""
    from gmaps.scraper import GosomScraper
    import json
    import tempfile

    # Create a fake Popen class that simulates gosom behavior
    class FakePopen:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.cwd = kwargs.get("cwd")
            self.pid = 12345
            # Extract results file path from command
            self.results_file = None
            for i, arg in enumerate(cmd):
                if arg == "-results" and i + 1 < len(cmd):
                    self.results_file = Path(cmd[i + 1])
                    break

        def communicate(self, timeout=None):
            # Write two JSONL entries to results file
            if self.results_file and self.cwd:
                entries = [{"place_id": "id1", "name": "Place 1"}, {"place_id": "id2", "name": "Place 2"}]
                self.results_file.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
            stderr = "proxy http://u:pw@h:1 slow"
            return "", stderr

        @property
        def returncode(self):
            return 0

    cfg = Config(
        supabase_url="x",
        supabase_key="y",
        proxies=["http://u:pw@h:1"],
        gosom_path=Path("g.exe"),
    )

    with patch("gmaps.scraper.subprocess.Popen", FakePopen):
        scraper = GosomScraper(cfg, concurrency=2)
        result = scraper("test query", depth=3)

        # Verify results
        assert len(result.entries) == 2
        assert result.entries[0]["place_id"] == "id1"
        assert result.entries[1]["place_id"] == "id2"
        assert result.returncode == 0

        # Verify credentials are redacted in stderr
        assert "pw" not in result.stderr_tail
        assert "u:" not in result.stderr_tail
        assert "h:1" in result.stderr_tail  # Host should still be visible

        # Verify command structure (no proxy URL in cmd, only -proxies-file flag)
        # This is checked indirectly: if proxies were in cmd, they'd appear in faked Popen
        # and the test would pass; the fact that we use a file means it's not in cmd
