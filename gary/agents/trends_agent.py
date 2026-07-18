"""Trends agent (issues #2 and #3).

Surfaces trending stocks, crypto assets, and YouTube topics that feed the
transcript and video pipelines. The current implementation returns a
deterministic sample set so the platform is runnable offline. Replace ``_fetch``
and ``_fetch_youtube`` with real scrapers / market-data / YouTube API calls.
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
class YouTubeTopic:
    title: str
    channel: str
    views: int
    velocity: float  # views/hour momentum

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

    def youtube_topics(self, limit: int = 5) -> list[YouTubeTopic]:
        """Trending finance topics on YouTube (issue #2)."""
        if limit < 1:
            raise ValueError("limit must be >= 1")
        topics = self._fetch_youtube()
        topics.sort(key=lambda t: t.velocity, reverse=True)
        return topics[:limit]

    def _fetch_youtube(self) -> list[YouTubeTopic]:
        # NOTE: replace with real YouTube Data API / scraping.
        return [
            YouTubeTopic("Why the Fed pivot changes everything", "MacroDaily", 412_000, 9800.0),
            YouTubeTopic("Bitcoin to $100k? The real math", "CryptoEdge", 980_000, 15200.0),
            YouTubeTopic("3 AI stocks before earnings", "StockLab", 265_000, 7100.0),
            YouTubeTopic("The DeFi yield nobody talks about", "ChainAlpha", 154_000, 6400.0),
            YouTubeTopic("Recession 2026: what to buy now", "ValueVault", 523_000, 11200.0),
        ]
