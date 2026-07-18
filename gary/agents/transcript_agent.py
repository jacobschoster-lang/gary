"""Transcript agent (issue #1).

Generates a structured YouTube finance video transcript from a topic and an
optional set of data points. The current logic is deterministic and offline so
the platform runs without API keys; swap ``_draft_body`` for a real LLM call to
upgrade the output quality.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Transcript:
    topic: str
    title: str
    sections: list[dict[str, str]]
    word_count: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TranscriptAgent:
    """Turns a finance topic into a video-ready transcript."""

    channel_name: str = "gary finance"
    data_points: list[str] = field(default_factory=list)

    def generate(self, topic: str, data_points: list[str] | None = None) -> Transcript:
        topic = (topic or "").strip()
        if not topic:
            raise ValueError("topic must not be empty")

        points = data_points if data_points is not None else self.data_points
        sections = self._draft_body(topic, points)
        word_count = sum(len(s["script"].split()) for s in sections)

        return Transcript(
            topic=topic,
            title=self._title(topic),
            sections=sections,
            word_count=word_count,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def _title(self, topic: str) -> str:
        return f"{topic.title()}: What Every Investor Needs to Know Today"

    def _draft_body(self, topic: str, points: list[str]) -> list[dict[str, str]]:
        # NOTE: replace this deterministic scaffold with a real LLM call.
        intro = (
            f"Welcome back to {self.channel_name}. Today we are breaking down "
            f"{topic} and what it means for your money right now."
        )

        if points:
            evidence = " ".join(
                f"Data point {i + 1}: {p}." for i, p in enumerate(points)
            )
        else:
            evidence = (
                "We pulled the latest market signals so you do not have to. "
                "Here is the short version, followed by the details that matter."
            )

        analysis = (
            f"So what is actually driving {topic}? Three things: momentum, "
            "liquidity, and sentiment. When these line up, moves accelerate; "
            "when they diverge, expect volatility."
        )
        outro = (
            "If this helped, subscribe for daily finance breakdowns. "
            "This is not financial advice. See you in the next one."
        )

        return [
            {"heading": "Hook", "script": intro},
            {"heading": "The Data", "script": evidence},
            {"heading": "Analysis", "script": analysis},
            {"heading": "Call To Action", "script": outro},
        ]
