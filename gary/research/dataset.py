"""Cached, split/dividend-adjusted price dataset for the research harness.

The free chart API throttles rapid multi-year pulls, so research on live data was
unreliable and irreproducible. This layer:

  - fetches **adjusted** closes (split/dividend-adjusted) over an explicit
    ``period1/period2`` window (more reliable than the ``range`` param),
  - **caches** each symbol to disk (``finance_data/price_cache/``, gitignored) so
    subsequent runs are reproducible and don't re-hammer the API,
  - fetches **politely** (a throttle delay + bounded retries),
  - falls back to the deterministic synthetic series offline,
  - and returns a **coverage report** (per-symbol bars + source) so callers can
    see how much real history they actually got.

Residual limitation: symbols are today's listed names (survivorship bias). A
truly clean test needs point-in-time index membership incl. delisted names, which
the free data here doesn't provide — callers should keep saying so.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from gary.data import http
from gary.trading import prices as price_data

_YF_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
Fetcher = Callable[[str, int], list[float] | None]


def fetch_yahoo_adjusted(symbol: str, days: int) -> list[float] | None:
    """Adjusted daily closes over the last ~``days`` trading days via period1/period2."""
    now = int(time.time())
    # ~1.5 calendar days per trading day, plus a buffer, so we actually cover `days`.
    start = now - int((days + 10) * 1.5 * 86400)
    data = http.get_json(_YF_CHART.format(symbol=symbol), params={
        "period1": start, "period2": now, "interval": "1d", "events": "div,splits",
    })
    try:
        result = data["chart"]["result"][0]
        indicators = result["indicators"]
        adj = indicators.get("adjclose", [{}])[0].get("adjclose")
        raw = indicators["quote"][0]["close"]
        series = adj if adj else raw
        closes = [float(c) for c in series if c is not None]
    except (TypeError, KeyError, IndexError):
        return None
    return closes or None


class PriceCache:
    """Per-symbol on-disk cache of adjusted closes (JSON, gitignored)."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.dir = Path(directory or os.environ.get(
            "GARY_PRICE_CACHE", "finance_data/price_cache"))

    def _path(self, symbol: str) -> Path:
        return self.dir / f"{symbol.upper()}.json"

    def load(self, symbol: str, max_age_days: float = 1.0) -> list[float] | None:
        p = self._path(symbol)
        if not p.exists():
            return None
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if (time.time() - rec.get("fetched_at", 0)) > max_age_days * 86400:
            return None  # stale
        closes = rec.get("closes") or []
        return [float(c) for c in closes] or None

    def save(self, symbol: str, closes: list[float]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._path(symbol).write_text(
            json.dumps({"symbol": symbol.upper(), "fetched_at": time.time(),
                        "bars": len(closes), "closes": closes}),
            encoding="utf-8",
        )

    def stale(self, symbol: str) -> list[float] | None:
        """Return cached closes ignoring age (last-resort fallback)."""
        return self.load(symbol, max_age_days=1e9)


def load_panel(
    universe: list[str],
    days: int,
    use_live: bool = True,
    cache: PriceCache | None = None,
    fetcher: Fetcher | None = None,
    throttle: float = 0.25,
    retries: int = 2,
    max_age_days: float = 1.0,
) -> tuple[dict[str, list[float]], dict[str, Any]]:
    """Return (panel, coverage). Offline uses the deterministic synthetic series;
    live uses cache-then-fetch (adjusted), politely, with a synthetic last resort."""
    panel: dict[str, list[float]] = {}
    per_symbol: dict[str, dict[str, Any]] = {}
    counts = {"cache": 0, "live": 0, "synthetic": 0, "stale_cache": 0}

    if not use_live:  # deterministic, reproducible, no network
        for sym in universe:
            panel[sym] = price_data.price_series(sym, days, use_live=False)
            per_symbol[sym] = {"bars": len(panel[sym]), "source": "synthetic"}
            counts["synthetic"] += 1
        return panel, {"symbols": per_symbol, "sources": counts, "live": False}

    cache = cache or PriceCache()
    fetcher = fetcher or fetch_yahoo_adjusted
    for sym in universe:
        closes = cache.load(sym, max_age_days=max_age_days)
        source = "cache"
        if not closes:
            for attempt in range(retries + 1):
                closes = fetcher(sym, days)
                if closes and len(closes) >= 30:
                    cache.save(sym, closes)
                    source = "live"
                    break
                time.sleep(throttle * (attempt + 1))  # back off politely
            if not closes:
                closes = cache.stale(sym)
                source = "stale_cache" if closes else "synthetic"
        if not closes:
            closes = price_data.price_series(sym, days, use_live=False)
            source = "synthetic"
        panel[sym] = closes
        per_symbol[sym] = {"bars": len(closes), "source": source}
        counts[source] = counts.get(source, 0) + 1
        if source == "live":
            time.sleep(throttle)  # be polite between real requests
    return panel, {"symbols": per_symbol, "sources": counts, "live": True}
