"""Live stock trends via the Yahoo Finance chart API (issue #2).

No API key required. We poll watchlists and rank by absolute daily move.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from gary.agents.trends_agent import Market, Trend
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

_QUANTUM_WATCHLIST = {
    "IONQ": "IonQ",
    "RGTI": "Rigetti Computing",
    "QBTS": "D-Wave Quantum",
    "QUBT": "Quantum Computing Inc",
    "IBM": "IBM",
    "GOOGL": "Alphabet",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
}


def _quote(symbol: str) -> tuple[float, float] | None:
    data = http.get_json(_CHART_URL.format(symbol=symbol), params={"range": "5d", "interval": "1d"})
    try:
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) >= 2:
            price, prev = closes[-1], closes[-2]
        else:
            meta = result["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if price is None or not prev:
            return None
        change_pct = (price - prev) / prev * 100
        return float(price), float(change_pct)
    except (TypeError, KeyError, IndexError):
        return None


def _fetch_watchlist_trends(
    watchlist: dict[str, str],
    market: Market,
    limit: int = 5,
) -> list[Trend] | None:
    symbols = list(watchlist.items())
    with ThreadPoolExecutor(max_workers=len(symbols)) as ex:
        quotes = list(ex.map(lambda sn: (sn[0], sn[1], _quote(sn[0])), symbols))

    trends: list[Trend] = []
    for symbol, name, quote in quotes:
        if quote is None:
            continue
        price, change = quote
        score = round(min(99.9, 50 + abs(change) * 4), 1)
        note = f"{change:+.1f}% today @ ${price:,.2f}"
        trends.append(Trend(symbol=symbol, name=name, market=market, score=score, note=note))

    if not trends:
        return None
    trends.sort(key=lambda t: t.score, reverse=True)
    return trends[:limit]


def fetch_stock_trends(limit: int = 5) -> list[Trend] | None:
    """Mega-cap watchlist quotes ranked by absolute daily move."""
    return _fetch_watchlist_trends(_WATCHLIST, "stocks", limit)


def fetch_quantum_trends(limit: int = 5) -> list[Trend] | None:
    """Quantum computing watchlist quotes ranked by absolute daily move."""
    return _fetch_watchlist_trends(_QUANTUM_WATCHLIST, "quantum", limit)
