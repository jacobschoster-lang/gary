"""Daily price-history provider for the trading bot.

Tries free public APIs (Yahoo Finance for equities, CoinGecko for crypto) via the
shared cached HTTP helper, and falls back to a *deterministic* synthetic price
series when offline. The synthetic path is seeded per symbol so simulations and
tests are reproducible, and it keeps the bot fully runnable without network.
"""

from __future__ import annotations

import math
import random

from gary.data import http

_YF_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_CG_CHART = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"

# Crypto tickers -> CoinGecko ids.
_CG_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "XRP": "ripple",
    "LINK": "chainlink",
    "ARB": "arbitrum",
    "DOGE": "dogecoin",
    "ADA": "cardano",
}

# Rough anchor prices + annualized vol for the synthetic fallback (per symbol).
_SEED_PRICES = {
    "NVDA": 120.0, "TSLA": 250.0, "AMD": 160.0, "AAPL": 220.0, "MSFT": 420.0,
    "AMZN": 185.0, "GOOGL": 175.0, "META": 520.0, "IONQ": 30.0, "RGTI": 12.0,
    "BTC": 66000.0, "ETH": 3200.0, "SOL": 170.0, "XRP": 1.15, "LINK": 18.0,
    "ARB": 1.1, "DOGE": 0.16, "ADA": 0.9, "BIL": 91.5,
}


def is_crypto(symbol: str) -> bool:
    return symbol.upper() in _CG_IDS


def _fetch_yahoo(symbol: str, days: int) -> list[float] | None:
    rng = "6mo" if days <= 120 else "1y"
    data = http.get_json(_YF_CHART.format(symbol=symbol), params={"range": rng, "interval": "1d"})
    try:
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
    except (TypeError, KeyError, IndexError):
        return None
    return [float(c) for c in closes] or None


def _fetch_coingecko(symbol: str, days: int) -> list[float] | None:
    cg_id = _CG_IDS.get(symbol.upper())
    if not cg_id:
        return None
    data = http.get_json(
        _CG_CHART.format(id=cg_id),
        params={"vs_currency": "usd", "days": max(days, 30), "interval": "daily"},
    )
    try:
        prices = [float(p[1]) for p in data["prices"]]
    except (TypeError, KeyError, IndexError):
        return None
    return prices or None


def _synthetic(symbol: str, days: int) -> list[float]:
    """Deterministic geometric random walk with mild upward drift + volatility."""
    sym = symbol.upper()
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(sym))
    rng = random.Random(seed)
    price = _SEED_PRICES.get(sym, 100.0)
    # Safe reserve asset barely moves; risk assets are more volatile.
    if sym == "BIL":
        drift, vol = 0.00008, 0.0008
    elif is_crypto(sym):
        drift, vol = 0.0016, 0.045
    else:
        drift, vol = 0.0009, 0.022
    n = max(days, 60)  # always give strategies enough warmup history
    series = [price]
    for _ in range(n - 1):
        shock = rng.gauss(drift, vol)
        price = max(0.01, price * (1 + shock))
        series.append(round(price, 6))
    return series


def price_series(symbol: str, days: int = 90, use_live: bool = True) -> list[float]:
    """Return daily closes (oldest -> newest). Never raises; falls back to synthetic."""
    if use_live:
        live = _fetch_coingecko(symbol, days) if is_crypto(symbol) else _fetch_yahoo(symbol, days)
        if live and len(live) >= 30:
            return live
    return _synthetic(symbol, days)


def latest_prices(symbols: list[str], use_live: bool = True) -> dict[str, float]:
    return {s: price_series(s, 60, use_live=use_live)[-1] for s in symbols}


def annualized_return(series: list[float]) -> float:
    if len(series) < 2 or series[0] <= 0:
        return 0.0
    total = series[-1] / series[0]
    years = len(series) / 252.0
    if years <= 0:
        return 0.0
    return math.pow(total, 1 / years) - 1
