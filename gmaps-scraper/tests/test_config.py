import pytest

from gmaps.config import parse_proxy_line


def test_webshare_format_becomes_http_url():
    assert parse_proxy_line("1.2.3.4:6754:user:pass\n") == "http://user:pass@1.2.3.4:6754"


def test_host_port_only():
    assert parse_proxy_line("1.2.3.4:8080") == "http://1.2.3.4:8080"


def test_full_url_passes_through():
    assert parse_proxy_line("socks5://u:p@host:1080") == "socks5://u:p@host:1080"


@pytest.mark.parametrize("line", ["", "   ", "# comment"])
def test_blank_and_comment_lines_skipped(line):
    assert parse_proxy_line(line) is None


def test_bad_line_error_does_not_leak_password():
    with pytest.raises(ValueError) as exc:
        parse_proxy_line("1.2.3.4:1:user")
    assert "user" not in str(exc.value)
