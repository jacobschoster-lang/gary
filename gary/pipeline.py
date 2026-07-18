"""Daily content pipeline.

Chains every agent into one runnable flow so the 7 issues have a working spine
to build on:

    trend (#2/#3) -> transcript (#1) -> long + short video plans (#4)
    -> thumbnail (#5) -> publish + track (#6) -> dashboard (#7)

Everything is deterministic/offline; each step delegates to an agent whose
internals are the real extension seams.
"""

from __future__ import annotations

from typing import Any

from gary.agents.publisher_agent import Publisher
from gary.agents.thumbnail_agent import ThumbnailAgent
from gary.agents.transcript_agent import TranscriptAgent
from gary.agents.trends_agent import TrendsAgent
from gary.agents.video_agent import VideoAgent


class ContentPipeline:
    def __init__(self, publisher: Publisher | None = None, use_live: bool = True) -> None:
        self.trends = TrendsAgent(use_live=use_live)
        self.transcripts = TranscriptAgent(use_live=use_live)
        self.videos = VideoAgent()
        self.thumbnails = ThumbnailAgent()
        self.publisher = publisher or Publisher()

    def run_daily(self, topic: str | None = None, market: str = "crypto") -> dict[str, Any]:
        """Produce a full day's content plan for one topic."""
        if not topic:
            top = self.trends.top(market, limit=1)  # type: ignore[arg-type]
            topic = f"{top[0].name} ({top[0].note})"

        transcript = self.transcripts.generate(topic)
        long_plan = self.videos.build(transcript, "long")
        short_plan = self.videos.build(transcript, "short")
        thumb = self.thumbnails.design(topic)
        published = self.publisher.upload(transcript.title, kind="long")
        metrics = self.publisher.track(published.video_id)

        return {
            "topic": topic,
            "transcript": transcript.to_dict(),
            "video_long": long_plan.to_dict(),
            "video_short": short_plan.to_dict(),
            "thumbnail": thumb.to_dict(),
            "published": published.to_dict(),
            "metrics": metrics,
        }
