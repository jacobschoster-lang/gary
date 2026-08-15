"""Forward live step: model signals -> Robinhood MCP equities (env-gated).

``simulate`` / Optimize stay on :class:`PaperBroker`. This module is the only
path that can send real orders, and only when ``TRADING_LIVE=1``.

Safety rails:
  * Equities only (BTC/ETH/SOL are dropped — the MCP is equity trading).
  * Long-only (``long_short`` is forced to ``cross_sectional``).
  * Per-order and per-step notional caps (defaults $250 / $1,500).
  * ``dry_run=True`` calls ``review_equity_order`` only.
  * Starts from the **agentic account** snapshot, not the paper $10k book.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

import gary.trading.prices as price_data
from gary.trading.broker import PaperBroker
from gary.trading.engine import TradingBot
from gary.trading.models import BotConfig, Fill, Position
from gary.trading.robinhood_mcp import RobinhoodMcpBroker, RobinhoodMcpError

DEFAULT_MAX_ORDER_USD = 250.0
DEFAULT_MAX_GROSS_USD = 1_500.0


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def max_order_usd() -> float:
    return max(1.0, _env_float("GARY_LIVE_MAX_ORDER_USD", DEFAULT_MAX_ORDER_USD))


def max_gross_usd() -> float:
    return max(1.0, _env_float("GARY_LIVE_MAX_GROSS_USD", DEFAULT_MAX_GROSS_USD))


def equity_universe(config: BotConfig) -> list[str]:
    return [s for s in config.universe if not price_data.is_crypto(s)]


def live_config(config: BotConfig) -> BotConfig:
    cfg = replace(config, universe=equity_universe(config) or ["AAPL", "MSFT", "NVDA"])
    if cfg.selection_mode == "long_short":
        cfg = replace(cfg, selection_mode="cross_sectional")
    return cfg


def _num(data: dict, *keys: str, default: float = 0.0) -> float:
    for key in keys:
        val = data.get(key)
        if val is None:
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return default


_BUYING_POWER_KEYS = (
    "buying_power", "buyingPower", "cash", "available_cash",
    "availableCash", "cash_available",
)


def buying_power_from_portfolio(raw: Any) -> float | None:
    """Spendable cash only. ``total_value`` is portfolio worth, not buying power."""
    if not isinstance(raw, dict):
        return None
    for key in _BUYING_POWER_KEYS:
        if key not in raw or raw[key] is None:
            continue
        try:
            return max(0.0, float(raw[key]))
        except (TypeError, ValueError):
            continue
    return None


def positions_from_mcp(raw: Any) -> dict[str, Position]:
    items: list = []
    if isinstance(raw, dict):
        items = raw.get("positions") or raw.get("results") or raw.get("equities") or []
    elif isinstance(raw, list):
        items = raw
    out: dict[str, Position] = {}
    for row in items:
        if not isinstance(row, dict):
            continue
        inst = row.get("instrument") if isinstance(row.get("instrument"), dict) else {}
        symbol = str(row.get("symbol") or inst.get("symbol") or "").upper()
        qty = _num(row, "quantity", "qty", "shares")
        avg = _num(row, "average_price", "avg_cost", "average_buy_price", "avgCost")
        if avg <= 0 and qty:
            basis = _num(row, "cost_basis", "costBasis")
            if basis:
                avg = abs(basis / qty)
        if not symbol or qty == 0:
            continue
        out[symbol] = Position(symbol=symbol, quantity=qty, avg_cost=avg or 0.0)
    return out


def paper_from_snapshot(
    portfolio: Any,
    positions_raw: Any,
) -> PaperBroker:
    cash = buying_power_from_portfolio(portfolio)
    if cash is None:
        raise RobinhoodMcpError(
            "portfolio missing buying_power/cash; refusing live step"
        )
    paper = PaperBroker(cash=cash, fee_bps=0.0, slippage_bps=0.0)
    for symbol, pos in positions_from_mcp(positions_raw).items():
        if price_data.is_crypto(symbol) or pos.quantity <= 0:
            continue
        paper.positions[symbol] = pos
    return paper


class LiveRouter:
    """Forwards long equity orders to MCP; keeps a paper shadow for the engine."""

    def __init__(
        self,
        paper: PaperBroker,
        mcp: RobinhoodMcpBroker | None,
        *,
        dry_run: bool = True,
        max_order: float = DEFAULT_MAX_ORDER_USD,
        max_gross: float = DEFAULT_MAX_GROSS_USD,
    ) -> None:
        self.paper = paper
        self.mcp = mcp
        self.dry_run = dry_run
        self.max_order = max_order
        self.max_gross = max_gross
        self.gross_sent = 0.0
        self.routed: list[dict[str, Any]] = []
        self.skipped: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.paper, name)

    def _skip(self, symbol: str, side: str, reason: str) -> None:
        self.skipped.append({"symbol": symbol, "side": side, "reason": reason})

    def _cap(self, notional: float) -> float:
        return max(0.0, min(notional, self.max_order, self.max_gross - self.gross_sent))

    def _route(self, symbol: str, side: str, *, dollar_amount: float | None = None,
               quantity: float | None = None) -> Any:
        if self.mcp is None:
            raise RobinhoodMcpError("Robinhood MCP not configured")
        if self.dry_run:
            return self.mcp.review_order(
                symbol, side, dollar_amount=dollar_amount, quantity=quantity,
            )
        return self.mcp.place_order(
            symbol, side, dollar_amount=dollar_amount, quantity=quantity,
        )

    def buy(self, symbol: str, notional: float, price: float, *, on: str = "",
            strategy: str = "", reason: str = "") -> Fill | None:
        if price_data.is_crypto(symbol):
            self._skip(symbol, "buy", "crypto skipped (equity MCP)")
            return None
        capped = self._cap(notional)
        if capped < 1.0:
            self._skip(symbol, "buy", "below live notional cap")
            return None
        result = self._route(symbol, "buy", dollar_amount=round(capped, 2))
        self.gross_sent += capped
        self.routed.append({
            "action": "review" if self.dry_run else "place",
            "side": "buy", "symbol": symbol, "dollar_amount": round(capped, 2),
            "result": result, "reason": reason,
        })
        return self.paper.buy(symbol, capped, price, on=on, strategy=strategy, reason=reason)

    def sell(self, symbol: str, quantity: float, price: float, *, on: str = "",
             strategy: str = "", reason: str = "") -> Fill | None:
        if price_data.is_crypto(symbol):
            self._skip(symbol, "sell", "crypto skipped (equity MCP)")
            return None
        if quantity <= 0 or price <= 0:
            return None
        notional = quantity * price
        if notional > self.max_order:
            quantity = self.max_order / price
        result = self._route(symbol, "sell", quantity=round(quantity, 8))
        self.routed.append({
            "action": "review" if self.dry_run else "place",
            "side": "sell", "symbol": symbol, "quantity": round(quantity, 8),
            "result": result, "reason": reason,
        })
        return self.paper.sell(symbol, quantity, price, on=on, strategy=strategy, reason=reason)

    def short(self, symbol: str, notional: float, price: float, *, on: str = "",
              strategy: str = "", reason: str = "") -> Fill | None:
        self._skip(symbol, "short", "shorts disabled on live")
        return None

    def cover(self, symbol: str, quantity: float, price: float, *, on: str = "",
              strategy: str = "", reason: str = "") -> Fill | None:
        self._skip(symbol, "cover", "shorts disabled on live")
        return None


def step_robinhood(
    mcp: RobinhoodMcpBroker,
    config: BotConfig | None = None,
    *,
    dry_run: bool = True,
    max_order: float | None = None,
    max_gross: float | None = None,
    use_live_prices: bool = True,
) -> dict[str, Any]:
    """One forward step against the agentic account. ``simulate`` is never used."""
    if not dry_run and not mcp.live_enabled:
        raise RobinhoodMcpError("live trading disabled; set TRADING_LIVE=1 to enable")
    cfg = live_config(config or BotConfig())
    order_cap = max_order_usd()
    gross_cap = max_gross_usd()
    if max_order is not None:
        order_cap = min(max_order, order_cap)
    if max_gross is not None:
        gross_cap = min(max_gross, gross_cap)
    portfolio = mcp.get_portfolio()
    held = mcp.get_equity_positions()
    paper = paper_from_snapshot(portfolio, held)
    router = LiveRouter(
        paper, mcp, dry_run=dry_run,
        max_order=order_cap,
        max_gross=gross_cap,
    )
    bot = TradingBot(config=cfg, broker=router, use_live=use_live_prices)
    result = bot.step_live()
    return {
        "dry_run": dry_run,
        "mode": "review" if dry_run else "live",
        "note": (
            "One forward step on the agentic account (equities only, notional-capped). "
            "This is not a 10%/month forecast — walk-forward OOS on this model was ~flat."
        ),
        "caps": {"max_order_usd": router.max_order, "max_gross_usd": router.max_gross},
        "universe": cfg.universe,
        "selection_mode": cfg.selection_mode,
        "buying_power": round(paper.cash, 2),
        "date": result["date"],
        "equity": result["equity"],
        "actions": result["actions"],
        "routed": router.routed,
        "skipped": router.skipped,
        "account": result["account"],
        "portfolio": portfolio,
    }
