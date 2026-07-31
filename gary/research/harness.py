"""Factor research harness.

Tests a battery of price-based factor configs across a universe, ranks them by
Sharpe, and — crucially — **haircuts the winner for multiple testing** (deflated
Sharpe over the number of configs tried) and checks stability across walk-forward
folds. A config only "survives" if it beats buy-and-hold with a positive deflated
Sharpe. Survivors are blended into one portfolio, and the resulting (honest,
possibly zero) return feeds a compounding projection toward the wealth targets.

If nothing survives, that's the real answer: no durable edge here — compound a
low-cost diversified hold instead.
"""

from __future__ import annotations

from typing import Any

from gary.research import projection
from gary.research.backtest import FactorConfig, buy_hold_return, run_factor
from gary.research.factors import FACTORS, min_history
from gary.trading import metrics, selection
from gary.trading import prices as price_data

# Equities only, so multi-year daily history is available uniformly for every name
# (crypto free-tier history is capped at ~1y, which would bottleneck the panel).
DEFAULT_UNIVERSE = [
    "NVDA", "TSLA", "AMD", "AAPL", "MSFT", "AMZN", "GOOGL", "META",
    "QCOM", "INTC", "CRM", "IONQ",
]
_TRADING_DAYS = 252
_MARKET_BASELINE = 0.08  # conservative long-run market return for the honest projection


def candidate_configs() -> list[FactorConfig]:
    grid: list[FactorConfig] = []
    for factor in FACTORS:
        for long_short in (False, True):
            grid.append(FactorConfig(factor=factor, long_short=long_short))
    return grid


def _fold_slices(rebar: list[int], folds: int) -> list[list[int]]:
    if len(rebar) < folds * 3:
        return [rebar]
    size = len(rebar) // folds
    return [rebar[i * size: (i + 1) * size + 1] for i in range(folds)]


def _cagr(equity_end: float, start: float, years: float) -> float:
    return ((equity_end / start) ** (1 / years) - 1) if years > 0 and start > 0 else 0.0


def research(
    universe: list[str] | None = None,
    years: int = 4,
    folds: int = 3,
    rebalance_days: int = 21,
    start_cash: float = 10_000.0,
    monthly_contribution: float = 2_000.0,
    targets: list[float] | None = None,
    use_live: bool = True,
) -> dict[str, Any]:
    universe = universe or DEFAULT_UNIVERSE
    targets = targets or [1_000_000.0, 18_000_000.0]
    warmup = max(min_history(f) for f in FACTORS)
    total_bars = warmup + years * _TRADING_DAYS
    panel = {s: price_data.price_series(s, total_bars, use_live=use_live) for s in universe}
    length = min((len(v) for v in panel.values()), default=0)
    rebar = list(range(warmup, length, rebalance_days))
    if len(rebar) < 4:
        return {"degenerate": True, "note": "not enough history for factor research",
                "universe": universe, "live_data": use_live}

    grid = candidate_configs()
    n_trials = len(grid)
    n_obs = len(rebar) - 1
    fold_slices = _fold_slices(rebar, folds)
    bench_pct = round(buy_hold_return(panel, rebar[0], rebar[-1]) * 100, 2)
    bench_years = (n_obs * rebalance_days) / _TRADING_DAYS
    bench_cagr = _cagr(1 + bench_pct / 100, 1.0, bench_years)

    results = []
    survivors = []
    for cfg in grid:
        full = run_factor(panel, cfg, rebar)
        fold_returns = [run_factor(panel, cfg, fs).get("return_pct", 0.0) for fs in fold_slices]
        deflated = selection.deflated_sharpe(full["sharpe"], n_trials, n_obs)
        beats = full["return_pct"] > bench_pct
        survivor = bool(deflated > 0 and beats)
        row = {
            "label": cfg.label(), "factor": cfg.factor, "long_short": cfg.long_short,
            "return_pct": full["return_pct"], "cagr_pct": full["cagr_pct"],
            "sharpe": full["sharpe"], "deflated_sharpe": round(deflated, 3),
            "max_drawdown_pct": full["max_drawdown_pct"],
            "folds_positive": sum(1 for r in fold_returns if r > 0), "folds": len(fold_slices),
            "beats_benchmark": beats, "survivor": survivor,
            "_period_returns": full["period_returns"],
        }
        results.append(row)
        if survivor:
            survivors.append(row)
    results.sort(key=lambda r: r["deflated_sharpe"], reverse=True)

    # Blend survivors into one equal-weight portfolio (per-period average).
    combined = None
    chosen_cagr = bench_cagr
    if survivors:
        m = min(len(s["_period_returns"]) for s in survivors)
        blended = [sum(s["_period_returns"][i] for s in survivors) / len(survivors)
                   for i in range(m)]
        equity = [start_cash]
        for r in blended:
            equity.append(round(equity[-1] * (1 + r), 2))
        ppy = round(_TRADING_DAYS / rebalance_days)
        stats = metrics.summarize(equity, [], periods_per_year=ppy)
        years_run = (m * rebalance_days) / _TRADING_DAYS
        c_cagr = _cagr(equity[-1], start_cash, years_run)
        combined = {"names": [s["label"] for s in survivors],
                    "return_pct": round((equity[-1] / start_cash - 1) * 100, 2),
                    "cagr_pct": round(c_cagr * 100, 2), "sharpe": stats["sharpe"],
                    "max_drawdown_pct": stats["max_drawdown_pct"]}
        chosen_cagr = c_cagr

    verdict = (
        f"{len(survivors)} of {n_trials} configs beat buy-and-hold with a positive "
        f"deflated Sharpe out-of-sample."
        if survivors else
        "No factor beat buy-and-hold after the multiple-testing haircut — no durable "
        "edge detected. Honest path: compound a low-cost, diversified, vol-targeted hold."
    )
    for r in results:  # drop internal series before returning
        r.pop("_period_returns", None)

    return {
        "universe": universe, "years": years, "rebalances": n_obs, "n_trials": n_trials,
        "benchmark": {"return_pct": bench_pct, "cagr_pct": round(bench_cagr * 100, 2)},
        "factors": results,
        "survivors": [s["label"] for s in survivors],
        "combined": combined,
        "verdict": verdict,
        "chosen_cagr_pct": round(chosen_cagr * 100, 2),
        "projection": {
            "start": start_cash, "monthly_contribution": monthly_contribution,
            "optimistic": projection.goal_summary(start_cash, monthly_contribution,
                                                   chosen_cagr, targets),
            "market_baseline": projection.goal_summary(start_cash, monthly_contribution,
                                                       _MARKET_BASELINE, targets),
        },
        "live_data": use_live,
    }
