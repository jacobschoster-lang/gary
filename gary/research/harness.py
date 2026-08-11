"""Factor research harness (Phase 2: honest edge test).

Improvements over Phase 1:
  - **Broad, diversified universe** across sectors (less hand-picked than a
    tech-winner list — though still current-listing survivorship, noted below).
  - **Multi-regime history** (default ~7 years, spanning bull + bear).
  - **Locked out-of-sample holdout**: configs are selected ONLY on the earlier
    research window (walk-forward + deflated Sharpe + fold stability); the final
    holdout window is never used for selection and is reported as the honest test.
  - **Regime-conditional reporting**: survivor performance split by bull/bear
    (equal-weight index vs its 200-day MA) on the holdout.
  - More factor families (momentum, short/long reversal, low-vol, downside-vol, trend).

Residual bias to keep in mind: the universe is today's listed large caps (no
delisted names), so real survivorship bias remains. A truly clean test needs
point-in-time index membership — not available from the free data here.
"""

from __future__ import annotations

from typing import Any

from gary.research import projection
from gary.research.backtest import FactorConfig, buy_hold_return, run_factor
from gary.research.factors import FACTORS, min_history
from gary.trading import metrics, selection
from gary.trading import prices as price_data

# Diversified across sectors (tech, financials, healthcare, staples, energy,
# industrials, utilities) to reduce the tech-winner selection bias of Phase 1.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AMD", "INTC", "CRM", "ORCL", "CSCO",
    "JPM", "BAC", "WFC", "GS", "V", "MA",
    "JNJ", "PFE", "UNH", "MRK", "ABBV",
    "WMT", "PG", "KO", "HD", "XOM", "CVX", "CAT", "BA", "NEE", "DIS",
]
_TRADING_DAYS = 252
_MARKET_BASELINE = 0.08
_REGIME_MA = 200


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


def _equal_weight_index(panel: dict[str, list[float]], length: int) -> list[float]:
    """Equal-weight index of the universe (mean of each name's price/first-price)."""
    idx = []
    for t in range(length):
        vals = [ser[t] / ser[0] for ser in panel.values() if ser[0] > 0 and t < len(ser)]
        idx.append(sum(vals) / len(vals) if vals else 1.0)
    return idx


def _regime_split(index: list[float], rebar: list[int], period_returns: list[float]) -> dict:
    """Compound the survivor returns separately in bull vs bear periods (index vs its MA)."""
    bull, bear, nb, nr = 1.0, 1.0, 0, 0
    for k in range(len(period_returns)):
        e = rebar[k]
        if e >= _REGIME_MA:
            sma = sum(index[e - _REGIME_MA + 1: e + 1]) / _REGIME_MA
            is_bull = index[e] >= sma
        else:
            is_bull = True
        if is_bull:
            bull *= 1 + period_returns[k]
            nb += 1
        else:
            bear *= 1 + period_returns[k]
            nr += 1
    return {
        "bull_return_pct": round((bull - 1) * 100, 2),
        "bear_return_pct": round((bear - 1) * 100, 2),
        "bull_periods": nb, "bear_periods": nr,
    }


def _combine(panel, survivors, rebar, start_cash, rebalance_days):
    """Blend survivor configs into one equal-weight portfolio over ``rebar``."""
    per = [run_factor(panel, s, rebar) for s in survivors]
    m = min((len(p["period_returns"]) for p in per), default=0)
    if m == 0:
        return None, [], 0.0
    blended = [sum(p["period_returns"][i] for p in per) / len(per) for i in range(m)]
    equity = [start_cash]
    for r in blended:
        equity.append(round(equity[-1] * (1 + r), 2))
    ppy = round(_TRADING_DAYS / rebalance_days)
    stats = metrics.summarize(equity, [], periods_per_year=ppy)
    years_run = (m * rebalance_days) / _TRADING_DAYS
    cagr = _cagr(equity[-1], start_cash, years_run)
    combined = {"return_pct": round((equity[-1] / start_cash - 1) * 100, 2),
                "cagr_pct": round(cagr * 100, 2), "sharpe": stats["sharpe"],
                "max_drawdown_pct": stats["max_drawdown_pct"]}
    return combined, blended, cagr


