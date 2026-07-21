"""Walk-forward strategy optimizer.

The naive approach — pick the config that scored best on a window and report that
same number — overfits badly. This module instead splits history into a **train**
window (used to choose parameters) and a later **test** window (used only to
report honest, out-of-sample results). It also benchmarks against buy-and-hold so
you can see whether the bot actually adds value after costs.

Candidates are ranked on the train window by a **risk-adjusted** objective
(annualized Sharpe), not raw equity, so the winner isn't just the most reckless
config. Prices are fetched once and reused across every candidate and window.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gary.trading import metrics
from gary.trading import prices as price_data
from gary.trading.engine import TradingBot
from gary.trading.models import BotConfig

WARMUP = TradingBot.WARMUP


def objective(report: dict[str, Any]) -> float:
    """Training objective: annualized Sharpe, tie-broken by total return."""
    m = report.get("metrics", {})
    return m.get("sharpe", 0.0) * 1000 + report.get("return_pct", 0.0)


def candidate_configs(base: BotConfig) -> list[BotConfig]:
    """A curated grid over exit style, sizing, add-ons, and entry sensitivity."""
    exit_modes = [
        {"trailing_stop_pct": 0.0, "take_profit_pct": 0.30},
        {"trailing_stop_pct": 0.0, "take_profit_pct": 0.50},
        {"trailing_stop_pct": 0.12, "take_profit_pct": 5.0},
        {"trailing_stop_pct": 0.20, "take_profit_pct": 5.0},
    ]
    sizes = [0.25, 0.40, 0.60]
    addons = [False, True]
    momentum_thresholds = [0.02, 0.04]

    grid: list[BotConfig] = []
    for em in exit_modes:
        for size in sizes:
            for addon in addons:
                for mt in momentum_thresholds:
                    grid.append(
                        replace(
                            base,
                            trailing_stop_pct=em["trailing_stop_pct"],
                            take_profit_pct=em["take_profit_pct"],
                            max_position_pct=size,
                            allow_add_ons=addon,
                            momentum_threshold=mt,
                        )
                    )
    return grid


def _eval(cfg: BotConfig, series: dict[str, list[float]], bars: list[int], use_live: bool) -> dict:
    bot = TradingBot(config=cfg, use_live=use_live)
    curve, prices = bot._run(series, bars)
    return bot.report(curve, prices, days=len(curve))


def _buy_and_hold(cfg: BotConfig, series: dict[str, list[float]], bars: list[int]) -> dict:
    """Equal-weight buy-and-hold of the universe over the test window."""
    if not bars:
        return metrics.summarize([], [])
    syms = [s for s in cfg.universe if series.get(s)]
    if not syms:
        return metrics.summarize([], [])
    alloc = cfg.starting_cash / len(syms)
    shares = {s: alloc / series[s][bars[0]] for s in syms if series[s][bars[0]] > 0}
    equity = [cfg.starting_cash]
    for b in bars:
        equity.append(round(sum(shares.get(s, 0.0) * series[s][b] for s in syms), 2))
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
        "fees_paid": report.get("fees_paid", 0.0),
        "params": {
            "exit": (
                f"trailing {cfg.trailing_stop_pct * 100:.0f}%"
                if cfg.trailing_stop_pct > 0
                else f"take-profit {cfg.take_profit_pct * 100:.0f}%"
            ),
            "trailing_stop_pct": cfg.trailing_stop_pct,
            "take_profit_pct": cfg.take_profit_pct,
            "max_position_pct": cfg.max_position_pct,
            "allow_add_ons": cfg.allow_add_ons,
            "momentum_threshold": cfg.momentum_threshold,
        },
    }


def optimize(
    base: BotConfig | None = None,
    days: int | None = None,
    train_days: int | None = None,
    use_live: bool = True,
    top_n: int = 5,
) -> dict[str, Any]:
    """Walk-forward search: tune on a train window, report on a later test window.

    ``days`` is the out-of-sample (test) horizon; ``train_days`` defaults to 2x
    that. Returns in-sample vs. out-of-sample summaries, a buy-and-hold
    benchmark, an overfit gap, and a leaderboard showing train-vs-test per config.
    """
    base = base or BotConfig()
    test_days = days or base.horizon_days
    train_days = train_days or test_days * 2

    span = WARMUP + train_days + test_days + 2
    series = {s: price_data.price_series(s, span, use_live=use_live) for s in base.universe}
    length = min((len(v) for v in series.values()), default=0)
    last = length - 1

    # Test = the most recent `test_days` executable bars; train precedes it.
    test_first = max(WARMUP + 1, last - test_days + 1)
    test_bars = list(range(test_first, last + 1))
    train_last = test_first - 1
    train_first = max(WARMUP, train_last - train_days + 1)
    train_bars = list(range(train_first, train_last + 1))

    # Fall back to a plain in-sample run if history is too short to split.
    if len(train_bars) < 5 or len(test_bars) < 3:
        report = TradingBot(config=base, use_live=use_live).simulate(test_days, series=series)
        return {
            "days": test_days,
            "degenerate": True,
            "note": "history too short for a walk-forward split; ran in-sample",
            "best_config": base.to_dict(),
            "best_report": report,
            "live_data": use_live,
        }

    ranked: list[tuple[float, BotConfig, dict, dict]] = []
    for cand in candidate_configs(base):
        train_report = _eval(cand, series, train_bars, use_live)
        test_report = _eval(cand, series, test_bars, use_live)
        ranked.append((objective(train_report), cand, train_report, test_report))
    ranked.sort(key=lambda r: r[0], reverse=True)

    _, best_cfg, best_train, best_test = ranked[0]
    baseline_test = _eval(base, series, test_bars, use_live)
    benchmark = _buy_and_hold(base, series, test_bars)

    in_ret = best_train.get("return_pct", 0.0)
    oos_ret = best_test.get("return_pct", 0.0)
    return {
        "days": test_days,
        "train_days": len(train_bars),
        "test_days": len(test_bars),
        "tried": len(ranked),
        "objective": "sharpe (train), reported out-of-sample",
        "in_sample": _summary(best_cfg, best_train),
        "out_of_sample": _summary(best_cfg, best_test),
        "baseline_out_of_sample": _summary(base, baseline_test),
        "benchmark": {
            "name": "buy & hold (equal weight)",
            "return_pct": benchmark.get("total_return_pct", 0.0),
            "max_drawdown_pct": benchmark.get("max_drawdown_pct", 0.0),
            "sharpe": benchmark.get("sharpe", 0.0),
        },
        "overfit_gap_pct": round(in_ret - oos_ret, 2),
        "beats_benchmark": oos_ret > benchmark.get("total_return_pct", 0.0),
        "best_config": best_cfg.to_dict(),
        "best_report": best_test,
        "leaderboard": [
            {
                "train_return_pct": tr.get("return_pct", 0.0),
                "test_return_pct": te.get("return_pct", 0.0),
                "train_sharpe": tr.get("metrics", {}).get("sharpe", 0.0),
                **_summary(cfg, te),
            }
            for _, cfg, tr, te in ranked[:top_n]
        ],
        "live_data": use_live,
    }
