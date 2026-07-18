"""Video agent (issue #4).

Turns a transcript into a production plan for a daily long-form video (~10 min)
and a daily YouTube Short (~45s). The plan is deterministic scaffolding: it maps
transcript sections to timed segments and adds b-roll / caption cues. Swap
``_broll_for`` and the rendering hooks for a real video-generation backend.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from gary.agents.transcript_agent import Transcript

VideoKind = Literal["long", "short"]

_TARGET_SECONDS: dict[VideoKind, int] = {"long": 600, "short": 45}


@dataclass
class Segment:
    heading: str
    script: str
    start_s: int
    duration_s: int
    broll: str


@dataclass
class VideoPlan:
    topic: str
    kind: VideoKind
    target_seconds: int
    total_seconds: int
    segments: list[Segment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "kind": self.kind,
            "target_seconds": self.target_seconds,
            "total_seconds": self.total_seconds,
            "segments": [asdict(s) for s in self.segments],
        }


@dataclass
class VideoAgent:
    words_per_second: float = 2.5  # ~150 wpm narration

    def build(self, transcript: Transcript, kind: VideoKind = "long") -> VideoPlan:
        if kind not in _TARGET_SECONDS:
            raise ValueError(f"unknown video kind: {kind!r}")

        sections = transcript.sections
        if kind == "short":
            # Shorts keep only the hook + call to action for punchiness.
            sections = [s for s in sections if s["heading"] in ("Hook", "Call To Action")]

        segments: list[Segment] = []
        cursor = 0
        for s in sections:
            duration = max(3, round(len(s["script"].split()) / self.words_per_second))
            segments.append(
                Segment(
                    heading=s["heading"],
                    script=s["script"],
                    start_s=cursor,
                    duration_s=duration,
                    broll=self._broll_for(s["heading"]),
                )
            )
            cursor += duration

        return VideoPlan(
            topic=transcript.topic,
            kind=kind,
            target_seconds=_TARGET_SECONDS[kind],
            total_seconds=cursor,
            segments=segments,
        )

    def _broll_for(self, heading: str) -> str:
        # NOTE: replace with a real asset/stock-footage lookup.
        return {
            "Hook": "fast market ticker montage",
            "The Data": "animated chart overlays",
            "Analysis": "host on camera with lower-thirds",
            "Call To Action": "subscribe animation + end screen",
        }.get(heading, "generic finance b-roll")
