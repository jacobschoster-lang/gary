"""Option strategy builders.

Each builder takes the underlying price ``S``, annualized vol ``sigma``, rate
``r``, and time-to-expiry ``t`` (years), and returns a strategy dict:

    {
      "name": str,
      "legs": [{"kind": "call"|"put", "strike": float, "qty": int}, ...],
      "entry_credit": float,   # net cash received at entry (per 1 contract set),
                               # positive = credit (short premium), negative = debit
      "max_profit": float,     # best-case P&L per contract set (>= 0 for credit)
      "max_loss": float,       # worst-case loss per contract set (positive number)
    }

``qty`` is in contracts; a negative qty is a short leg. All cash is scaled by the
standard 100-share contract multiplier. These are option-only structures (no
underlying leg) so P&L is computed purely from the legs.
"""

from __future__ import annotations

from typing import Any

from gary.trading.options import bs_price, intrinsic

MULTIPLIER = 100
_BIG = 1e9  # cap for "undefined" risk so sizing stays finite


def _leg(kind: str, strike: float, qty: int) -> dict[str, Any]:
    return {"kind": kind, "strike": round(strike, 4), "qty": qty}


def entry_credit(legs: list[dict], S: float, r: float, t: float, sigma: float) -> float:
    """Net cash received at entry: +credit for shorts, −debit for longs."""
    total = 0.0
    for leg in legs:
        price = bs_price(leg["kind"], S, leg["strike"], t, r, sigma)
        total += -leg["qty"] * price * MULTIPLIER  # short (qty<0) -> receive premium
    return round(total, 2)


def payoff_at(legs: list[dict], S_expiry: float) -> float:
    """Total intrinsic payoff of the legs at expiry (per 1 contract set)."""
    return round(
        sum(leg["qty"] * intrinsic(leg["kind"], S_expiry, leg["strike"]) * MULTIPLIER
            for leg in legs),
        2,
    )


def _defined_risk(legs, S, r, t, sigma, lo: float, hi: float) -> tuple[float, float]:
    """Max profit / max loss for a defined-risk structure, by scanning terminal
    prices across [lo, hi] plus the leg strikes (payoff is piecewise-linear)."""
    credit = entry_credit(legs, S, r, t, sigma)
    points = sorted({lo, hi, *[leg["strike"] for leg in legs]})
    pnls = [credit + payoff_at(legs, p) for p in points]
    return round(max(pnls), 2), round(-min(pnls), 2)


def build(strategy: str, S: float, r: float, t: float, sigma: float,
          moneyness: float = 0.05, width: float = 0.05) -> dict[str, Any]:
    """Construct a strategy at the given moneyness/width (as fractions of S)."""
    m, w = moneyness, width
    if strategy == "cash_secured_put":
        legs = [_leg("put", S * (1 - m), -1)]
        credit = entry_credit(legs, S, r, t, sigma)
        # Worst case: underlying -> 0, put assigned at strike.
        max_loss = round(legs[0]["strike"] * MULTIPLIER - credit, 2)
        return {"name": strategy, "legs": legs, "entry_credit": credit,
                "max_profit": credit, "max_loss": max(1.0, max_loss)}
    if strategy == "short_strangle":
        legs = [_leg("put", S * (1 - m), -1), _leg("call", S * (1 + m), -1)]
        credit = entry_credit(legs, S, r, t, sigma)
        # Undefined upside risk; cap for sizing at ~ notional.
        return {"name": strategy, "legs": legs, "entry_credit": credit,
                "max_profit": credit, "max_loss": round(S * MULTIPLIER, 2)}
    if strategy == "long_straddle":
        legs = [_leg("call", S, 1), _leg("put", S, 1)]
        debit = entry_credit(legs, S, r, t, sigma)  # negative
        return {"name": strategy, "legs": legs, "entry_credit": debit,
                "max_profit": round(S * MULTIPLIER, 2), "max_loss": max(1.0, -debit)}
    if strategy == "bull_put_spread":
        legs = [_leg("put", S * (1 - m), -1), _leg("put", S * (1 - m - w), 1)]
    elif strategy == "bear_call_spread":
        legs = [_leg("call", S * (1 + m), -1), _leg("call", S * (1 + m + w), 1)]
    elif strategy == "iron_condor":
        legs = [
            _leg("put", S * (1 - m), -1), _leg("put", S * (1 - m - w), 1),
            _leg("call", S * (1 + m), -1), _leg("call", S * (1 + m + w), 1),
        ]
    else:
        raise ValueError(f"unknown option strategy: {strategy!r}")
    max_profit, max_loss = _defined_risk(legs, S, r, t, sigma, lo=S * 0.2, hi=S * 1.8)
    return {"name": strategy, "legs": legs, "entry_credit": entry_credit(legs, S, r, t, sigma),
            "max_profit": max_profit, "max_loss": max(1.0, max_loss)}


def payoff_curve(strategy: str, S: float, r: float, t: float, sigma: float,
                 moneyness: float = 0.05, width: float = 0.05,
                 lo_frac: float = 0.7, hi_frac: float = 1.3, points: int = 41) -> dict[str, Any]:
    """Expiration P&L of the structure across a grid of terminal underlying prices
    (for a payoff diagram). Includes breakevens and max profit/loss."""
    strat = build(strategy, S, r, t, sigma, moneyness, width)
    credit = strat["entry_credit"]
    lo, hi = S * lo_frac, S * hi_frac
    step = (hi - lo) / (points - 1) if points > 1 else 0.0
    prices, pnl = [], []
    for i in range(points):
        p = lo + step * i
        prices.append(round(p, 2))
        pnl.append(round(credit + payoff_at(strat["legs"], p), 2))
    breakevens = []
    for i in range(1, points):
        a, b = pnl[i - 1], pnl[i]
        if (a <= 0 <= b or a >= 0 >= b) and a != b:
            x = prices[i - 1] + (0 - a) * (prices[i] - prices[i - 1]) / (b - a)
            breakevens.append(round(x, 2))
    return {"strategy": strategy, "underlying": round(S, 2), "prices": prices, "pnl": pnl,
            "breakevens": breakevens, "max_profit": strat["max_profit"],
            "max_loss": strat["max_loss"], "entry_credit": credit}


STRATEGIES = (
    "cash_secured_put", "bull_put_spread", "bear_call_spread",
    "iron_condor", "short_strangle", "long_straddle",
)
