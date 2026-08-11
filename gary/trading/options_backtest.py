"""Options strategy backtester.

Runs an option strategy on one underlying in fixed cycles (≈ monthly): each
cycle it estimates volatility, opens the strategy's legs at Black-Scholes model
prices, then either closes early on a profit-take / stop, or holds to expiry
(intrinsic settlement). Position size is risk-based (a fraction of equity divided
by the structure's max loss), and commissions are charged per contract-leg.

Everything is deterministic offline (uses the synthetic price fallback), so the
optimizer and tests are reproducible. P&L is option-only (no underlying leg).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from gary.trading import metrics, risk
from gary.trading import prices as price_data
from gary.trading.option_strategies import build, payoff_at
from gary.trading.options import bs_price

_TRADING_DAYS = 252


@dataclass
class OptionsConfig:
    symbol: str = "NVDA"
    strategy: str = "iron_condor"
    starting_cash: float = 10_000.0
    dte: int = 21  # trading days to expiry per cycle
    moneyness: float = 0.05
    width: float = 0.05
    risk_pct: float = 0.10  # fraction of equity risked (max loss) per cycle
    profit_take: float = 0.5  # close when captured >= this frac of max profit (0 disables)
    stop_mult: float = 2.0  # close when loss >= this * max profit (0 disables)
    commission_per_contract: float = 0.65
    rate: float = 0.04
    vol_window: int = 20
    goal_multiple: float = 2.0

    def goal_equity(self) -> float:
        return self.starting_cash * self.goal_multiple

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["goal_equity"] = self.goal_equity()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> OptionsConfig:
        data = data or {}
        base = cls()

        def num(key, default, cast=float):
            v = data.get(key)
            return cast(v) if v is not None else default

        return cls(
            symbol=str(data.get("symbol") or base.symbol),
            strategy=str(data.get("strategy") or base.strategy),
            starting_cash=num("starting_cash", base.starting_cash),
            dte=num("dte", base.dte, int),
            moneyness=num("moneyness", base.moneyness),
            width=num("width", base.width),
            risk_pct=num("risk_pct", base.risk_pct),
            profit_take=num("profit_take", base.profit_take),
            stop_mult=num("stop_mult", base.stop_mult),
            commission_per_contract=num("commission_per_contract", base.commission_per_contract),
            rate=num("rate", base.rate),
            vol_window=num("vol_window", base.vol_window, int),
            goal_multiple=num("goal_multiple", base.goal_multiple),
        )


@dataclass
class OptionsBacktester:
    config: OptionsConfig = field(default_factory=OptionsConfig)
    use_live: bool = True

    def _annualized_vol(self, series: list[float], upto: int) -> float:
        v = risk.volatility(series[: upto + 1], self.config.vol_window) * (_TRADING_DAYS ** 0.5)
        return v if v > 0.01 else 0.30  # floor so pricing is sane when history is flat

    def run(self, series: list[float] | None = None) -> dict[str, Any]:
        cfg = self.config
        warmup = cfg.vol_window + 1
        if series is None:
            span = max(320, warmup + 10 * cfg.dte)
            series = price_data.price_series(cfg.symbol, span, use_live=self.use_live)
        n = len(series)
        equity = cfg.starting_cash
        today = date.today()
        curve: list[dict[str, Any]] = []
        fills: list[dict[str, Any]] = []
        r = cfg.rate

        i = warmup
        while i + cfg.dte < n:
            S = series[i]
            sigma = self._annualized_vol(series, i)
            t = cfg.dte / _TRADING_DAYS
            strat = build(cfg.strategy, S, r, t, sigma, cfg.moneyness, cfg.width)
            legs = strat["legs"]
            risk_per = strat["max_loss"]
            contracts = int((equity * cfg.risk_pct) // risk_per) if risk_per > 0 else 0
            # Allow a single lot when the risk budget can't cover one but the
            # account still can within a 50% cap (common for pricey underlyings).
            if contracts == 0 and 0 < risk_per <= equity * 0.5:
                contracts = 1
            date_str = (today - timedelta(days=n - 1 - i)).isoformat()
            if contracts <= 0:
                curve.append({"date": date_str, "equity": round(equity, 2)})
                i += cfg.dte
                continue

            entry = strat["entry_credit"] * contracts
            legcount = len(legs)
            open_comm = cfg.commission_per_contract * legcount * contracts
            max_profit_total = strat["max_profit"] * contracts

            realized = None
            close_day = cfg.dte
            close_comm = cfg.commission_per_contract * legcount * contracts
            for d in range(1, cfg.dte):
                s_d = series[i + d]
                t_r = (cfg.dte - d) / _TRADING_DAYS
                mark = sum(
                    leg["qty"] * bs_price(leg["kind"], s_d, leg["strike"], t_r, r, sigma) * 100
                    for leg in legs
                ) * contracts
                pnl_now = entry + mark
                take = cfg.profit_take > 0 and max_profit_total > 0 and \
                    pnl_now >= cfg.profit_take * max_profit_total
                stop = cfg.stop_mult > 0 and max_profit_total > 0 and \
                    pnl_now <= -cfg.stop_mult * max_profit_total
                if take or stop:
                    realized = pnl_now - open_comm - close_comm
                    close_day = d
                    break
            if realized is None:  # held to expiry (intrinsic settlement, no close commission)
                payoff = payoff_at(legs, series[i + cfg.dte]) * contracts
                realized = entry + payoff - open_comm

            equity += realized
            end_date = (today - timedelta(days=n - 1 - (i + close_day))).isoformat()
            fills.append({
                "date": end_date, "symbol": cfg.symbol, "side": "sell",
                "strategy": cfg.strategy, "contracts": contracts,
                "notional": round(abs(entry), 2), "realized_pnl": round(realized, 2),
                "held_days": close_day,
            })
            curve.append({"date": end_date, "equity": round(equity, 2)})
            i += cfg.dte

        return self._report(curve, fills, series)

    def _report(self, curve, fills, series) -> dict[str, Any]:
        cfg = self.config
        start = cfg.starting_cash
        end_equity = curve[-1]["equity"] if curve else start
        equity_series = [start] + [p["equity"] for p in curve]
        stats = metrics.summarize(equity_series, fills)
        goal = cfg.goal_equity()
        # Benchmark: buy & hold the underlying over the same tested span.
        bench = 0.0
        if len(series) > 1 and series[0] > 0:
            bench = round((series[-1] / series[0] - 1) * 100, 2)
        return {
            "config": cfg.to_dict(),
            "start_equity": round(start, 2),
            "end_equity": round(end_equity, 2),
            "return_pct": round((end_equity - start) / start * 100, 2) if start else 0.0,
            "max_drawdown_pct": stats["max_drawdown_pct"],
            "metrics": stats,
            "num_trades": len(fills),
            "cycles": len(curve),
            "underlying_return_pct": bench,
            "goal_equity": round(goal, 2),
            "goal_reached": end_equity >= goal,
            "equity_curve": curve,
            "trades": fills[-40:],
            "live_data": self.use_live,
        }


@dataclass
class OptionsPaperTrader:
    """Stateful, day-by-day forward options trader (for the scheduled paper job).

    Unlike ``OptionsBacktester`` (a from-scratch cycle backtest), this holds ONE
    open option position across days: each ``step`` marks it to Black-Scholes,
    closes on profit-take / stop / expiry, and (re)opens a fresh position when
    flat. Cash reflects realized P&L only; equity = cash + the open position's
    mark-to-model P&L.
    """

    config: OptionsConfig = field(default_factory=OptionsConfig)
    use_live: bool = True

    def _price_and_vol(self) -> tuple[float, float]:
        n = self.config.vol_window + 2
        series = price_data.price_series(self.config.symbol, n, use_live=self.use_live)
        S = series[-1]
        vol = risk.volatility(series, self.config.vol_window) * (_TRADING_DAYS ** 0.5)
        return S, (vol if vol > 0.01 else 0.30)

    def _unrealized(self, pos: dict, S: float, sigma: float) -> float:
        r = self.config.rate
        t_r = max(pos["days_left"], 0) / _TRADING_DAYS
        mark = sum(
            leg["qty"] * bs_price(leg["kind"], S, leg["strike"], t_r, r, sigma) * 100
            for leg in pos["legs"]
        ) * pos["contracts"]
        return pos["entry_credit"] + mark

    def step(self, state: dict, on: str | None = None,
             S: float | None = None, sigma: float | None = None,
             allow_new_entries: bool = True) -> dict[str, Any]:
        cfg = self.config
        r = cfg.rate
        on = on or date.today().isoformat()
        if S is None or sigma is None:
            S, sigma = self._price_and_vol()
        cash = float(state.get("cash", cfg.starting_cash))
        pos = state.get("position")
        action = "held"

        if pos:
            pos["days_left"] -= 1
            pnl_now = self._unrealized(pos, S, sigma)
            mp = pos["max_profit_total"]
            expired = pos["days_left"] <= 0
            take = cfg.profit_take > 0 and mp > 0 and pnl_now >= cfg.profit_take * mp
            stop = cfg.stop_mult > 0 and mp > 0 and pnl_now <= -cfg.stop_mult * mp
            if expired or take or stop:
                legcount = len(pos["legs"])
                close_comm = cfg.commission_per_contract * legcount * pos["contracts"]
                if expired:
                    payoff = payoff_at(pos["legs"], S) * pos["contracts"]
                    realized = pos["entry_credit"] + payoff - pos["open_comm"]
                else:
                    realized = pnl_now - pos["open_comm"] - close_comm
                cash += realized
                state.setdefault("realized", []).append(
                    {"date": on, "pnl": round(realized, 2), "strategy": pos["strategy"]})
                pos = None
                action = "closed"

        if not pos and allow_new_entries:
            t = cfg.dte / _TRADING_DAYS
            strat = build(cfg.strategy, S, r, t, sigma, cfg.moneyness, cfg.width)
            risk_per = strat["max_loss"]
            contracts = int((cash * cfg.risk_pct) // risk_per) if risk_per > 0 else 0
            if contracts == 0 and 0 < risk_per <= cash * 0.5:
                contracts = 1
            if contracts > 0:
                legcount = len(strat["legs"])
                pos = {
                    "strategy": cfg.strategy, "legs": strat["legs"], "contracts": contracts,
                    "entry_credit": strat["entry_credit"] * contracts, "entry_S": round(S, 4),
                    "dte": cfg.dte, "days_left": cfg.dte,
                    "max_profit_total": strat["max_profit"] * contracts,
                    "open_comm": cfg.commission_per_contract * legcount * contracts,
                    "opened_on": on,
                }
                action = "rolled" if action == "closed" else "opened"

        state["position"] = pos
        state["cash"] = round(cash, 2)
        unreal = self._unrealized(pos, S, sigma) if pos else 0.0
        equity = round(cash + unreal, 2)
        hist = state.setdefault("equity_history", [])
        hist[:] = [h for h in hist if h.get("date") != on]
        hist.append({"date": on, "equity": equity})

        return {
            "date": on, "action": action, "equity": equity, "cash": round(cash, 2),
            "symbol": cfg.symbol, "strategy": cfg.strategy,
            "position": (
                {"strategy": pos["strategy"], "contracts": pos["contracts"],
                 "days_left": pos["days_left"], "unrealized_pnl": round(unreal, 2)}
                if pos else None
            ),
            "equity_history_points": len(hist),
        }


class OptionsStore:
    """Local JSON persistence for the forward options paper account."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("GARY_OPTIONS_FILE", "finance_data/options.json"))

    def load(self) -> tuple[OptionsConfig, dict]:
        if not self.path.exists():
            return OptionsConfig(), {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return OptionsConfig(), {}
        return OptionsConfig.from_dict(data.get("config")), dict(data.get("state", {}))

    def save(self, config: OptionsConfig, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"config": config.to_dict(), "state": state}
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
