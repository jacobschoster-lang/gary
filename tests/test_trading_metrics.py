from __future__ import annotations

import math

from gary.trading.metrics import (
    cagr,
    calmar,
    max_drawdown_pct,
    returns,
    sharpe,
    sortino,
    summarize,
    total_return_pct,
    trade_stats,
    turnover,
)


def test_returns_basic_and_empty():
    assert returns([]) == []
    assert returns([100.0]) == []
    r = returns([100.0, 110.0, 99.0])
    assert len(r) == 2
    assert math.isclose(r[0], 0.1)
    assert math.isclose(r[1], -0.1)


def test_returns_handles_zero_prev():
    assert returns([0.0, 100.0]) == [0.0]


def test_total_return_pct():
    assert math.isclose(total_return_pct([100.0, 110.0]), 10.0)
    assert total_return_pct([]) == 0.0
    assert total_return_pct([100.0]) == 0.0
    assert total_return_pct([0.0, 110.0]) == 0.0


def test_cagr():
    # One full year of daily bars doubling -> 100% CAGR.
    equity = [100.0] + [200.0] * 252
    # elapsed = (len-1)/252 = 1 year, ratio 2 -> cagr == 1.0
    assert math.isclose(cagr(equity), 1.0, rel_tol=1e-9)
    assert cagr([]) == 0.0
    assert cagr([100.0]) == 0.0
    assert cagr([0.0, 200.0]) == 0.0


def test_max_drawdown_pct():
    assert math.isclose(max_drawdown_pct([100.0, 120.0, 90.0, 100.0]), 25.0)
    assert max_drawdown_pct([100.0, 110.0, 120.0]) == 0.0
    assert max_drawdown_pct([]) == 0.0


def test_sharpe_increasing_positive_flat_zero():
    increasing = [100.0, 101.0, 102.5, 104.0, 106.0]
    assert sharpe(increasing) > 0
    assert sharpe([100.0, 100.0, 100.0]) == 0.0
    assert sharpe([100.0]) == 0.0


def test_sortino_no_downside_is_zero_and_downside_positive():
    increasing = [100.0, 101.0, 102.5, 104.0, 106.0]
    # No negative excess returns -> downside deviation undefined -> 0.0.
    assert sortino(increasing) == 0.0
    mixed = [100.0, 110.0, 105.0, 120.0, 115.0, 130.0]
    assert sortino(mixed) != 0.0
    assert sortino([100.0]) == 0.0


def test_calmar_positive_with_drawdown_zero_without():
    # Up curve that dips then recovers higher -> positive cagr and a drawdown.
    equity = [100.0, 130.0, 110.0, 150.0]
    assert calmar(equity) > 0
    # No drawdown at all -> 0.0.
    assert calmar([100.0, 110.0, 120.0]) == 0.0
    assert calmar([]) == 0.0


def test_trade_stats():
    fills = [
        {"side": "sell", "realized_pnl": 100},
        {"side": "sell", "realized_pnl": -50},
        {"side": "buy", "notional": 500},
    ]
    stats = trade_stats(fills)
    assert stats["closed_trades"] == 2
    assert stats["wins"] == 1
    assert stats["losses"] == 1
    assert math.isclose(stats["win_rate"], 50.0)
    assert math.isclose(stats["avg_win"], 100.0)
    assert math.isclose(stats["avg_loss"], -50.0)
    assert math.isclose(stats["profit_factor"], 2.0)


def test_trade_stats_empty_and_no_losses():
    empty = trade_stats([])
    assert empty["closed_trades"] == 0
    assert empty["win_rate"] == 0.0
    assert empty["profit_factor"] == 0.0

    only_wins = trade_stats([
        {"side": "sell", "realized_pnl": 30},
        {"side": "sell", "realized_pnl": 70},
    ])
    assert only_wins["losses"] == 0
    # No losses -> profit_factor falls back to sum of wins.
    assert math.isclose(only_wins["profit_factor"], 100.0)


def test_turnover():
    fills = [
        {"side": "buy", "notional": 500},
        {"side": "sell", "notional": 300},
    ]
    equity = [100.0, 300.0]  # mean 200
    assert math.isclose(turnover(fills, equity), 800.0 / 200.0)
    assert turnover(fills, []) == 0.0


def test_summarize_keys_and_rounding():
    equity = [100.0, 130.0, 110.0, 150.0]
    fills = [
        {"side": "sell", "realized_pnl": 100},
        {"side": "sell", "realized_pnl": -50},
        {"side": "buy", "notional": 500},
    ]
    out = summarize(equity, fills)
    expected_keys = {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "sharpe",
        "sortino",
        "calmar",
        "turnover",
        "closed_trades",
        "wins",
        "losses",
        "win_rate",
        "avg_win",
        "avg_loss",
        "profit_factor",
    }
    assert set(out.keys()) == expected_keys
    # sharpe/sortino/calmar rounded to 3 decimals, others to 2.
    assert out["sharpe"] == round(out["sharpe"], 3)
    assert out["total_return_pct"] == round(out["total_return_pct"], 2)
    assert out["closed_trades"] == 2
    assert math.isclose(out["win_rate"], 50.0)
