"""Trends agent (issues #2 and #3).

Surfaces trending stocks and crypto assets that feed the transcript and video
pipelines. The current implementation returns a deterministic sample set so the
platform is runnable offline. Replace ``_fetch`` with real scrapers / market
data API calls (e.g. YouTube, stock, and DeFi sources).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

Market = Literal["stocks", "crypto"]


@dataclass
class Trend:
    symbol: str
    name: str
    market: Market
    score: float
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TrendsAgent:
    """Returns ranked trending assets per market."""

    def top(self, market: Market, limit: int = 5) -> list[Trend]:
        if market not in ("stocks", "crypto"):
            raise ValueError(f"unknown market: {market!r}")
        if limit < 1:
            raise ValueError("limit must be >= 1")

        trends = self._fetch(market)
        trends.sort(key=lambda t: t.score, reverse=True)
        return trends[:limit]

    def _fetch(self, market: Market) -> list[Trend]:
        # NOTE: replace with real scrapers / market-data APIs.
        if market == "stocks":
            return [
                Trend("NVDA", "NVIDIA", "stocks", 94.2, "AI demand momentum"),
                Trend("AAPL", "Apple", "stocks", 81.0, "Services growth"),
                Trend("TSLA", "Tesla", "stocks", 88.7, "High retail interest"),
                Trend("MSFT", "Microsoft", "stocks", 76.5, "Cloud strength"),
                Trend("AMD", "Advanced Micro Devices", "stocks", 79.9, "GPU cycle"),
            ]
        return [
            Trend("BTC", "Bitcoin", "crypto", 91.3, "ETF inflows"),
            Trend("ETH", "Ethereum", "crypto", 85.4, "Staking yield"),
            Trend("SOL", "Solana", "crypto", 89.1, "DeFi volume spike"),
            Trend("LINK", "Chainlink", "crypto", 72.8, "Oracle adoption"),
            Trend("ARB", "Arbitrum", "crypto", 70.2, "L2 TVL growth"),
        ]
