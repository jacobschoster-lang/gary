from __future__ import annotations

import pytest

from gary.research import factors


def test_momentum_uptrend_positive():
    prices = [100.0 * (1.01**i) for i in range(200)]
    assert factors.momentum(prices) > 0.0


def test_momentum_downtrend_negative():
    prices = [100.0 * (0.99**i) for i in range(200)]
    assert factors.momentum(prices) < 0.0


def test_momentum_short_history_zero():
    prices = [100.0 + i for i in range(50)]
    assert factors.momentum(prices) == 0.0


def test_momentum_skips_recent_bars():
    # Steady rise then a sharp recent drop within the skip window: the 12-1
    # momentum should ignore the drop and stay positive.
    prices = [100.0 * (1.01**i) for i in range(160)]
    prices += [prices[-1] * 0.5] * 10  # crash inside the skip=21 window
    assert factors.momentum(prices) > 0.0


def test_short_reversal_recent_drop_positive():
    prices = [100.0] * 20 + [90.0]
    assert factors.short_reversal(prices) > 0.0


def test_short_reversal_recent_rally_negative():
    prices = [100.0] * 20 + [110.0]
    assert factors.short_reversal(prices) < 0.0


def test_short_reversal_short_history_zero():
    assert factors.short_reversal([100.0, 101.0]) == 0.0


def test_low_volatility_calm_scores_higher_than_jumpy():
    # Same mean drift (0 net), different volatility.
    calm = [100.0]
    for i in range(80):
        calm.append(calm[-1] * (1.001 if i % 2 == 0 else 1.0 / 1.001))
    jumpy = [100.0]
    for i in range(80):
        jumpy.append(jumpy[-1] * (1.05 if i % 2 == 0 else 1.0 / 1.05))
    calm_score = factors.low_volatility(calm)
    jumpy_score = factors.low_volatility(jumpy)
    assert calm_score > jumpy_score
    assert calm_score <= 0.0
    assert jumpy_score <= 0.0


def test_low_volatility_short_history_zero():
    assert factors.low_volatility([100.0, 101.0, 102.0]) == 0.0


def test_trend_above_sma_positive():
    prices = [100.0 + i for i in range(250)]  # steadily rising -> last price above SMA
    assert factors.trend(prices) > 0.0


def test_trend_below_sma_negative():
    prices = [100.0 - i * 0.1 for i in range(250)]  # steadily falling -> last below SMA
    assert factors.trend(prices) < 0.0


def test_trend_short_history_zero():
    prices = [100.0 + i for i in range(50)]
    assert factors.trend(prices) == 0.0


def test_score_dispatches_to_named_factor():
    prices = [100.0 * (1.01**i) for i in range(250)]
    for name in factors.FACTORS:
        assert factors.score(name, prices) == factors.FACTORS[name](prices)


def test_score_unknown_name_raises():
    with pytest.raises(ValueError):
        factors.score("nope", [100.0, 101.0])


def test_factors_registry_has_exactly_four_keys():
    assert set(factors.FACTORS) == {"momentum", "short_reversal", "low_volatility", "trend"}


def test_min_history_returns_sane_positive_ints():
    for name in factors.FACTORS:
        value = factors.min_history(name)
        assert isinstance(value, int)
        assert value > 0
    assert factors.min_history("momentum") == 126 + 21 + 1
    assert factors.min_history("short_reversal") == 5 + 1
    assert factors.min_history("low_volatility") == 63 + 1
    assert factors.min_history("trend") == 200 + 1


def test_min_history_unknown_name_raises():
    with pytest.raises(ValueError):
        factors.min_history("nope")