def research(
    universe: list[str] | None = None,
    years: int = 7,
    folds: int = 3,
    rebalance_days: int = 21,
    holdout_frac: float = 0.35,
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
    if len(rebar) < 8:
        return {"degenerate": True, "note": "not enough history for the holdout split",
                "universe": universe, "live_data": use_live}

    # Lock the tail as an out-of-sample holdout; select only on the research window.
    split = int(len(rebar) * (1 - holdout_frac))
    research_rebar = rebar[: split + 1]
    holdout_rebar = rebar[split:]
    index = _equal_weight_index(panel, length)

    grid = candidate_configs()
    n_trials = len(grid)
    n_obs = len(research_rebar) - 1
    fold_slices = _fold_slices(research_rebar, folds)
    research_bench = round(buy_hold_return(panel, research_rebar[0], research_rebar[-1]) * 100, 2)

    rows, survivor_cfgs = [], []
    for cfg in grid:
        full = run_factor(panel, cfg, research_rebar)
        fold_rets = [run_factor(panel, cfg, fs).get("return_pct", 0.0) for fs in fold_slices]
        deflated = selection.deflated_sharpe(full["sharpe"], n_trials, n_obs)
        folds_pos = sum(1 for r in fold_rets if r > 0)
        beats = full["return_pct"] > research_bench
        survivor = bool(deflated > 0 and beats and folds_pos >= max(2, len(fold_slices) - 1))
        rows.append({
            "label": cfg.label(), "factor": cfg.factor, "long_short": cfg.long_short,
            "return_pct": full["return_pct"], "cagr_pct": full["cagr_pct"],
            "sharpe": full["sharpe"], "deflated_sharpe": round(deflated, 3),
            "max_drawdown_pct": full["max_drawdown_pct"],
            "folds_positive": folds_pos, "folds": len(fold_slices),
            "beats_benchmark": beats, "survivor": survivor,
        })
        if survivor:
            survivor_cfgs.append(cfg)
    rows.sort(key=lambda r: r["deflated_sharpe"], reverse=True)

    # HONEST TEST: evaluate the research-selected survivors on the untouched holdout.
    holdout_bench = round(buy_hold_return(panel, holdout_rebar[0], holdout_rebar[-1]) * 100, 2)
    holdout_years = ((len(holdout_rebar) - 1) * rebalance_days) / _TRADING_DAYS
    combined = regime = None
    chosen_cagr = _cagr(1 + holdout_bench / 100, 1.0, holdout_years)  # default: market
    if survivor_cfgs:
        combined, blended, c_cagr = _combine(panel, survivor_cfgs, holdout_rebar,
                                             start_cash, rebalance_days)
        if combined:
            regime = _regime_split(index, holdout_rebar, blended)
            chosen_cagr = c_cagr

    beats_holdout = bool(combined and combined["return_pct"] > holdout_bench)
    n_surv = len(survivor_cfgs)
    ho_ret = combined["return_pct"] if combined else 0.0
    if not survivor_cfgs:
        verdict = ("No factor survived selection (deflated Sharpe + beats buy-and-hold + "
                   "fold stability) on the research window. No edge — compound a low-cost hold.")
    elif beats_holdout:
        verdict = (f"{n_surv} survivor(s) selected on research BEAT buy-and-hold on the untouched "
                   f"holdout ({ho_ret:+.1f}% vs {holdout_bench:+.1f}%). Promising, but validate on "
                   "more universes/regimes before trusting it.")
    else:
        verdict = (f"{n_surv} survivor(s) looked good in-sample but did NOT beat buy-and-hold on "
                   f"the holdout ({ho_ret:+.1f}% vs {holdout_bench:+.1f}%) — the edge didn't "
                   "generalize.")

    return {
        "universe": universe, "years": years, "rebalances": len(rebar) - 1, "n_trials": n_trials,
        "research_benchmark_pct": research_bench,
        "factors": rows,
        "survivors": [c.label() for c in survivor_cfgs],
        "holdout": {
            "rebalances": len(holdout_rebar) - 1,
            "benchmark_return_pct": holdout_bench,
            "combined": combined,
            "beats_benchmark": beats_holdout,
            "regime": regime,
        },
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
