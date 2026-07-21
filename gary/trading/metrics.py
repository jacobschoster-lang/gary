"""Performance-metrics pure functions for the trading bot.

These turn an equity curve and a list of fills into the standard set of
backtest statistics (returns, drawdown, Sharpe/Sortino/Calmar, trade stats,
turnover). Everything here is pure: no I/O, no network, standard library only.

Inputs are handled defensively -- empty or too-short inputs return ``0.0``
(or an empty/zeroed structure) rather than raising or dividing by zero, so
callers can feed partial data without guarding every call.
"""

from __future__ import annotations

import math
import statistics


def returns(equity: list[float]) -> list[float]:
    """Per-step simple returns from an equity curve. ``[]`` if <2 points."""
    if len(equity) < 2:
        return []
    out: list[float] = []
    for prev, cur in zip(equity, equity[1:], strict=False):
        if prev == 0:
            out.append(0.0)
        else:
            out.append(cur / prev - 1.0)
    return out


def total_return_pct(equity: list[float]) -> float:
    """``(equity[-1]/equity[0] - 1) * 100``. 0.0 if <2 points or equity[0]<=0."""
    if len(equity) < 2 or equity[0] <= 0:
        return 0.0
    return (equity[-1] / equity[0] - 1.0) * 100.0


def cagr(equity: list[float], periods_per_year: int = 252) -> float:
    """Compound annual growth rate as a fraction (e.g. 0.2 = 20%).

    Uses ``len(equity)-1`` steps as the elapsed period. 0.0 if not computable.
    """
    if len(equity) < 2 or equity[0] <= 0 or equity[-1] <= 0 or periods_per_year <= 0:
        return 0.0
    years = (len(equity) - 1) / periods_per_year
    if years <= 0:
        return 0.0
    return (equity[-1] / equity[0]) ** (1.0 / years) - 1.0


def max_drawdown_pct(equity: list[float]) -> float:
    """Largest peak-to-trough decline as a POSITIVE percent (e.g. 12.5). 0.0 if none."""
    if len(equity) < 2:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for value in equity:
        if value > peak:
            peak = value
        if peak > 0:
            drawdown = (peak - value) / peak
            if drawdown > worst:
                worst = drawdown
    return worst * 100.0


def sharpe(
    equity: list[float],
    periods_per_year: int = 252,
    risk_free: float = 0.0,
) -> float:
    """Annualized Sharpe ratio from per-step returns.

    ``(mean(r) - rf_per_step) / std(r) * sqrt(periods_per_year)`` using the
    population standard deviation. 0.0 if <2 returns or std==0.
    """
    rets = returns(equity)
    if len(rets) < 2 or periods_per_year <= 0:
        return 0.0
    std = statistics.pstdev(rets)
    if std == 0:
        return 0.0
    rf_per_step = risk_free / periods_per_year
    excess = statistics.fmean(rets) - rf_per_step
    return excess / std * math.sqrt(periods_per_year)


def sortino(
    equity: list[float],
    periods_per_year: int = 252,
    risk_free: float = 0.0,
) -> float:
    """Like :func:`sharpe` but the denominator is downside deviation.

    Downside deviation is the population root-mean-square of the negative
    excess returns (positive excess returns contribute 0). 0.0 if there is no
    downside or the result is not computable.
    """
    rets = returns(equity)
    if len(rets) < 2 or periods_per_year <= 0:
        return 0.0
    rf_per_step = risk_free / periods_per_year
    excess = [r - rf_per_step for r in rets]
    downside = [e for e in excess if e < 0]
    if not downside:
        return 0.0
    downside_dev = math.sqrt(sum(e * e for e in downside) / len(rets))
    if downside_dev == 0:
        return 0.0
    return statistics.fmean(excess) / downside_dev * math.sqrt(periods_per_year)


def calmar(equity: list[float], periods_per_year: int = 252) -> float:
    """``cagr / (max_drawdown_pct/100)``. 0.0 if drawdown is 0 or not computable."""
    mdd = max_drawdown_pct(equity)
    if mdd == 0:
        return 0.0
    return cagr(equity, periods_per_year) / (mdd / 100.0)


def trade_stats(fills: list[dict]) -> dict:
    """Realized-trade statistics from a list of fill dicts.

    Only fills with ``side == 'sell'`` carry realized P&L in ``realized_pnl``.
    """
    sells = [f for f in fills if f.get("side") == "sell"]
    closed = len(sells)
    win_pnls = [float(f.get("realized_pnl", 0.0)) for f in sells if f.get("realized_pnl", 0.0) > 0]
    loss_pnls = [float(f.get("realized_pnl", 0.0)) for f in sells if f.get("realized_pnl", 0.0) < 0]
    wins = len(win_pnls)
    losses = len(loss_pnls)

    win_rate = (wins / closed * 100.0) if closed else 0.0
    avg_win = statistics.fmean(win_pnls) if win_pnls else 0.0
    avg_loss = statistics.fmean(loss_pnls) if loss_pnls else 0.0

    total_wins = sum(win_pnls)
    total_losses = abs(sum(loss_pnls))
    if total_losses > 0:
        profit_factor = total_wins / total_losses
    else:
        profit_factor = total_wins if wins else 0.0

    return {
        "closed_trades": closed,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
    }


def turnover(fills: list[dict], equity: list[float]) -> float:
    """Sum of all fill ``notional`` divided by mean equity. 0.0 if no equity."""
    if not equity:
        return 0.0
    mean_equity = statistics.fmean(equity)
    if mean_equity == 0:
        return 0.0
    notional = sum(float(f.get("notional", 0.0)) for f in fills)
    return notional / mean_equity


def summarize(
    equity: list[float],
    fills: list[dict],
    periods_per_year: int = 252,
) -> dict:
    """Bundle every metric into one rounded dict.

    Floats are rounded to 2 decimals, except ``sharpe``/``sortino``/``calmar``
    which use 3. ``cagr_pct`` is ``cagr * 100``.
    """
    stats = trade_stats(fills)
    result = {
        "total_return_pct": round(total_return_pct(equity), 2),
        "cagr_pct": round(cagr(equity, periods_per_year) * 100.0, 2),
        "max_drawdown_pct": round(max_drawdown_pct(equity), 2),
        "sharpe": round(sharpe(equity, periods_per_year), 3),
        "sortino": round(sortino(equity, periods_per_year), 3),
        "calmar": round(calmar(equity, periods_per_year), 3),
        "turnover": round(turnover(fills, equity), 2),
    }
    for key, value in stats.items():
        result[key] = round(value, 2) if isinstance(value, float) else value
    return result
