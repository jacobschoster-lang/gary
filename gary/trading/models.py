"""Data models for the paper trading bot.

All amounts are in USD. Everything is a plain dataclass with ``to_dict`` so the
API/dashboard can serialize state, mirroring the finance module's conventions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Action = Literal["buy", "sell", "hold", "short", "cover"]


@dataclass
class Signal:
    """A single strategy's opinion on one symbol at one point in time."""

    action: Action
    strength: float  # 0..1 confidence
    reason: str
    strategy: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Position:
    """An open holding, aggregated per symbol (average-cost basis)."""

    symbol: str
    quantity: float
    avg_cost: float
    opened_on: str = ""
    strategy: str = ""
    peak_price: float = 0.0  # highest price seen while held (for trailing stop)

    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_cost) * self.quantity

    def return_pct(self, price: float) -> float:
        if self.avg_cost <= 0:
            return 0.0
        return (price - self.avg_cost) / self.avg_cost

    def to_dict(self, price: float | None = None) -> dict[str, Any]:
        d = asdict(self)
        if price is not None:
            d["price"] = round(price, 6)
            d["market_value"] = round(self.market_value(price), 2)
            d["unrealized_pnl"] = round(self.unrealized_pnl(price), 2)
            d["return_pct"] = round(self.return_pct(price) * 100, 2)
        return d


@dataclass
class Fill:
    """A completed paper trade."""

    date: str
    symbol: str
    side: Action
    quantity: float
    price: float
    notional: float
    strategy: str = ""
    reason: str = ""
    realized_pnl: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BotConfig:
    """Trading rules for the bot. Defaults encode the user's brief:

    start $10k, aim to double in ~1 month, take profit at +30%, cut losers at a
    stop loss, and rebalance half of realized profits into a lower-risk holding.
    """

    starting_cash: float = 10_000.0
    goal_multiple: float = 2.0
    horizon_days: int = 30
    take_profit_pct: float = 0.30
    stop_loss_pct: float = 0.15
    max_position_pct: float = 0.25  # cap any one position at 25% of equity
    rebalance_profit_pct: float = 0.50  # move 50% of realized gains to reserve
    safe_symbol: str = "BIL"  # 1-3 month T-bill ETF proxy for the reserve
    universe: list[str] = field(
        default_factory=lambda: ["NVDA", "TSLA", "AMD", "AAPL", "MSFT", "BTC", "ETH", "SOL"]
    )
    strategies: list[str] = field(
        default_factory=lambda: ["momentum", "price_history", "mean_reversion"]
    )

    # --- trading frictions (realism) --------------------------------------
    fee_bps: float = 10.0  # commission/spread per trade, in basis points (0.10%)
    slippage_bps: float = 5.0  # adverse fill vs. close, in basis points (0.05%)

    # --- portfolio construction -------------------------------------------
    # "per_symbol": trade each name on its own blended signal (original behavior).
    # "cross_sectional": rank the universe by momentum, hold the top N (long-only).
    # "long_short": long the top N and short the bottom N (market-neutral).
    selection_mode: str = "per_symbol"
    top_n_positions: int = 3  # names held per side (both long and short legs)
    regime_ma: int = 0  # >0: only hold names above this moving average (trend filter)
    vol_target: float = 0.0  # >0: size inversely to volatility toward this annual vol
    vol_window: int = 20  # lookback for the volatility estimate
    borrow_bps: float = 5.0  # per-bar borrow cost charged on short notional
    rebalance_every: int = 1  # rebalance/rotate only every N bars (1 = daily)

    # --- tunable knobs (optimizer searches over these) --------------------
    trailing_stop_pct: float = 0.0  # >0 lets winners run: exit on drop from peak
    allow_add_ons: bool = False  # pyramid into winners up to the position cap
    min_signal_strength: float = 0.0  # ignore weak blended buy signals
    # strategy internals
    momentum_lookback: int = 10
    momentum_threshold: float = 0.03
    sma_short: int = 5
    sma_long: int = 20
    mr_window: int = 20
    mr_z: float = 1.0
    # per-strategy vote weights in the blend
    weights: dict[str, float] = field(
        default_factory=lambda: {"momentum": 1.0, "price_history": 1.0, "mean_reversion": 1.0}
    )

    def goal_equity(self) -> float:
        return self.starting_cash * self.goal_multiple

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["goal_equity"] = self.goal_equity()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> BotConfig:
        data = data or {}
        base = cls()

        def num(key: str, default: float, cast: Any = float) -> Any:
            val = data.get(key)
            return cast(val) if val is not None else default

        weights = data.get("weights")
        return cls(
            starting_cash=num("starting_cash", base.starting_cash),
            goal_multiple=num("goal_multiple", base.goal_multiple),
            horizon_days=num("horizon_days", base.horizon_days, int),
            take_profit_pct=num("take_profit_pct", base.take_profit_pct),
            stop_loss_pct=num("stop_loss_pct", base.stop_loss_pct),
            max_position_pct=num("max_position_pct", base.max_position_pct),
            rebalance_profit_pct=num("rebalance_profit_pct", base.rebalance_profit_pct),
            safe_symbol=str(data.get("safe_symbol") or base.safe_symbol),
            universe=list(data.get("universe") or base.universe),
            strategies=list(data.get("strategies") or base.strategies),
            fee_bps=num("fee_bps", base.fee_bps),
            slippage_bps=num("slippage_bps", base.slippage_bps),
            selection_mode=str(data.get("selection_mode") or base.selection_mode),
            top_n_positions=num("top_n_positions", base.top_n_positions, int),
            regime_ma=num("regime_ma", base.regime_ma, int),
            vol_target=num("vol_target", base.vol_target),
            vol_window=num("vol_window", base.vol_window, int),
            borrow_bps=num("borrow_bps", base.borrow_bps),
            rebalance_every=num("rebalance_every", base.rebalance_every, int),
            trailing_stop_pct=num("trailing_stop_pct", base.trailing_stop_pct),
            allow_add_ons=bool(
                data["allow_add_ons"]
                if data.get("allow_add_ons") is not None
                else base.allow_add_ons
            ),
            min_signal_strength=num("min_signal_strength", base.min_signal_strength),
            momentum_lookback=num("momentum_lookback", base.momentum_lookback, int),
            momentum_threshold=num("momentum_threshold", base.momentum_threshold),
            sma_short=num("sma_short", base.sma_short, int),
            sma_long=num("sma_long", base.sma_long, int),
            mr_window=num("mr_window", base.mr_window, int),
            mr_z=num("mr_z", base.mr_z),
            weights=(
                {str(k): float(v) for k, v in weights.items()}
                if weights
                else dict(base.weights)
            ),
        )
