import random
from datetime import datetime, timedelta, timezone

from gmaps.proxies import MAX_STRIKES, ProxyHealth, failed_hosts, proxy_key

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
PROXIES = [f"http://u:p@10.0.0.{i}:80{i:02d}" for i in range(1, 21)]


def test_proxy_key_is_host_port_without_credentials():
    assert proxy_key("http://user:secret@1.2.3.4:6754") == "1.2.3.4:6754"


def test_failed_hosts_parses_upstream_errors_only_for_known_hosts():
    stderr = (
        "[AuthProxy] 2026/09/28 03:18:46 Failed to connect to upstream: dial tcp 10.0.0.3:8003: connectex: ...\n"
        "[AuthProxy] ... Failed to connect to upstream: dial tcp 10.0.0.3:8003: timeout\n"
        "[AuthProxy] ... Failed to connect to upstream: dial tcp 99.9.9.9:1: refused\n"
        "some other line mentioning 10.0.0.4:8004\n"
    )
    assert failed_hosts(stderr, {"10.0.0.3:8003", "10.0.0.4:8004"}) == {"10.0.0.3:8003"}


def test_pick_returns_k_distinct_random_proxies(tmp_path):
    health = ProxyHealth(tmp_path / "h.json")
    picked = health.pick(PROXIES, 5, now=NOW, rng=random.Random(1))
    assert len(picked) == 5 and len(set(picked)) == 5
    assert set(picked) <= set(PROXIES)
    other = health.pick(PROXIES, 5, now=NOW, rng=random.Random(2))
    assert picked != other  # different searches get different proxies


def test_pick_spreads_load_across_the_whole_list(tmp_path):
    health = ProxyHealth(tmp_path / "h.json")
    rng = random.Random(0)
    used = set()
    for _ in range(40):
        used.update(health.pick(PROXIES, 5, now=NOW, rng=rng))
    assert used == set(PROXIES)


def test_strike_benches_for_24h_then_returns(tmp_path):
    health = ProxyHealth(tmp_path / "h.json")
    bad = PROXIES[0]
    health.record_failures({proxy_key(bad)}, now=NOW)
    for seed in range(20):
        assert bad not in health.pick(PROXIES, 19, now=NOW + timedelta(hours=23), rng=random.Random(seed))
    later = health.pick(PROXIES, 20, now=NOW + timedelta(hours=25), rng=random.Random(0))
    assert bad in later


def test_three_strikes_retires_permanently(tmp_path):
    health = ProxyHealth(tmp_path / "h.json")
    bad = PROXIES[0]
    for i in range(MAX_STRIKES):
        health.record_failures({proxy_key(bad)}, now=NOW + timedelta(days=2 * i))
    far_future = NOW + timedelta(days=365)
    assert bad not in health.pick(PROXIES, 20, now=far_future, rng=random.Random(0))
    assert health.retired() == [proxy_key(bad)]


def test_state_persists_across_instances(tmp_path):
    path = tmp_path / "h.json"
    ProxyHealth(path).record_failures({proxy_key(PROXIES[1])}, now=NOW)
    reloaded = ProxyHealth(path)
    assert proxy_key(PROXIES[1]) in reloaded.benched(now=NOW)


def test_pick_returns_fewer_when_few_healthy_and_empty_when_none(tmp_path):
    health = ProxyHealth(tmp_path / "h.json")
    small = PROXIES[:3]
    health.record_failures({proxy_key(small[0])}, now=NOW)
    assert sorted(health.pick(small, 5, now=NOW, rng=random.Random(0))) == sorted(small[1:])
    health.record_failures({proxy_key(p) for p in small}, now=NOW)
    assert health.pick(small, 5, now=NOW, rng=random.Random(0)) == []


def test_corrupt_state_file_is_treated_as_empty(tmp_path):
    path = tmp_path / "h.json"
    path.write_text("{not json", encoding="utf-8")
    assert len(ProxyHealth(path).pick(PROXIES, 5, now=NOW, rng=random.Random(0))) == 5
