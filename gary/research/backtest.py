"""Cross-sectional factor backtester.

Each rebalance, ranks the universe by a factor score, goes long the top quantile
(optionally short the bottom, dollar-neutral), holds until the next rebalance,
and applies a turnover cost. This is a portfolio-return backtest (not order-level)
— the right granularity for factor research. Deterministic offline.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from gary.research.factors import min_history, score
from gary.trading import metrics

_TRADING_DAYS = 252


@dataclass
class FactorConfig:
    factor: str
    rebalance_days: int = 21
    top_quantile: float = 0.30
    long_short: bool = False
    cost_bps: float = 10.0
    starting_cash: float = 10_000.0

    def label(self) -> str:
        return f"{self.factor}{'/LS' if self.long_short else ''}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["label"] = self.label()
        return d


def buy_hold_return(panel: dict[str, list[float]], start_bar: int, end_bar: int) -> float:
    """Equal-weight buy-and-hold return of the universe over [start_bar, end_bar]."""
    rets = []
    for ser in panel.values():
        if end_bar < len(ser) and ser[start_bar] > 0:
            rets.append(ser[end_bar] / ser[start_bar] - 1)
    return (sum(rets) / len(rets)) if rets else 0.0


def run_factor(panel: dict[str, list[float]], cfg: FactorConfig,
               rebar: list[int]) -> dict[str, Any]:
    """Backtest one factor config over the given rebalance bar indices."""
    mh = min_history(cfg.factor)
    equity = cfg.starting_cash
    curve: list[dict[str, Any]] = []
    period_returns: list[float] = []
    cost = cfg.cost_bps / 10_000.0

    for k in range(len(rebar) - 1):
        e, e2 = rebar[k], rebar[k + 1]
        scores: dict[str, float] = {}
        for sym, ser in panel.items():
            if e >= mh and e2 < len(ser) and ser[e] > 0:
                scores[sym] = score(cfg.factor, ser[: e + 1])
        if len(scores) < 3:
            curve.append({"bar": e2, "equity": round(equity, 2)})
            continue
        ranked = sorted(scores, key=lambda s: scores[s], reverse=True)
        nsel = max(1, int(len(ranked) * cfg.top_quantile))
        longs = ranked[:nsel]
        shorts = ranked[-nsel:] if cfg.long_short else []

        def hold_ret(sym: str, _e: int = e, _e2: int = e2) -> float:
            return panel[sym][_e2] / panel[sym][_e] - 1

        long_ret = sum(hold_ret(s) for s in longs) / len(longs)
        if cfg.long_short and shorts:
            short_ret = sum(hold_ret(s) for s in shorts) / len(shorts)
            port_ret = (long_ret - short_ret) / 2  # dollar-neutral: half capital each leg
        else:
            port_ret = long_ret
        net = port_ret - cost
        equity *= 1 + net
        period_returns.append(net)
        curve.append({"bar": e2, "equity": round(equity, 2)})

    return _report(cfg, curve, period_returns, panel, rebar)


def _report(cfg, curve, period_returns, panel, rebar) -> dict[str, Any]:
    start = cfg.starting_cash
    end_equity = curve[-1]["equity"] if curve else start
    equity_series = [start] + [c["equity"] for c in curve]
    ppy = _TRADING_DAYS / max(1, cfg.rebalance_days)
    stats = metrics.summarize(equity_series, [], periods_per_year=round(ppy))
    n_periods = len(period_returns)
    years = (n_periods * cfg.rebalance_days) / _TRADING_DAYS if n_periods else 0.0
    cagr = ((end_equity / start) ** (1 / years) - 1) if years > 0 and start > 0 else 0.0
    bench = (buy_hold_return(panel, rebar[0], rebar[-1]) * 100) if len(rebar) >= 2 else 0.0
    return {
        "config": cfg.to_dict(),
        "start_equity": round(start, 2),
        "end_equity": round(end_equity, 2),
        "return_pct": round((end_equity / start - 1) * 100, 2) if start else 0.0,
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": stats["sharpe"],
        "max_drawdown_pct": stats["max_drawdown_pct"],
        "metrics": stats,
        "period_returns": period_returns,
        "equity_curve": curve,
        "benchmark_return_pct": round(bench, 2),
        "rebalances": n_periods,
        "years": round(years, 2),
    }
