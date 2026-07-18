"""Live data backends (crypto, stocks, news) with graceful fallback.

Every fetcher returns ``None`` (never raises) on network/parse failure so the
agents can fall back to their deterministic stubs and the app stays runnable
offline.
"""

from gary.data.crypto import fetch_crypto_trends
from gary.data.news import fetch_headlines
from gary.data.stocks import fetch_stock_trends

__all__ = ["fetch_crypto_trends", "fetch_stock_trends", "fetch_headlines"]
