"""Tests for the cached, adjusted price dataset layer."""

from gary.research.dataset import PriceCache, load_panel


def test_offline_panel_is_deterministic_and_synthetic():
    p1, cov1 = load_panel(["AAPL", "MSFT"], 300, use_live=False)
    p2, _ = load_panel(["AAPL", "MSFT"], 300, use_live=False)
    assert p1["AAPL"] == p2["AAPL"]  # deterministic
    assert cov1["live"] is False
    assert cov1["sources"]["synthetic"] == 2
    assert all(len(v) >= 60 for v in p1.values())


def test_price_cache_roundtrip_and_staleness(tmp_path):
    cache = PriceCache(directory=tmp_path)
    assert cache.load("AAPL") is None  # empty
    cache.save("AAPL", [1.0, 2.0, 3.0])
    assert cache.load("AAPL") == [1.0, 2.0, 3.0]
    # A zero max-age is always stale, but stale() still returns it.
    assert cache.load("AAPL", max_age_days=0) is None
    assert cache.stale("AAPL") == [1.0, 2.0, 3.0]


def test_load_panel_uses_cache_then_fetcher_then_synthetic(tmp_path):
    cache = PriceCache(directory=tmp_path)
    cache.save("CACHED", [100.0 + i for i in range(120)])
    calls = []

    def fake_fetcher(sym, days):
        calls.append(sym)
        return [50.0 + i for i in range(150)] if sym == "LIVE" else None

    panel, cov = load_panel(
        ["CACHED", "LIVE", "FAILS"], 100, use_live=True, cache=cache,
        fetcher=fake_fetcher, throttle=0.0,
    )
    # CACHED served from cache (fetcher not called for it).
    assert "CACHED" not in calls
    assert cov["symbols"]["CACHED"]["source"] == "cache"
    # LIVE fetched and cached.
    assert cov["symbols"]["LIVE"]["source"] == "live"
    assert cache.load("LIVE") is not None
    # FAILS falls back to the deterministic synthetic series.
    assert cov["symbols"]["FAILS"]["source"] == "synthetic"
    assert len(panel["FAILS"]) >= 60


def test_load_panel_retries_then_falls_back(tmp_path):
    cache = PriceCache(directory=tmp_path)
    attempts = []

    def flaky(sym, days):
        attempts.append(sym)
        return None  # always fails -> exhausts retries -> synthetic

    panel, cov = load_panel(["X"], 100, use_live=True, cache=cache,
                            fetcher=flaky, throttle=0.0, retries=2)
    assert len(attempts) == 3  # initial + 2 retries
    assert cov["symbols"]["X"]["source"] == "synthetic"
