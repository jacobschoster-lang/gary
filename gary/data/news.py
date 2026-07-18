"""Live finance headlines via Google News RSS (issue #1).

Used to ground generated transcripts in real, current internet data. No API key
required. Returns ``None`` on failure so callers fall back to generic copy.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from gary.data import http

_RSS_URL = "https://news.google.com/rss/search"


def fetch_headlines(query: str, limit: int = 5) -> list[str] | None:
    query = (query or "").strip()
    if not query:
        return None

    text = http.get_text(
        _RSS_URL,
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
    )
    if not text:
        return None

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    headlines: list[str] = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        if title_el is not None and title_el.text:
            headlines.append(title_el.text.strip())
        if len(headlines) >= limit:
            break

    return headlines or None
