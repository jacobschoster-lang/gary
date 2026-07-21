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
from gary.trading.strategies import (
    above_regime,
    combine,
    momentum_score,
    momentum_signal,
    signals_from_config,
)


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

        # 1 + 2) manage exits on open risk positions (take-profit/trailing/stop).
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
            if self._close(sym, price, on, reason, actions):
                exited.add(sym)

        # 1c) regime exits: drop anything that has fallen below its trend filter.
        if cfg.regime_ma > 0:
            for sym, pos in list(self.broker.positions.items()):
                if sym in exited:
                    continue
                if not above_regime(history.get(sym) or [], cfg.regime_ma):
                    price = prices.get(sym, pos.avg_cost)
                    if self._close(sym, price, on, f"regime exit (<{cfg.regime_ma}d MA)", actions):
                        exited.add(sym)

        # 3) entries.
        equity = self.broker.equity(prices)
        if cfg.selection_mode == "cross_sectional":
            self._cross_sectional_entries(history, prices, on, equity, exited, actions)
        else:
            self._per_symbol_entries(history, prices, on, equity, exited, actions)
        return actions

    def _close(
        self, sym: str, price: float, on: str, reason: str, actions: list[dict[str, Any]]
    ) -> bool:
        """Fully sell a position, skim profit to the reserve, and log the action."""
        pos = self.broker.positions.get(sym)
        if pos is None:
            return False
        fill = self.broker.sell(
            sym, pos.quantity, price, on=on, strategy=pos.strategy, reason=reason
        )
        if fill is None:
            return False
        act = {"action": "sell", "symbol": sym, "reason": reason, "realized_pnl": fill.realized_pnl}
        skim = risk.rebalance_amount(fill.realized_pnl, self.config.rebalance_profit_pct)
        if skim > 0:
            act["rebalanced_to_reserve"] = round(self.broker.move_to_reserve(skim), 2)
        actions.append(act)
        return True

    def _buy(
        self, sym: str, notional: float, price: float, on: str, why: str,
        actions: list[dict[str, Any]],
    ) -> None:
        if notional < 1.0:
            return
        fill = self.broker.buy(sym, notional, price, on=on, strategy="blend", reason=why)
        if not fill:
            return
        pos = self.broker.positions.get(sym)
        if pos is not None:
            pos.peak_price = max(pos.peak_price, price)
        actions.append({"action": "buy", "symbol": sym, "notional": fill.notional, "reason": why})

    def _per_symbol_entries(self, history, prices, on, equity, exited, actions) -> None:
        cfg = self.config
        for sym in cfg.universe:
            hist = history.get(sym)
            if not hist or sym in exited:
                continue
            price = prices.get(sym, hist[-1])
            if cfg.regime_ma > 0 and not above_regime(hist, cfg.regime_ma):
                continue  # trend filter blocks new longs
            action, strength, why = combine(signals_from_config(hist, cfg), cfg.weights)
            held = self.broker.positions.get(sym)
            if action == "buy" and strength >= cfg.min_signal_strength:
                if held is not None and not cfg.allow_add_ons:
                    continue
                existing = held.market_value(price) if held else 0.0
                notional = risk.position_notional(
                    equity, self.broker.cash, cfg.max_position_pct, existing,
                    strength=strength, asset_vol=risk.volatility(hist, cfg.vol_window),
                    vol_target=cfg.vol_target,
                )
                self._buy(sym, notional, price, on, why, actions)
            elif action == "sell" and held is not None:
                self._close(sym, price, on, f"signal: {why}", actions)

    def _cross_sectional_entries(self, history, prices, on, equity, exited, actions) -> None:
        """Rank the universe by momentum and hold the top N (rotating out the rest)."""
        cfg = self.config
        scores: dict[str, float] = {}
        for sym in cfg.universe:
            hist = history.get(sym)
            if not hist:
                continue
            if cfg.regime_ma > 0 and not above_regime(hist, cfg.regime_ma):
                continue
            # Only rank names with positive momentum (long-only, trend-following).
            if momentum_signal(hist, cfg.momentum_lookback, cfg.momentum_threshold).action != "buy":
                continue
            scores[sym] = momentum_score(hist, cfg.momentum_lookback)
        target = sorted(scores, key=lambda s: scores[s], reverse=True)[: cfg.top_n_positions]
        target_set = set(target)

        # Rotate out held names that fell out of the target set.
        for sym in list(self.broker.positions):
            if sym in exited or sym in target_set:
                continue
            self._close(sym, prices.get(sym, 0.0), on, "rotate out of top-N", actions)

        # Equal-weight (capped) allocation into the target names.
        cap_fraction = min(cfg.max_position_pct, 1.0 / max(1, cfg.top_n_positions))
        for sym in target:
            hist = history[sym]
            price = prices.get(sym, hist[-1])
            held = self.broker.positions.get(sym)
            existing = held.market_value(price) if held else 0.0
            notional = risk.position_notional(
                equity, self.broker.cash, cap_fraction, existing,
                strength=1.0, asset_vol=risk.volatility(hist, cfg.vol_window),
                vol_target=cfg.vol_target,
            )
            self._buy(sym, notional, price, on, "cross-sectional momentum top-N", actions)

    WARMUP = 25  # floor for bars of history needed before the first trade

    def warmup(self) -> int:
        """History needed before trading, widened by the longest lookback in use."""
        cfg = self.config
        return max(
            self.WARMUP, cfg.regime_ma, cfg.sma_long, cfg.mr_window,
            cfg.momentum_lookback + 1, cfg.vol_window + 1,
        )

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
        warmup = self.warmup()
        if series is None:
            span = days + warmup + 1  # +1 so the last decision has a next bar to fill on
            series = {
                s: price_data.price_series(s, span, use_live=self.use_live) for s in cfg.universe
            }
        length = min((len(v) for v in series.values()), default=0)
        last = length - 1
        first = max(warmup, last - days + 1)
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
