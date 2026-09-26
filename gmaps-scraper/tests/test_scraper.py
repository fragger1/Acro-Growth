from pathlib import Path

from gmaps.scraper import build_command, depth_for_limit, parse_results


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
