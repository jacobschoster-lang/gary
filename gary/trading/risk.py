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


def rebalance_amount(realized_profit: float, rebalance_profit_pct: float) -> float:
    """Half (by default) of a realized gain is skimmed into the reserve."""
    if realized_profit <= 0:
        return 0.0
    return round(realized_profit * max(0.0, min(1.0, rebalance_profit_pct)), 2)
