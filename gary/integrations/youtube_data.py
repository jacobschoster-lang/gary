"""YouTube Data API helpers for trends and public video statistics.

Uses ``YOUTUBE_API_KEY`` (API key only — no OAuth required for public reads).
Falls back gracefully when the key is absent or the API errors.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from gary.data.http import get_json

_API = "https://www.googleapis.com/youtube/v3"


def api_key(env: dict[str, str] | None = None) -> str | None:
    env = env if env is not None else dict(os.environ)
    return env.get("YOUTUBE_API_KEY")


def fetch_finance_topics(
    limit: int = 5, env: dict[str, str] | None = None
) -> list[dict[str, Any]] | None:
    """Return trending finance video topics from YouTube search, or None."""
    key = api_key(env)
    if not key:
        return None

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=7)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = get_json(
        f"{_API}/search",
        params={
            "part": "snippet",
            "q": "finance investing stocks crypto money",
            "type": "video",
            "order": "viewCount",
            "publishedAfter": published_after,
            "maxResults": min(max(limit * 2, 5), 25),
            "key": key,
        },
    )
    if not data or not isinstance(data.get("items"), list):
        return None

    topics: list[dict[str, Any]] = []
    for item in data["items"]:
        snippet = item.get("snippet") or {}
        title = (snippet.get("title") or "").strip()
        channel = (snippet.get("channelTitle") or "").strip()
        video_id = (item.get("id") or {}).get("videoId")
        if not title:
            continue
        topics.append(
            {
                "title": title,
                "channel": channel or "YouTube",
                "views": 0,
                "velocity": float(len(topics) + 1) * 1000.0,
                "video_id": video_id,
            }
        )
        if len(topics) >= limit:
            break
    return topics or None


def fetch_video_statistics(
    video_id: str, env: dict[str, str] | None = None
) -> dict[str, Any] | None:
    """Return public view/like/comment counts for a YouTube video, or None."""
    key = api_key(env)
    if not key or not video_id:
        return None

    data = get_json(
        f"{_API}/videos",
        params={"part": "statistics", "id": video_id, "key": key},
    )
    if not data or not data.get("items"):
        return None

    stats = data["items"][0].get("statistics") or {}
    try:
        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))
    except (TypeError, ValueError):
        return None

    return {
        "video_id": video_id,
        "views": views,
        "likes": likes,
        "comments": comments,
        "ctr_percent": None,
        "source": "youtube",
    }
