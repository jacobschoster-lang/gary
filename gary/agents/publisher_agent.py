"""Publisher agent (issue #6).

Handles the post-production side: uploading videos, drafting comment replies,
and tracking per-video performance. Uses the YouTube Data API when
``YOUTUBE_API_KEY`` is set; otherwise metrics are deterministic samples.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from gary.agents import llm
from gary.integrations.youtube_data import fetch_video_statistics


@dataclass
class PublishedVideo:
    video_id: str
    title: str
    kind: str
    url: str
    published_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Publisher:
    _videos: dict[str, PublishedVideo] = field(default_factory=dict)

    def upload(self, title: str, kind: str = "long") -> PublishedVideo:
        title = (title or "").strip()
        if not title:
            raise ValueError("title must not be empty")

        seed = f"{title}|{kind}|{datetime.now(timezone.utc).isoformat()}"
        video_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:11]
        video = PublishedVideo(
            video_id=video_id,
            title=title,
            kind=kind,
            url=f"https://youtu.be/{video_id}",
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        self._videos[video_id] = video
        return video

    def register(self, video_id: str, title: str, kind: str, url: str) -> PublishedVideo:
        """Register a real uploaded video (e.g. from YouTube OAuth upload)."""
        video = PublishedVideo(
            video_id=video_id,
            title=title,
            kind=kind,
            url=url,
            published_at=datetime.now(timezone.utc).isoformat(),
        )
        self._videos[video_id] = video
        return video

    def videos(self) -> list[PublishedVideo]:
        return list(self._videos.values())

    def manage_comments(
        self, video_id: str, comments: list[str], top_n: int = 10
    ) -> list[dict[str, str]]:
        if video_id not in self._videos:
            raise KeyError(f"unknown video_id: {video_id}")
        replies: list[dict[str, str]] = []
        for comment in comments[:top_n]:
            replies.append({"comment": comment, "reply": self._draft_reply(comment)})
        return replies

    def track(self, video_id: str) -> dict[str, Any]:
        if video_id not in self._videos:
            raise KeyError(f"unknown video_id: {video_id}")

        live = fetch_video_statistics(video_id)
        if live is not None:
            return live

        digest = hashlib.sha256(video_id.encode("utf-8")).digest()
        views = 1000 + digest[0] * 137
        likes = int(views * (0.03 + digest[1] / 5000))
        comments = int(views * 0.004)
        ctr = round(3 + digest[2] / 40, 1)
        return {
            "video_id": video_id,
            "views": views,
            "likes": likes,
            "comments": comments,
            "ctr_percent": ctr,
            "source": "sample",
        }

    def _draft_reply(self, comment: str) -> str:
        reply = llm.draft_comment_reply(comment, env=dict(os.environ))
        if reply:
            return reply
        return (
            "Great point — thanks for watching! We'll dig into that in an "
            "upcoming video. Not financial advice."
        )
