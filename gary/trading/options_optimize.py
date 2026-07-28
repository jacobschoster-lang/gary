"""Options strategy optimizer.

Grid-searches option strategies + parameters on a **train** slice of the
underlying's history and reports honest **out-of-sample** results on a later
slice, reusing the same discipline as the equities optimizer:

  - benchmark against buy-and-hold of the underlying,
  - haircut the winner's Sharpe for multiple-testing (deflated Sharpe),
  - Monte Carlo the out-of-sample cycle P&Ls (risk of ruin / percentiles),
  - cost-sensitivity sweep at 1x/2x/3x commissions.

Prices are fetched once and reused across every candidate and both slices.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gary.trading import montecarlo, selection
from gary.trading import prices as price_data
from gary.trading.option_strategies import STRATEGIES
from gary.trading.options_backtest import OptionsBacktester, OptionsConfig


def candidate_configs(base: OptionsConfig) -> list[OptionsConfig]:
    grid: list[OptionsConfig] = []
    for strat in STRATEGIES:
        for dte in (21, 35):
            for profit_take in (0.0, 0.5):
                grid.append(replace(base, strategy=strat, dte=dte, profit_take=profit_take))
    return grid


def _params(cfg: OptionsConfig) -> dict[str, Any]:
    return {"strategy": cfg.strategy, "dte": cfg.dte, "moneyness": cfg.moneyness,
            "profit_take": cfg.profit_take}


def _summary(cfg: OptionsConfig, report: dict[str, Any]) -> dict[str, Any]:
    m = report.get("metrics", {})
    return {"return_pct": report.get("return_pct", 0.0),
            "max_drawdown_pct": m.get("max_drawdown_pct", 0.0),
            "sharpe": m.get("sharpe", 0.0), "win_rate": m.get("win_rate", 0.0),
            "num_trades": report.get("num_trades", 0), "params": _params(cfg)}


def optimize(base: OptionsConfig | None = None, use_live: bool = True,
             train_frac: float = 0.6, top_n: int = 5) -> dict[str, Any]:
    base = base or OptionsConfig()
    warmup = base.vol_window + 1
    span = max(700, warmup + 14 * base.dte)
    series = price_data.price_series(base.symbol, span, use_live=use_live)
    n = len(series)
    split = warmup + int((n - warmup) * train_frac)
    train_series = series[:split]
    test_series = series[max(0, split - warmup):]  # warmup lead-in for the vol estimate

    grid = candidate_configs(base)
    ranked: list[tuple[float, OptionsConfig, dict, dict]] = []
    for cand in grid:
        tr = OptionsBacktester(cand, use_live=use_live).run(train_series)
        te = OptionsBacktester(cand, use_live=use_live).run(test_series)
        score = tr.get("metrics", {}).get("sharpe", 0.0) * 1000 + tr.get("return_pct", 0.0)
        ranked.append((score, cand, tr, te))
    ranked.sort(key=lambda r: r[0], reverse=True)
    # Prefer configs that actually trade (>=3 train cycles); fall back if none do.
    tradeable = [row for row in ranked if row[2].get("num_trades", 0) >= 3]
    _, best_cfg, best_tr, best_te = (tradeable or ranked)[0]

    n_obs = max(1, best_tr.get("cycles", 1))
    deflated = selection.deflated_sharpe(best_tr.get("metrics", {}).get("sharpe", 0.0),
                                         len(grid), n_obs)
    oos_pnls = [t["realized_pnl"] for t in best_te.get("trades", [])]
    mc = montecarlo.summarize(oos_pnls, base.starting_cash, base.goal_equity(),
                              n_paths=2000, seed=11)
    cost = []
    for mult in (1.0, 2.0, 3.0):
        c = replace(best_cfg, commission_per_contract=best_cfg.commission_per_contract * mult)
        rep = OptionsBacktester(c, use_live=use_live).run(test_series)
        cost.append({"cost_multiple": mult, "return_pct": rep.get("return_pct", 0.0)})

    in_ret = best_tr.get("return_pct", 0.0)
    oos_ret = best_te.get("return_pct", 0.0)
    bench = best_te.get("underlying_return_pct", 0.0)
    return {
        "symbol": base.symbol,
        "tried": len(grid),
        "objective": "train Sharpe, reported out-of-sample",
        "in_sample": _summary(best_cfg, best_tr),
        "out_of_sample": _summary(best_cfg, best_te),
        "benchmark": {"name": f"buy & hold {base.symbol}", "return_pct": bench},
        "beats_benchmark": oos_ret > bench,
        "overfit_gap_pct": round(in_ret - oos_ret, 2),
        "selection": {"observed_sharpe": best_tr.get("metrics", {}).get("sharpe", 0.0),
                      "deflated_sharpe": round(deflated, 3), "n_trials": len(grid)},
        "monte_carlo": mc,
        "cost_sensitivity": cost,
        "best_config": best_cfg.to_dict(),
        "best_report": best_te,
        "leaderboard": [
            {"train_return_pct": tr.get("return_pct", 0.0),
             "test_return_pct": te.get("return_pct", 0.0),
             "sharpe": te.get("metrics", {}).get("sharpe", 0.0), **_summary(cfg, te)}
            for _, cfg, tr, te in ranked[:top_n]
        ],
        "live_data": use_live,
    }
