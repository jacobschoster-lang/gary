"""Brokers for the trading bot.

``PaperBroker`` is a fully offline, deterministic simulated account: it holds
cash + positions and fills market orders at whatever price it is given, tracking
realized P&L. It is the default so the bot never touches a real account.

Real brokers (e.g. Robinhood Crypto) implement the same small surface and are
env-gated, exactly like ``gary.finance.plaid.PlaidClient`` — see
``gary.trading.robinhood``. Keep the bot on paper until you deliberately wire a
live broker in.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from gary.trading.models import Fill, Position


@runtime_checkable
class Broker(Protocol):
    """Minimal surface the trading engine needs from any broker."""

    def buy(self, symbol: str, notional: float, price: float, *, on: str) -> Fill | None: ...

    def sell(self, symbol: str, quantity: float, price: float, *, on: str) -> Fill | None: ...

    def equity(self, prices: dict[str, float]) -> float: ...


class PaperBroker:
    """A simulated brokerage account. No network, fully deterministic."""

    def __init__(
        self, cash: float = 10_000.0, fee_bps: float = 0.0, slippage_bps: float = 0.0
    ) -> None:
        self.cash = float(cash)
        self.reserve = 0.0  # lower-risk bucket funded from realized profits
        self.realized_pnl = 0.0
        # Trading frictions (basis points). fee = commission/spread on notional;
        # slippage worsens the fill price. Both default off so unit tests that
        # construct a bare broker stay exact; the engine wires in realistic values.
        self.fee_bps = float(fee_bps)
        self.slippage_bps = float(slippage_bps)
        self.fees_paid = 0.0
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []

    # -- orders ---------------------------------------------------------------
    def buy(
        self, symbol: str, notional: float, price: float, *, on: str = "", strategy: str = "",
        reason: str = "",
    ) -> Fill | None:
        """Buy ``notional`` dollars of ``symbol`` at ``price``, net of fees/slippage."""
        notional = min(notional, self.cash)
        if notional <= 0 or price <= 0:
            return None
        eff_price = price * (1 + self.slippage_bps / 10_000)  # pay up when buying
        fee = notional * (self.fee_bps / 10_000)
        invested = notional - fee
        if invested <= 0 or eff_price <= 0:
            return None
        qty = invested / eff_price
        pos = self.positions.get(symbol)
        # Cost basis = full cash outlay (incl. fee/slippage) so realized P&L is net.
        if pos is None:
            self.positions[symbol] = Position(
                symbol=symbol, quantity=qty, avg_cost=notional / qty,
                opened_on=on, strategy=strategy,
            )
        else:
            total_cost = pos.cost_basis() + notional
            pos.quantity += qty
            pos.avg_cost = total_cost / pos.quantity
        self.cash -= notional
        self.fees_paid += fee
        fill = Fill(
            date=on, symbol=symbol, side="buy", quantity=round(qty, 8), price=round(eff_price, 6),
            notional=round(notional, 2), strategy=strategy, reason=reason,
        )
        self.fills.append(fill)
        return fill

    def sell(
        self, symbol: str, quantity: float, price: float, *, on: str = "", strategy: str = "",
        reason: str = "",
    ) -> Fill | None:
        """Sell ``quantity`` units of ``symbol`` at ``price`` and realize net P&L."""
        pos = self.positions.get(symbol)
        if pos is None or price <= 0:
            return None
        quantity = min(quantity, pos.quantity)
        if quantity <= 0:
            return None
        eff_price = price * (1 - self.slippage_bps / 10_000)  # take less when selling
        gross = quantity * eff_price
        fee = gross * (self.fee_bps / 10_000)
        proceeds = gross - fee
        realized = proceeds - quantity * pos.avg_cost  # net of both buy & sell costs
        self.cash += proceeds
        self.realized_pnl += realized
        self.fees_paid += fee
        pos.quantity -= quantity
        if pos.quantity <= 1e-9:
            del self.positions[symbol]
        fill = Fill(
            date=on, symbol=symbol, side="sell", quantity=round(quantity, 8),
            price=round(eff_price, 6), notional=round(proceeds, 2), strategy=strategy,
            reason=reason, realized_pnl=round(realized, 2),
        )
        self.fills.append(fill)
        return fill

    def move_to_reserve(self, amount: float) -> float:
        """Shift free cash into the lower-risk reserve bucket."""
        amount = max(0.0, min(amount, self.cash))
        self.cash -= amount
        self.reserve += amount
        return amount

    # -- valuation ------------------------------------------------------------
    def positions_value(self, prices: dict[str, float]) -> float:
        return sum(p.market_value(prices.get(sym, p.avg_cost)) for sym, p in self.positions.items())

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + self.reserve + self.positions_value(prices)

    def to_dict(self, prices: dict[str, float] | None = None) -> dict[str, Any]:
        prices = prices or {}
        return {
            "cash": round(self.cash, 2),
            "reserve": round(self.reserve, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "fees_paid": round(self.fees_paid, 2),
            "positions_value": round(self.positions_value(prices), 2),
            "equity": round(self.equity(prices), 2),
            "positions": [
                p.to_dict(prices.get(sym)) for sym, p in sorted(self.positions.items())
            ],
        }

    def serialize(self) -> dict[str, Any]:
        """Full state for persistence (prices not needed)."""
        return {
            "cash": self.cash,
            "reserve": self.reserve,
            "realized_pnl": self.realized_pnl,
            "fees_paid": self.fees_paid,
            "fee_bps": self.fee_bps,
            "slippage_bps": self.slippage_bps,
            "positions": [p.to_dict() for p in self.positions.values()],
            "fills": [f.to_dict() for f in self.fills],
        }

    @classmethod
    def deserialize(cls, data: dict[str, Any] | None) -> PaperBroker:
        data = data or {}
        broker = cls(
            cash=float(data.get("cash", 10_000.0) or 0.0),
            fee_bps=float(data.get("fee_bps", 0.0) or 0.0),
            slippage_bps=float(data.get("slippage_bps", 0.0) or 0.0),
        )
        broker.reserve = float(data.get("reserve", 0.0) or 0.0)
        broker.realized_pnl = float(data.get("realized_pnl", 0.0) or 0.0)
        broker.fees_paid = float(data.get("fees_paid", 0.0) or 0.0)
        for p in data.get("positions", []):
            broker.positions[str(p["symbol"])] = Position(
                symbol=str(p["symbol"]),
                quantity=float(p.get("quantity", 0) or 0),
                avg_cost=float(p.get("avg_cost", 0) or 0),
                opened_on=str(p.get("opened_on", "")),
                strategy=str(p.get("strategy", "")),
                peak_price=float(p.get("peak_price", 0) or 0),
            )
        for f in data.get("fills", []):
            broker.fills.append(
                Fill(
                    date=str(f.get("date", "")),
                    symbol=str(f.get("symbol", "")),
                    side=f.get("side", "buy"),
                    quantity=float(f.get("quantity", 0) or 0),
                    price=float(f.get("price", 0) or 0),
                    notional=float(f.get("notional", 0) or 0),
                    strategy=str(f.get("strategy", "")),
                    reason=str(f.get("reason", "")),
                    realized_pnl=float(f.get("realized_pnl", 0) or 0),
                )
            )
        return broker
