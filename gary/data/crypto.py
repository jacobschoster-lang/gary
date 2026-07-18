"""Live crypto trends via the CoinGecko public API (issue #3)."""

from __future__ import annotations

from gary.agents.trends_agent import Trend
from gary.data import http

_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"


def fetch_crypto_trends(limit: int = 5) -> list[Trend] | None:
    """Top coins by market cap, scored by 24h momentum. None on failure."""
    data = http.get_json(
        _MARKETS_URL,
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": max(limit + 3, 8),
            "page": 1,
            "price_change_percentage": "24h",
        },
    )
    if not isinstance(data, list) or not data:
        return None

    trends: list[Trend] = []
    for coin in data:
        symbol = str(coin.get("symbol", "")).upper()
        name = coin.get("name")
        if not symbol or not name:
            continue
        # Skip stablecoins — not interesting for "trending".
        if symbol in {"USDT", "USDC", "DAI", "BUSD", "TUSD", "FDUSD"}:
            continue
        change = coin.get("price_change_percentage_24h") or 0.0
        price = coin.get("current_price")
        # Momentum score: base on absolute 24h move, capped to a 0-100-ish range.
        score = round(min(99.9, 50 + change * 2), 1)
        note = f"{change:+.1f}% 24h @ ${price:,}" if price is not None else f"{change:+.1f}% 24h"
        trends.append(Trend(symbol=symbol, name=name, market="crypto", score=score, note=note))
        if len(trends) >= limit:
            break

    return trends or None
