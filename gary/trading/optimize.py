"""Rolling, purged walk-forward optimizer with robust parameter selection.

Improvements over a naive grid search:
  - **Rolling walk-forward**: several (train, test) folds slide through history.
  - **Purge/embargo**: a gap between train and test windows so overlapping
    indicator lookbacks don't leak future information into the test.
  - **Robust selection on train only**: the config is chosen by how good AND how
    *stable* it is across the train folds (``selection.robustness_score``) — never
    using the test data — then reported out-of-sample. This avoids picking a
    config that just got lucky on one window.
  - **Deflated Sharpe**: the winner's Sharpe is haircut for multiple-testing bias
    (we tried many configs).
  - Buy-and-hold benchmark + Monte Carlo of the out-of-sample trades.

Prices are fetched once and reused across every candidate, window, and fold.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gary.trading import metrics, montecarlo, selection
from gary.trading import prices as price_data
from gary.trading.engine import TradingBot
from gary.trading.models import BotConfig


def candidate_configs(base: BotConfig) -> list[BotConfig]:
    """Grid over selection mode (incl. long/short), exit, sizing, and turnover."""
    grid: list[BotConfig] = []
    for sel in ("per_symbol", "cross_sectional", "long_short", "buy_hold"):
        for exit_mode in ({"trailing_stop_pct": 0.0, "take_profit_pct": 0.30},
                          {"trailing_stop_pct": 0.15, "take_profit_pct": 5.0}):
            for size in (0.25, 0.50):
                for reb in (1, 5):
                    grid.append(
                        replace(
                            base,
                            selection_mode=sel,
                            trailing_stop_pct=exit_mode["trailing_stop_pct"],
                            take_profit_pct=exit_mode["take_profit_pct"],
                            max_position_pct=size,
                            rebalance_every=reb,
                            vol_target=0.20,
                        )
                    )
    return grid


def _run_cfg(cfg, series, bars, use_live):
    bot = TradingBot(config=cfg, use_live=use_live)
    curve, prices = bot._run(series, bars)
    report = bot.report(curve, prices, days=len(curve))
    realized = [f.realized_pnl for f in bot.broker.fills if f.side in ("sell", "cover")]
    return report, realized


def _buy_and_hold(cfg, series, bars):
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


def _params(cfg: BotConfig) -> dict[str, Any]:
    return {
        "selection": cfg.selection_mode,
        "exit": (
            f"trailing {cfg.trailing_stop_pct * 100:.0f}%"
            if cfg.trailing_stop_pct > 0
            else f"take-profit {cfg.take_profit_pct * 100:.0f}%"
        ),
        "max_position_pct": cfg.max_position_pct,
        "rebalance_every": cfg.rebalance_every,
        "regime_ma": cfg.regime_ma,
        "vol_target": cfg.vol_target,
    }


def _mean(xs: list[float]) -> float:
    return round(sum(xs) / len(xs), 2) if xs else 0.0


def _fold_windows(last, warmup, train_days, test_days, embargo, folds):
    windows = []
    for i in range(folds):
        test_end = last - (folds - 1 - i) * test_days
        test_first = max(warmup + 1, test_end - test_days + 1)
        train_last = test_first - 1 - embargo  # purge gap
        train_first = max(warmup, train_last - train_days + 1)
        train_bars = list(range(train_first, train_last + 1))
        test_bars = list(range(test_first, test_end + 1))
        if len(train_bars) >= 5 and len(test_bars) >= 3:
            windows.append((train_bars, test_bars))
    return windows


def optimize(
    base: BotConfig | None = None,
    days: int | None = None,
    train_days: int | None = None,
    folds: int = 3,
    embargo: int = 3,
    use_live: bool = True,
    top_n: int = 5,
) -> dict[str, Any]:
    base = base or BotConfig()
    test_days = days or base.horizon_days
    train_days = train_days or test_days * 2
    warmup = TradingBot(base).warmup()

    span = warmup + train_days + folds * test_days + embargo + 2
    series = {s: price_data.price_series(s, span, use_live=use_live) for s in base.universe}
    length = min((len(v) for v in series.values()), default=0)
    windows = _fold_windows(length - 1, warmup, train_days, test_days, embargo, folds)

    if not windows:
        report, _ = _run_cfg(base, series, list(range(max(warmup, length - 1 - test_days),
                                                       length)), use_live)
        return {"days": test_days, "degenerate": True,
                "note": "history too short for purged walk-forward; ran in-sample",
                "best_config": base.to_dict(), "best_report": report, "live_data": use_live}

    grid = candidate_configs(base)
    cands: list[dict[str, Any]] = []
    for cfg in grid:
        train_returns, train_sharpes, test_returns, test_sharpes, test_dds = [], [], [], [], []
        test_pnls: list[float] = []
        for train_bars, test_bars in windows:
            tr, _ = _run_cfg(cfg, series, train_bars, use_live)
            te, te_pnls = _run_cfg(cfg, series, test_bars, use_live)
            train_returns.append(tr.get("return_pct", 0.0))
            train_sharpes.append(tr.get("metrics", {}).get("sharpe", 0.0))
            test_returns.append(te.get("return_pct", 0.0))
            test_sharpes.append(te.get("metrics", {}).get("sharpe", 0.0))
            test_dds.append(te.get("metrics", {}).get("max_drawdown_pct", 0.0))
            test_pnls += te_pnls
        cands.append({
            "cfg": cfg, "train_returns": train_returns, "train_sharpes": train_sharpes,
            "test_returns": test_returns, "test_sharpes": test_sharpes, "test_dds": test_dds,
            "test_pnls": test_pnls,
        })

    # Choose on TRAIN robustness only (no test leakage).
    ranked = selection.rank_by_robustness(cands, returns_key="train_returns")
    chosen = ranked[0]
    chosen_cfg: BotConfig = chosen["cfg"]

    n_obs = sum(len(tb) for tb, _ in windows)
    observed_sharpe = _mean(chosen["train_sharpes"])
    deflated = selection.deflated_sharpe(observed_sharpe, len(grid), n_obs)

    all_test_bars = [b for _, tb in windows for b in tb]
    benchmark = _buy_and_hold(base, series, all_test_bars)
    bench_ret = benchmark.get("total_return_pct", 0.0)
    mc = montecarlo.summarize(chosen["test_pnls"], base.starting_cash, base.goal_equity(),
                              n_paths=2000, seed=7)

    oos_list = chosen["test_returns"]
    mean_oos = _mean(oos_list)
    fold_rows = [
        {"fold": i + 1, "train_return_pct": chosen["train_returns"][i],
         "oos_return_pct": chosen["test_returns"][i], "oos_sharpe": chosen["test_sharpes"][i],
         "oos_max_drawdown_pct": chosen["test_dds"][i], "params": _params(chosen_cfg)}
        for i in range(len(windows))
    ]
    return {
        "days": test_days,
        "folds": len(windows),
        "embargo": embargo,
        "train_days": train_days,
        "test_days": test_days,
        "tried": len(grid),
        "objective": "train robustness (mean − stdev), reported out-of-sample",
        "selection": {
            "robustness": round(chosen.get("robustness", 0.0), 2),
            "observed_sharpe": observed_sharpe,
            "deflated_sharpe": round(deflated, 3),
            "n_trials": len(grid),
        },
        "in_sample": {"return_pct": _mean(chosen["train_returns"]), "params": _params(chosen_cfg)},
        "out_of_sample": {
            "return_pct": mean_oos,
            "max_drawdown_pct": _mean(chosen["test_dds"]),
            "sharpe": _mean(chosen["test_sharpes"]),
            "params": _params(chosen_cfg),
        },
        "aggregate": {
            "mean_oos_return_pct": mean_oos,
            "median_oos_return_pct": sorted(oos_list)[len(oos_list) // 2],
            "folds_positive": sum(1 for r in oos_list if r > 0),
            "folds_beating_benchmark": sum(1 for r in oos_list if r > bench_ret),
        },
        "folds_detail": fold_rows,
        "benchmark": {
            "name": "buy & hold (equal weight)",
            "return_pct": bench_ret,
            "max_drawdown_pct": benchmark.get("max_drawdown_pct", 0.0),
            "sharpe": benchmark.get("sharpe", 0.0),
        },
        "monte_carlo": mc,
        "overfit_gap_pct": round(_mean(chosen["train_returns"]) - mean_oos, 2),
        "beats_benchmark": mean_oos > bench_ret,
        "best_config": chosen_cfg.to_dict(),
        "leaderboard": [
            {
                "train_return_pct": _mean(c["train_returns"]),
                "test_return_pct": _mean(c["test_returns"]),
                "robustness": round(c.get("robustness", 0.0), 2),
                "sharpe": _mean(c["test_sharpes"]),
                "params": _params(c["cfg"]),
            }
            for c in ranked[:top_n]
        ],
        "live_data": use_live,
    }
