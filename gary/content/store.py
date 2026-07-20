"""Local JSON persistence for transcripts and published videos.

Survives server restarts. Path is configurable via ``GARY_CONTENT_FILE``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from gary.agents.publisher_agent import PublishedVideo

_DEFAULT_PATH = os.environ.get("GARY_CONTENT_FILE", "finance_data/content.json")


class ContentStore:
    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self.path = Path(path)

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"transcripts": [], "videos": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"transcripts": [], "videos": []}
        return {
            "transcripts": list(data.get("transcripts") or []),
            "videos": list(data.get("videos") or []),
        }

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def transcripts(self) -> list[dict[str, Any]]:
        return self._read()["transcripts"]

    def add_transcript(self, record: dict[str, Any], limit: int = 50) -> None:
        data = self._read()
        rows = [record, *[t for t in data["transcripts"] if t.get("title") != record.get("title")]]
        data["transcripts"] = rows[:limit]
        self._write(data)

    def videos(self) -> list[PublishedVideo]:
        return [PublishedVideo(**v) for v in self._read()["videos"]]

    def add_video(self, video: PublishedVideo, limit: int = 100) -> None:
        data = self._read()
        rows = [
            video.to_dict(),
            *[v for v in data["videos"] if v.get("video_id") != video.video_id],
        ]
        data["videos"] = rows[:limit]
        self._write(data)

    def hydrate_publisher(self, publisher: Any) -> None:
        for video in self.videos():
            publisher._videos[video.video_id] = video
