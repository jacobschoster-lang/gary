"""Monte Carlo / risk-of-ruin pure functions for the trading bot.

Given the realized profit-and-loss of a set of closed trades from a backtest,
these bootstrap-resample the trade sequence many times to estimate the
*distribution* of outcomes instead of a single point estimate. That lets us
report a probability of reaching a goal and a risk of ruin rather than one
number.

Resampling with replacement assumes trade order is independent -- a standard,
documented simplification: it ignores autocorrelation and regime changes, so
treat the results as a spread of plausible outcomes, not a forecast.

Everything here is pure: no I/O, no network, standard library only (``random``
with an explicit seed for determinism -- no numpy). Inputs are handled
defensively: empty or degenerate inputs return zeros/empty rather than raising
or dividing by zero, so callers can feed partial data without guarding every
call.
"""

from __future__ import annotations

import random
import statistics


def simulate_paths(
    trade_pnls: list[float],
    starting_equity: float,
    n_paths: int = 2000,
    path_len: int | None = None,
    seed: int = 0,
) -> list[list[float]]:
    """Bootstrap many equity paths.

    Each path resamples ``path_len`` trades (default: ``len(trade_pnls)``) WITH
    replacement from ``trade_pnls``, applying them cumulatively starting from
    ``starting_equity``. Returns a list of paths; each path is the list of
    running-equity values AFTER each trade (length == path_len). Uses
    ``random.Random(seed)`` for determinism. Returns ``[]`` if trade_pnls is
    empty or path_len resolves to 0 or n_paths <= 0.
    """
    if not trade_pnls or n_paths <= 0:
        return []
    steps = len(trade_pnls) if path_len is None else path_len
    if steps <= 0:
        return []

    rng = random.Random(seed)
    paths: list[list[float]] = []
    for _ in range(n_paths):
        equity = starting_equity
        path: list[float] = []
        for pnl in rng.choices(trade_pnls, k=steps):
            equity += pnl
            path.append(equity)
        paths.append(path)
    return paths


def final_equities(paths: list[list[float]], starting_equity: float) -> list[float]:
    """The last equity of each path (or starting_equity for an empty path)."""
    return [path[-1] if path else starting_equity for path in paths]


def probability_reach_goal(paths: list[list[float]], goal_equity: float) -> float:
    """Percent (0..100) of paths whose FINAL equity >= goal_equity. 0.0 if no paths."""
    if not paths:
        return 0.0
    hits = sum(1 for path in paths if path and path[-1] >= goal_equity)
    return hits / len(paths) * 100.0


def risk_of_ruin(paths: list[list[float]], ruin_equity: float) -> float:
    """Percent (0..100) of paths whose running equity EVER touches/falls below
    ruin_equity at any point along the path. 0.0 if no paths."""
    if not paths:
        return 0.0
    ruined = sum(1 for path in paths if any(value <= ruin_equity for value in path))
    return ruined / len(paths) * 100.0


def percentile(values: list[float], p: float) -> float:
    """The p-th percentile (p in 0..100) of values using linear interpolation
    between closest ranks on the sorted list. 0.0 if empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    frac = max(0.0, min(100.0, p)) / 100.0
    rank = frac * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def summarize(
    trade_pnls: list[float],
    starting_equity: float,
    goal_equity: float,
    ruin_equity: float | None = None,
    n_paths: int = 2000,
    path_len: int | None = None,
    seed: int = 0,
) -> dict:
    """Run the simulation and return a rounded summary dict.

    Keys: ``paths`` (number of paths actually simulated), ``trades_per_path``,
    ``prob_reach_goal_pct``, ``risk_of_ruin_pct`` (``ruin_equity`` defaults to
    ``0.5 * starting_equity`` when None), ``median_final_equity`` (p50),
    ``p5_final_equity``, ``p95_final_equity``, ``median_return_pct``,
    ``mean_return_pct``. All floats rounded to 2 decimals. If ``trade_pnls`` is
    empty, returns the dict with ``paths=0`` and all metrics 0.0 (equities equal
    to ``starting_equity`` where sensible).
    """
    ruin = 0.5 * starting_equity if ruin_equity is None else ruin_equity
    paths = simulate_paths(trade_pnls, starting_equity, n_paths, path_len, seed)

    if not paths:
        return {
            "paths": 0,
            "trades_per_path": 0,
            "prob_reach_goal_pct": 0.0,
            "risk_of_ruin_pct": 0.0,
            "median_final_equity": round(starting_equity, 2),
            "p5_final_equity": round(starting_equity, 2),
            "p95_final_equity": round(starting_equity, 2),
            "median_return_pct": 0.0,
            "mean_return_pct": 0.0,
        }

    finals = final_equities(paths, starting_equity)
    median_final = percentile(finals, 50.0)
    mean_final = statistics.fmean(finals)
    median_return = (median_final / starting_equity - 1.0) * 100.0 if starting_equity else 0.0
    mean_return = (mean_final / starting_equity - 1.0) * 100.0 if starting_equity else 0.0

    return {
        "paths": len(paths),
        "trades_per_path": len(paths[0]),
        "prob_reach_goal_pct": round(probability_reach_goal(paths, goal_equity), 2),
        "risk_of_ruin_pct": round(risk_of_ruin(paths, ruin), 2),
        "median_final_equity": round(median_final, 2),
        "p5_final_equity": round(percentile(finals, 5.0), 2),
        "p95_final_equity": round(percentile(finals, 95.0), 2),
        "median_return_pct": round(median_return, 2),
        "mean_return_pct": round(mean_return, 2),
    }
