"""The paper trading bot: turns signals + risk rules into orders on a broker.

The engine is broker-agnostic (defaults to :class:`PaperBroker`) and market-data
agnostic (defaults to :mod:`gary.trading.prices`, which itself falls back to a
deterministic synthetic series offline).

Flow per tick:
    1. manage open positions (take-profit / stop-loss / strategy-driven exit)
    2. skim 50% of any realized profit into the lower-risk reserve
    3. open/add positions where the blended strategy signal says "buy"

``simulate`` runs this tick-by-tick over a historical window to backtest the
strategy and produce an equity curve + trade log, which is what the dashboard
"Run paper bot" button drives.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from gary.trading import metrics, risk
from gary.trading import prices as price_data
from gary.trading.broker import PaperBroker
from gary.trading.models import BotConfig
from gary.trading.strategies import combine, signals_from_config


class TradingBot:
    def __init__(
        self,
        config: BotConfig | None = None,
        broker: PaperBroker | None = None,
        use_live: bool = True,
    ) -> None:
        self.config = config or BotConfig()
        self.broker = broker or PaperBroker(cash=self.config.starting_cash)
        self.use_live = use_live

    # -- one step -------------------------------------------------------------
    def run_tick(
        self,
        history: dict[str, list[float]],
        on: str,
        exec_prices: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        """Advance the bot one bar.

        ``history[sym]`` is the closes known at decision time. ``exec_prices``
        is where orders actually fill — pass the *next* bar's price to avoid
        look-ahead bias. When omitted, fills use the last close in ``history``.
        """
        cfg = self.config
        prices = exec_prices or {s: h[-1] for s, h in history.items() if h}
        actions: list[dict[str, Any]] = []
        exited: set[str] = set()  # don't re-enter a name we just closed this tick

        # 1 + 2) manage exits on open risk positions.
        for sym, pos in list(self.broker.positions.items()):
            price = prices.get(sym, pos.avg_cost)
            ret = pos.return_pct(price)
            reason = None
            if cfg.trailing_stop_pct > 0:
                # Let winners run: arm a trailing stop once the position has been
                # in profit, exiting only on a pullback from the peak.
                pos.peak_price = max(pos.peak_price or pos.avg_cost, price)
                if pos.peak_price > pos.avg_cost:
                    drop = (pos.peak_price - price) / pos.peak_price
                    if drop >= cfg.trailing_stop_pct:
                        reason = f"trailing-stop +{ret * 100:.1f}% ({drop * 100:.1f}% off peak)"
            elif risk.should_take_profit(ret, cfg.take_profit_pct):
                reason = f"take-profit +{ret * 100:.1f}%"
            if reason is None and risk.should_stop_loss(ret, cfg.stop_loss_pct):
                reason = f"stop-loss {ret * 100:.1f}%"
            if reason is None:
                continue
            fill = self.broker.sell(
                sym, pos.quantity, price, on=on, strategy=pos.strategy, reason=reason
            )
            if fill is None:
                continue
            act = {"action": "sell", "symbol": sym, "reason": reason,
                   "realized_pnl": fill.realized_pnl}
            skim = risk.rebalance_amount(fill.realized_pnl, cfg.rebalance_profit_pct)
            if skim > 0:
                moved = self.broker.move_to_reserve(skim)
                act["rebalanced_to_reserve"] = round(moved, 2)
            exited.add(sym)
            actions.append(act)

        # 3) entries / strategy-driven exits.
        equity = self.broker.equity(prices)
        for sym in cfg.universe:
            hist = history.get(sym)
            if not hist or sym in exited:
                continue
            price = prices.get(sym, hist[-1])
            signals = signals_from_config(hist, cfg)
            action, strength, why = combine(signals, cfg.weights)
            held = self.broker.positions.get(sym)
            if action == "buy" and strength >= cfg.min_signal_strength:
                if held is not None and not cfg.allow_add_ons:
                    continue  # already holding; add-ons disabled
                existing = held.market_value(price) if held else 0.0
                notional = risk.target_position_notional(
                    equity, self.broker.cash, cfg.max_position_pct, existing, strength
                )
                if notional >= 1.0:
                    fill = self.broker.buy(
                        sym, notional, price, on=on, strategy="blend", reason=why
                    )
                    if fill:
                        pos = self.broker.positions.get(sym)
                        if pos is not None:
                            pos.peak_price = max(pos.peak_price, price)
                        actions.append({"action": "buy", "symbol": sym,
                                        "notional": fill.notional, "reason": why})
            elif action == "sell" and held is not None:
                fill = self.broker.sell(
                    sym, held.quantity, price, on=on, strategy="blend", reason=f"signal: {why}"
                )
                if fill:
                    act = {"action": "sell", "symbol": sym, "reason": f"signal: {why}",
                           "realized_pnl": fill.realized_pnl}
                    skim = risk.rebalance_amount(fill.realized_pnl, cfg.rebalance_profit_pct)
                    if skim > 0:
                        act["rebalanced_to_reserve"] = round(self.broker.move_to_reserve(skim), 2)
                    actions.append(act)
        return actions

    WARMUP = 25  # bars of history needed before the first trade (long SMA, etc.)

    # -- core backtest loop ---------------------------------------------------
    def _run(
        self, series: dict[str, list[float]], exec_bars: list[int]
    ) -> tuple[list[dict[str, Any]], dict[str, float]]:
        """Run the tick loop, executing at each bar in ``exec_bars``.

        At execution bar ``e`` decisions use closes strictly before ``e``
        (``series[:e]``) and orders fill at ``series[e]`` — i.e. next-bar-open
        execution, which removes look-ahead bias.
        """
        cfg = self.config
        self.broker = PaperBroker(
            cash=cfg.starting_cash, fee_bps=cfg.fee_bps, slippage_bps=cfg.slippage_bps
        )
        length = min((len(v) for v in series.values()), default=0)
        today = date.today()
        curve: list[dict[str, Any]] = []
        for e in exec_bars:
            history = {s: v[:e] for s, v in series.items()}
            exec_prices = {s: v[e] for s, v in series.items()}
            on = (today - timedelta(days=length - 1 - e)).isoformat()
            self.run_tick(history, on, exec_prices=exec_prices)
            curve.append({"date": on, "equity": round(self.broker.equity(exec_prices), 2)})
        final_prices = {s: v[exec_bars[-1]] for s, v in series.items()} if exec_bars else {}
        return curve, final_prices

    # -- backtest over a window ----------------------------------------------
    def simulate(
        self, days: int | None = None, series: dict[str, list[float]] | None = None
    ) -> dict[str, Any]:
        """Backtest from a fresh account over the last ``days`` of price history.

        ``series`` (symbol -> closes) can be supplied to reuse already-fetched
        prices across many candidate configs (used by the optimizer).
        """
        cfg = self.config
        days = days or cfg.horizon_days
        if series is None:
            span = days + self.WARMUP + 1  # +1 so the last decision has a next bar to fill on
            series = {
                s: price_data.price_series(s, span, use_live=self.use_live) for s in cfg.universe
            }
        length = min((len(v) for v in series.values()), default=0)
        last = length - 1
        first = max(self.WARMUP, last - days + 1)
        exec_bars = list(range(first, last + 1))
        curve, final_prices = self._run(series, exec_bars)
        return self.report(curve, final_prices, days=len(curve))

    # -- reporting ------------------------------------------------------------
    def report(
        self, curve: list[dict[str, Any]], prices: dict[str, float], days: int
    ) -> dict[str, Any]:
        cfg = self.config
        end_equity = self.broker.equity(prices)
        start = cfg.starting_cash
        goal = cfg.goal_equity()
        ret_pct = (end_equity - start) / start * 100 if start else 0.0
        equity_series = [start] + [p["equity"] for p in curve]
        fills = [f.to_dict() for f in self.broker.fills]
        stats = metrics.summarize(equity_series, fills)
        return {
            "config": cfg.to_dict(),
            "days": days,
            "start_equity": round(start, 2),
            "end_equity": round(end_equity, 2),
            "return_pct": round(ret_pct, 2),
            "max_drawdown_pct": stats["max_drawdown_pct"],
            "metrics": stats,
            "fees_paid": round(self.broker.fees_paid, 2),
            "goal_equity": round(goal, 2),
            "goal_progress_pct": round(min(100.0, end_equity / goal * 100), 2) if goal else 0.0,
            "goal_reached": end_equity >= goal,
            "num_trades": len(self.broker.fills),
            "equity_curve": curve,
            "trades": [f.to_dict() for f in self.broker.fills[-60:]],
            "account": self.broker.to_dict(prices),
            "live_data": self.use_live,
        }

    def status(self) -> dict[str, Any]:
        prices = price_data.latest_prices(self.config.universe, use_live=self.use_live)
        # Include any held symbols outside the configured universe, too.
        for sym in self.broker.positions:
            prices.setdefault(sym, price_data.price_series(sym, 60, use_live=self.use_live)[-1])
        return self.report(curve=[], prices=prices, days=0)
