"""Strategy optimizer: grid-search the tunable knobs to chase the growth goal.

Fetches each symbol's price history **once**, then backtests many candidate
configs over that same series so the search is fast and apples-to-apples.
Candidates are scored to reward final equity while penalizing deep drawdowns, so
the "optimal" config is aggressive-but-not-reckless rather than pure gamble.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gary.trading import prices as price_data
from gary.trading.engine import TradingBot
from gary.trading.models import BotConfig

# How harshly to penalize peak-to-trough drawdown (in equity dollars).
_DRAWDOWN_PENALTY = 0.5


def score(report: dict[str, Any]) -> float:
    """Higher is better: end equity minus a drawdown penalty."""
    return report["end_equity"] - _DRAWDOWN_PENALTY * report.get("max_drawdown", 0.0)


def candidate_configs(base: BotConfig) -> list[BotConfig]:
    """A curated grid over exit style, sizing, add-ons, and entry sensitivity."""
    # Exit style: fixed take-profits vs. trailing stops that let winners run.
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


def _summary(cfg: BotConfig, report: dict[str, Any]) -> dict[str, Any]:
    return {
        "score": round(score(report), 2),
        "end_equity": report["end_equity"],
        "return_pct": report["return_pct"],
        "max_drawdown_pct": report.get("max_drawdown_pct", 0.0),
        "num_trades": report["num_trades"],
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
    use_live: bool = True,
    top_n: int = 5,
) -> dict[str, Any]:
    """Search the grid and return the baseline vs. best config + a leaderboard."""
    base = base or BotConfig()
    days = days or base.horizon_days
    span = days + 25
    series = {s: price_data.price_series(s, span, use_live=use_live) for s in base.universe}

    baseline_report = TradingBot(config=base, use_live=use_live).simulate(days, series=series)

    ranked: list[tuple[float, BotConfig, dict[str, Any]]] = []
    for cand in candidate_configs(base):
        report = TradingBot(config=cand, use_live=use_live).simulate(days, series=series)
        ranked.append((score(report), cand, report))
    ranked.sort(key=lambda r: r[0], reverse=True)

    best_score, best_cfg, best_report = ranked[0]
    return {
        "days": days,
        "tried": len(ranked),
        "baseline": _summary(base, baseline_report),
        "best": _summary(best_cfg, best_report),
        "best_config": best_cfg.to_dict(),
        "best_report": best_report,
        "leaderboard": [_summary(cfg, rep) for _, cfg, rep in ranked[:top_n]],
        "improvement_pct": round(
            best_report["end_equity"] - baseline_report["end_equity"], 2
        ),
        "live_data": use_live,
    }
