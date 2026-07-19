"""Live stock trends via the Yahoo Finance chart API (issue #2).

No API key required. We poll a small watchlist and rank by absolute daily move.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from gary.agents.trends_agent import Trend
from gary.data import http

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

_WATCHLIST = {
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "TSLA": "Tesla",
    "MSFT": "Microsoft",
    "AMD": "Advanced Micro Devices",
    "AMZN": "Amazon",
    "GOOGL": "Alphabet",
    "META": "Meta Platforms",
}


def _quote(symbol: str) -> tuple[float, float] | None:
    data = http.get_json(_CHART_URL.format(symbol=symbol), params={"range": "1d", "interval": "1d"})
    try:
        meta = data["chart"]["result"][0]["meta"]
    except (TypeError, KeyError, IndexError):
        return None
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if price is None or not prev:
        return None
    change_pct = (price - prev) / prev * 100
    return float(price), float(change_pct)


def fetch_stock_trends(limit: int = 5) -> list[Trend] | None:
    """Watchlist quotes ranked by absolute daily move. None on failure.

    Quotes are fetched concurrently (I/O-bound network calls) to keep the
    dashboard's cold load fast.
    """
    symbols = list(_WATCHLIST.items())
    with ThreadPoolExecutor(max_workers=len(symbols)) as ex:
        quotes = list(ex.map(lambda sn: (sn[0], sn[1], _quote(sn[0])), symbols))

    trends: list[Trend] = []
    for symbol, name, quote in quotes:
        if quote is None:
            continue
        price, change = quote
        score = round(min(99.9, 50 + abs(change) * 4), 1)
        note = f"{change:+.1f}% today @ ${price:,.2f}"
        trends.append(Trend(symbol=symbol, name=name, market="stocks", score=score, note=note))

    if not trends:
        return None
    trends.sort(key=lambda t: t.score, reverse=True)
    return trends[:limit]
