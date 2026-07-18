"""Small cached HTTP helpers used by the live data backends.

Uses httpx with short timeouts and a tiny in-process TTL cache so we are polite
to the free public APIs (CoinGecko, Yahoo, Google News) and never block the app
for long. All helpers return ``None`` on any failure instead of raising.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

USER_AGENT = "gary-finance/0.1 (+https://github.com/jacobschoster-lang/gary)"
DEFAULT_TIMEOUT = 8.0
_CACHE_TTL = 60.0

_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit and (time.time() - hit[0]) < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


def get_json(url: str, params: dict[str, Any] | None = None) -> Any | None:
    key = f"json:{url}:{sorted((params or {}).items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = httpx.get(
            url,
            params=params,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    _cache_put(key, data)
    return data


def get_text(url: str, params: dict[str, Any] | None = None) -> str | None:
    key = f"text:{url}:{sorted((params or {}).items())}"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        resp = httpx.get(
            url,
            params=params,
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        text = resp.text
    except Exception:
        return None
    _cache_put(key, text)
    return text


def clear_cache() -> None:
    _cache.clear()
