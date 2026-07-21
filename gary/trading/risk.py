"""Risk-management rules for the trading bot.

These encode the user's brief and keep the money-management logic separate from
signal generation so it can be tuned and tested in isolation:

    - take profit at +30%
    - stop loss at a configurable drawdown
    - size positions as a fraction of equity (never over-allocate)
    - move 50% of realized profit into a lower-risk reserve
"""

from __future__ import annotations


def should_take_profit(return_pct: float, take_profit_pct: float) -> bool:
    return return_pct >= take_profit_pct


def should_stop_loss(return_pct: float, stop_loss_pct: float) -> bool:
    return return_pct <= -abs(stop_loss_pct)


def target_position_notional(
    equity: float,
    cash: float,
    max_position_pct: float,
    existing_value: float,
    strength: float,
) -> float:
    """Dollars to deploy into a name, capped by per-position and cash limits.

    Scales with signal ``strength`` (0..1) but never lets a single position
    exceed ``max_position_pct`` of equity, and never spends more than free cash.
    """
    if equity <= 0 or cash <= 0:
        return 0.0
    cap = equity * max_position_pct
    room = max(0.0, cap - existing_value)
    desired = cap * max(0.0, min(1.0, strength))
    return round(max(0.0, min(desired, room, cash)), 2)


def volatility(prices: list[float], window: int = 20) -> float:
    """Per-bar return volatility (population stdev) over the last ``window`` bars.

    0.0 when there isn't enough history so callers can fall back to fixed sizing.
    """
    if len(prices) <= 1 or window <= 1:
        return 0.0
    recent = prices[-(window + 1):]
    rets = []
    for prev, cur in zip(recent, recent[1:], strict=False):
        if prev > 0:
            rets.append(cur / prev - 1.0)
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    return var ** 0.5


def position_notional(
    equity: float,
    cash: float,
    cap_fraction: float,
    existing_value: float,
    *,
    strength: float = 1.0,
    asset_vol: float = 0.0,
    vol_target: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Dollars to deploy into a name.

    When ``vol_target`` > 0 and an ``asset_vol`` estimate is available, size
    inversely to the asset's annualized volatility toward the target (volatility
    targeting). Otherwise scale the per-position cap by signal ``strength``.
    Always bounded by the per-position cap, remaining room, and free cash.
    """
    if equity <= 0 or cash <= 0 or cap_fraction <= 0:
        return 0.0
    cap = equity * cap_fraction
    if vol_target > 0 and asset_vol > 0:
        annual_vol = asset_vol * (periods_per_year ** 0.5)
        frac = min(cap_fraction, vol_target / annual_vol) if annual_vol > 0 else cap_fraction
        desired = equity * max(0.0, frac)
    else:
        desired = cap * max(0.0, min(1.0, strength))
    room = max(0.0, cap - existing_value)
    return round(max(0.0, min(desired, room, cash)), 2)


def rebalance_amount(realized_profit: float, rebalance_profit_pct: float) -> float:
    """Half (by default) of a realized gain is skimmed into the reserve."""
    if realized_profit <= 0:
        return 0.0
    return round(realized_profit * max(0.0, min(1.0, rebalance_profit_pct)), 2)
