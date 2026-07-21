"""Rolling walk-forward strategy optimizer.

Picking the best config on one window and reporting that same number overfits.
This module instead uses **rolling walk-forward**: it slides several
(train, test) folds through history, tunes parameters on each *train* window and
scores them only on the following *out-of-sample* test window, then aggregates
the OOS results into an honest distribution. It also:

  - benchmarks against equal-weight buy-and-hold over the tested period,
  - runs a Monte Carlo bootstrap of the out-of-sample trades to estimate the
    probability of hitting the goal and the risk of ruin,
  - ranks candidates on a risk-adjusted objective (annualized Sharpe), not raw
    equity, so the winner isn't just the most reckless config.

Prices are fetched once and reused across every candidate, window, and fold.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gary.trading import metrics, montecarlo
from gary.trading import prices as price_data
from gary.trading.engine import TradingBot
from gary.trading.models import BotConfig


def objective(report: dict[str, Any]) -> float:
    """Training objective: annualized Sharpe, tie-broken by total return."""
    m = report.get("metrics", {})
    return m.get("sharpe", 0.0) * 1000 + report.get("return_pct", 0.0)


def candidate_configs(base: BotConfig) -> list[BotConfig]:
    """Grid over the robust levers: exit style, sizing, selection mode, regime
    filter, and volatility targeting."""
    exit_modes = [
        {"trailing_stop_pct": 0.0, "take_profit_pct": 0.30},
        {"trailing_stop_pct": 0.15, "take_profit_pct": 5.0},
    ]
    sizes = [0.25, 0.50]
    selections = ["per_symbol", "cross_sectional"]
    regimes = [0, 100]
    vol_targets = [0.0, 0.20]

    grid: list[BotConfig] = []
    for em in exit_modes:
        for size in sizes:
            for sel in selections:
                for reg in regimes:
                    for vt in vol_targets:
                        grid.append(
                            replace(
                                base,
                                trailing_stop_pct=em["trailing_stop_pct"],
                                take_profit_pct=em["take_profit_pct"],
                                max_position_pct=size,
                                selection_mode=sel,
                                regime_ma=reg,
                                vol_target=vt,
                            )
                        )
    return grid


def _run_cfg(
    cfg: BotConfig, series: dict[str, list[float]], bars: list[int], use_live: bool
) -> tuple[dict[str, Any], list[float]]:
    bot = TradingBot(config=cfg, use_live=use_live)
    curve, prices = bot._run(series, bars)
    report = bot.report(curve, prices, days=len(curve))
    realized = [f.realized_pnl for f in bot.broker.fills if f.side == "sell"]
    return report, realized


def _buy_and_hold(cfg: BotConfig, series: dict[str, list[float]], bars: list[int]) -> dict:
    if not bars:
        return metrics.summarize([], [])
    syms = [s for s in cfg.universe if series.get(s) and series[s][bars[0]] > 0]
    if not syms:
        return metrics.summarize([], [])
    alloc = cfg.starting_cash / len(syms)
    shares = {s: alloc / series[s][bars[0]] for s in syms}
    equity = [cfg.starting_cash]
    for b in bars:
        equity.append(round(sum(shares[s] * series[s][b] for s in syms), 2))
    return metrics.summarize(equity, [])


def _summary(cfg: BotConfig, report: dict[str, Any]) -> dict[str, Any]:
    m = report.get("metrics", {})
    return {
        "return_pct": report.get("return_pct", 0.0),
        "max_drawdown_pct": m.get("max_drawdown_pct", 0.0),
        "sharpe": m.get("sharpe", 0.0),
        "calmar": m.get("calmar", 0.0),
        "win_rate": m.get("win_rate", 0.0),
        "profit_factor": m.get("profit_factor", 0.0),
        "num_trades": report.get("num_trades", 0),
        "params": _params(cfg),
    }


def _params(cfg: BotConfig) -> dict[str, Any]:
    return {
        "exit": (
            f"trailing {cfg.trailing_stop_pct * 100:.0f}%"
            if cfg.trailing_stop_pct > 0
            else f"take-profit {cfg.take_profit_pct * 100:.0f}%"
        ),
        "selection": cfg.selection_mode,
        "regime_ma": cfg.regime_ma,
        "vol_target": cfg.vol_target,
        "max_position_pct": cfg.max_position_pct,
    }


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def optimize(
    base: BotConfig | None = None,
    days: int | None = None,
    train_days: int | None = None,
    folds: int = 3,
    use_live: bool = True,
    top_n: int = 5,
) -> dict[str, Any]:
    """Rolling walk-forward search over ``folds`` (train, test) windows."""
    base = base or BotConfig()
    test_days = days or base.horizon_days
    train_days = train_days or test_days * 2
    warmup = TradingBot(base).warmup()

    span = warmup + train_days + folds * test_days + 2
    series = {s: price_data.price_series(s, span, use_live=use_live) for s in base.universe}
    length = min((len(v) for v in series.values()), default=0)
    last = length - 1

    grid = candidate_configs(base)
    fold_rows: list[dict[str, Any]] = []
    all_oos_bars: list[int] = []
    stitched_pnls: list[float] = []
    applied_cfg = base
    last_fold_ranked: list[tuple[float, BotConfig, dict, dict]] = []

    for i in range(folds):
        test_end = last - (folds - 1 - i) * test_days
        test_first = max(warmup + 1, test_end - test_days + 1)
        test_bars = list(range(test_first, test_end + 1))
        train_last = test_first - 1
        train_first = max(warmup, train_last - train_days + 1)
        train_bars = list(range(train_first, train_last + 1))
        if len(train_bars) < 5 or len(test_bars) < 3:
            continue

        ranked: list[tuple[float, BotConfig, dict, dict]] = []
        for cand in grid:
            train_report, _ = _run_cfg(cand, series, train_bars, use_live)
            test_report, test_pnls = _run_cfg(cand, series, test_bars, use_live)
            ranked.append((objective(train_report), cand, train_report, test_report))
        ranked.sort(key=lambda r: r[0], reverse=True)
        _, best_cfg, best_train, best_test = ranked[0]
        _, best_pnls = _run_cfg(best_cfg, series, test_bars, use_live)

        applied_cfg = best_cfg
        last_fold_ranked = ranked
        all_oos_bars += test_bars
        stitched_pnls += best_pnls
        fold_rows.append({
            "fold": i + 1,
            "train_return_pct": best_train.get("return_pct", 0.0),
            "oos_return_pct": best_test.get("return_pct", 0.0),
            "oos_sharpe": best_test.get("metrics", {}).get("sharpe", 0.0),
            "oos_max_drawdown_pct": best_test.get("metrics", {}).get("max_drawdown_pct", 0.0),
            "params": _params(best_cfg),
        })

    if not fold_rows:
        report, _ = _run_cfg(base, series, list(range(max(warmup, last - test_days + 1), last + 1)),
                             use_live)
        return {"days": test_days, "degenerate": True,
                "note": "history too short for walk-forward; ran in-sample",
                "best_config": base.to_dict(), "best_report": report, "live_data": use_live}

    oos_returns = [f["oos_return_pct"] for f in fold_rows]
    train_returns = [f["train_return_pct"] for f in fold_rows]
    benchmark = _buy_and_hold(base, series, all_oos_bars)
    bench_ret = benchmark.get("total_return_pct", 0.0)

    mc = montecarlo.summarize(
        stitched_pnls, base.starting_cash, base.goal_equity(), n_paths=2000, seed=7
    )
    mean_oos = _mean(oos_returns)
    return {
        "days": test_days,
        "folds": len(fold_rows),
        "train_days": train_days,
        "test_days": test_days,
        "tried": len(grid),
        "objective": "sharpe (train), rolling out-of-sample",
        "in_sample": {"return_pct": _mean(train_returns), "params": _params(applied_cfg)},
        "out_of_sample": {
            "return_pct": mean_oos,
            "max_drawdown_pct": _mean([f["oos_max_drawdown_pct"] for f in fold_rows]),
            "sharpe": _mean([f["oos_sharpe"] for f in fold_rows]),
            "params": _params(applied_cfg),
        },
        "aggregate": {
            "mean_oos_return_pct": mean_oos,
            "median_oos_return_pct": sorted(oos_returns)[len(oos_returns) // 2],
            "folds_positive": sum(1 for r in oos_returns if r > 0),
            "folds_beating_benchmark": sum(1 for r in oos_returns if r > bench_ret),
        },
        "folds_detail": fold_rows,
        "benchmark": {
            "name": "buy & hold (equal weight)",
            "return_pct": bench_ret,
            "max_drawdown_pct": benchmark.get("max_drawdown_pct", 0.0),
            "sharpe": benchmark.get("sharpe", 0.0),
        },
        "monte_carlo": mc,
        "overfit_gap_pct": round(_mean(train_returns) - mean_oos, 2),
        "beats_benchmark": mean_oos > bench_ret,
        "best_config": applied_cfg.to_dict(),
        "leaderboard": [
            {
                "train_return_pct": tr.get("return_pct", 0.0),
                "test_return_pct": te.get("return_pct", 0.0),
                "sharpe": te.get("metrics", {}).get("sharpe", 0.0),
                **_summary(cfg, te),
            }
            for _, cfg, tr, te in last_fold_ranked[:top_n]
        ],
        "live_data": use_live,
    }
