"""Price-based factor-signal functions for the cross-sectional research harness.

The harness ranks a universe of symbols each rebalance by a *factor score*
(higher = more attractive to hold long) and goes long the top names (and
optionally short the bottom). This module implements the classic price-based
factors as pure functions: each takes ONE symbol's close-price history as a
``list[float]`` (oldest -> newest) and returns a ``float`` score.

Everything here is pure: no I/O, no network, standard library only. Inputs are
handled defensively -- when there isn't enough history the factor returns
``0.0`` rather than raising or dividing by zero, so callers can feed partial
data without guarding every call. Only :func:`score` and :func:`min_history`
raise, and only on an unknown factor name.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable


def momentum(prices: list[float], lookback: int = 126, skip: int = 21) -> float:
    """12-1 style momentum: total return from t-(lookback+skip) to t-skip (skipping the
    most recent `skip` bars to avoid short-term reversal). 0.0 if insufficient history."""
    if lookback <= 0 or skip < 0:
        return 0.0
    need = lookback + skip + 1
    if len(prices) < need:
        return 0.0
    end = len(prices) - 1 - skip
    start = end - lookback
    base = prices[start]
    if base == 0:
        return 0.0
    return prices[end] / base - 1.0


def short_reversal(prices: list[float], window: int = 5) -> float:
    """Short-term reversal: NEGATIVE of the last `window`-bar return (buy recent losers).
    0.0 if insufficient history."""
    if window <= 0 or len(prices) < window + 1:
        return 0.0
    base = prices[-1 - window]
    if base == 0:
        return 0.0
    return -(prices[-1] / base - 1.0)


def low_volatility(prices: list[float], window: int = 63) -> float:
    """Low-volatility factor: negative of the stdev of the last `window` daily returns
    (so calmer stocks score higher). 0.0 if insufficient history."""
    if window <= 0 or len(prices) < window + 1:
        return 0.0
    recent = prices[-(window + 1):]
    rets: list[float] = []
    for prev, cur in zip(recent, recent[1:], strict=False):
        if prev == 0:
            rets.append(0.0)
        else:
            rets.append(cur / prev - 1.0)
    if len(rets) < 2:
        return 0.0
    return -statistics.pstdev(rets)


def trend(prices: list[float], window: int = 200) -> float:
    """Trend factor: price/SMA(window) - 1 (positive when above the moving average).
    0.0 if insufficient history."""
    if window <= 0 or len(prices) < window + 1:
        return 0.0
    sma = statistics.fmean(prices[-window:])
    if sma == 0:
        return 0.0
    return prices[-1] / sma - 1.0


FACTORS: dict[str, Callable[[list[float]], float]] = {
    "momentum": lambda prices: momentum(prices),
    "short_reversal": lambda prices: short_reversal(prices),
    "low_volatility": lambda prices: low_volatility(prices),
    "trend": lambda prices: trend(prices),
}


def score(name: str, prices: list[float]) -> float:
    """Dispatch to the named factor (using its default params). Raise ValueError on unknown name."""
    try:
        factor = FACTORS[name]
    except KeyError:
        raise ValueError(f"unknown factor: {name!r}") from None
    return factor(prices)


def min_history(name: str) -> int:
    """Minimum number of bars needed for the named factor to produce a non-trivial score
    (e.g. momentum -> lookback+skip+1, trend -> window+1, low_volatility -> window+1,
    short_reversal -> window+1)."""
    minimums: dict[str, int] = {
        "momentum": 126 + 21 + 1,
        "short_reversal": 5 + 1,
        "low_volatility": 63 + 1,
        "trend": 200 + 1,
    }
    try:
        return minimums[name]
    except KeyError:
        raise ValueError(f"unknown factor: {name!r}") from None
