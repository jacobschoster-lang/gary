"""Trading strategies as pure functions over a price history.

Each strategy takes a list of historical closes (oldest -> newest) and returns a
``Signal``. Keeping them pure (no I/O, no state) makes them trivial to unit test
and to combine in the engine.

Implemented (per the user's brief):
    - momentum:      ride recent trend strength
    - price_history: SMA crossover (short vs long moving average)
    - mean_reversion: fade extremes via z-score of price vs its moving average
"""

from __future__ import annotations

from typing import Any

from gary.trading.models import Signal

STRATEGIES = ("momentum", "price_history", "mean_reversion")


def _sma(prices: list[float], window: int) -> float | None:
    if len(prices) < window or window <= 0:
        return None
    return sum(prices[-window:]) / window


def _hold(strategy: str, reason: str = "insufficient data") -> Signal:
    return Signal(action="hold", strength=0.0, reason=reason, strategy=strategy)


def momentum_signal(
    prices: list[float], lookback: int = 10, threshold: float = 0.03
) -> Signal:
    """Buy when the trailing ``lookback`` return exceeds +threshold; sell on -threshold."""
    strat = "momentum"
    if len(prices) <= lookback:
        return _hold(strat)
    past, now = prices[-1 - lookback], prices[-1]
    if past <= 0:
        return _hold(strat)
    change = (now - past) / past
    strength = min(1.0, abs(change) / (threshold * 4))
    if change >= threshold:
        return Signal("buy", round(strength, 3), f"+{change * 100:.1f}% over {lookback}d", strat)
    if change <= -threshold:
        return Signal("sell", round(strength, 3), f"{change * 100:.1f}% over {lookback}d", strat)
    return _hold(strat, f"{change * 100:+.1f}% within band")


def sma_crossover_signal(
    prices: list[float], short: int = 5, long: int = 20
) -> Signal:
    """Price-history trading: buy when short SMA is above long SMA, else sell."""
    strat = "price_history"
    short_now, long_now = _sma(prices, short), _sma(prices, long)
    short_prev, long_prev = _sma(prices[:-1], short), _sma(prices[:-1], long)
    if None in (short_now, long_now, short_prev, long_prev):
        return _hold(strat)
    gap = (short_now - long_now) / long_now if long_now else 0.0  # type: ignore[operator]
    strength = min(1.0, abs(gap) / 0.05)
    crossed_up = short_prev <= long_prev and short_now > long_now  # type: ignore[operator]
    crossed_down = short_prev >= long_prev and short_now < long_now  # type: ignore[operator]
    if crossed_up or short_now > long_now:  # type: ignore[operator]
        reason = "golden cross" if crossed_up else f"{short}d SMA above {long}d"
        conf = round(max(strength, 0.4) if crossed_up else strength, 3)
        return Signal("buy", conf, reason, strat)
    if crossed_down or short_now < long_now:  # type: ignore[operator]
        reason = "death cross" if crossed_down else f"{short}d SMA below {long}d"
        conf = round(max(strength, 0.4) if crossed_down else strength, 3)
        return Signal("sell", conf, reason, strat)
    return _hold(strat)


def mean_reversion_signal(
    prices: list[float], window: int = 20, z_threshold: float = 1.0
) -> Signal:
    """Fade extremes: buy when price is well below its mean, sell when well above."""
    strat = "mean_reversion"
    if len(prices) < window:
        return _hold(strat)
    window_prices = prices[-window:]
    mean = sum(window_prices) / window
    var = sum((p - mean) ** 2 for p in window_prices) / window
    std = var ** 0.5
    if std <= 0:
        return _hold(strat, "no volatility")
    z = (prices[-1] - mean) / std
    strength = min(1.0, abs(z) / (z_threshold * 2))
    if z <= -z_threshold:
        return Signal("buy", round(strength, 3), f"oversold z={z:.2f}", strat)
    if z >= z_threshold:
        return Signal("sell", round(strength, 3), f"overbought z={z:.2f}", strat)
    return _hold(strat, f"z={z:.2f} within band")


_DISPATCH = {
    "momentum": momentum_signal,
    "price_history": sma_crossover_signal,
    "mean_reversion": mean_reversion_signal,
}


def signal_for(name: str, prices: list[float]) -> Signal:
    fn = _DISPATCH.get(name)
    if fn is None:
        raise ValueError(f"unknown strategy: {name!r}")
    return fn(prices)


def signals_from_config(prices: list[float], cfg: Any) -> list[Signal]:
    """Run each enabled strategy with the tunable params from ``cfg``."""
    out: list[Signal] = []
    for name in cfg.strategies:
        if name == "momentum":
            out.append(momentum_signal(prices, cfg.momentum_lookback, cfg.momentum_threshold))
        elif name == "price_history":
            out.append(sma_crossover_signal(prices, cfg.sma_short, cfg.sma_long))
        elif name == "mean_reversion":
            out.append(mean_reversion_signal(prices, cfg.mr_window, cfg.mr_z))
        else:
            raise ValueError(f"unknown strategy: {name!r}")
    return out


def combine(
    signals: list[Signal], weights: dict[str, float] | None = None
) -> tuple[str, float, str]:
    """Blend multiple strategy signals into one net decision.

    Votes are weighted by each signal's strength and an optional per-strategy
    weight; the net direction wins. Returns (action, strength, reason).
    """
    def w(s: Signal) -> float:
        return s.strength * (weights.get(s.strategy, 1.0) if weights else 1.0)

    buy = sum(w(s) for s in signals if s.action == "buy")
    sell = sum(w(s) for s in signals if s.action == "sell")
    contributing = [s for s in signals if s.action != "hold"]
    if not contributing or abs(buy - sell) < 1e-9:
        return "hold", 0.0, "no consensus"
    if buy > sell:
        reasons = ", ".join(f"{s.strategy}: {s.reason}" for s in signals if s.action == "buy")
        return "buy", round(min(1.0, buy - sell), 3), reasons
    reasons = ", ".join(f"{s.strategy}: {s.reason}" for s in signals if s.action == "sell")
    return "sell", round(min(1.0, sell - buy), 3), reasons
