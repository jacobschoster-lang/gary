"""Local JSON persistence for transcripts and published videos.

Survives server restarts. Path is configurable via ``GARY_CONTENT_FILE``.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from gary.agents.publisher_agent import PublishedVideo

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.environ.get("GARY_CONTENT_FILE", "finance_data/content.json")
_VIDEO_KEYS = ("video_id", "title", "kind", "url", "published_at")


class ContentStoreError(RuntimeError):
    """Raised when the store cannot be read or written safely."""


class ContentStore:
    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self.path = Path(path)
        self._load_failed = False

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            self._load_failed = False
            return {"transcripts": [], "videos": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            self._load_failed = True
            logger.warning("content store JSON corrupt (%s): %s", self.path, exc)
            return {"transcripts": [], "videos": []}
        except OSError as exc:
            self._load_failed = True
            logger.warning("content store unreadable (%s): %s", self.path, exc)
            return {"transcripts": [], "videos": []}
        self._load_failed = False
        return {
            "transcripts": list(data.get("transcripts") or []),
            "videos": list(data.get("videos") or []),
        }

    def _write(self, data: dict[str, Any]) -> None:
        if self._load_failed:
            raise ContentStoreError(
                f"refusing to write content store; fix or delete corrupt file: {self.path}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = json.dumps(
            {"transcripts": data["transcripts"], "videos": data["videos"]},
            indent=2,
        )
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)

    def transcripts(self) -> list[dict[str, Any]]:
        return self._read()["transcripts"]

    def add_transcript(self, record: dict[str, Any], limit: int = 50) -> None:
        data = self._read()
        key = record.get("created_at")
        if key:
            kept = [t for t in data["transcripts"] if t.get("created_at") != key]
        else:
            kept = data["transcripts"]
        data["transcripts"] = [record, *kept][:limit]
        self._write(data)

    def _parse_video(self, raw: dict[str, Any]) -> PublishedVideo | None:
        if not all(k in raw for k in _VIDEO_KEYS):
            logger.warning("skipping malformed video record: %s", raw)
            return None
        try:
            return PublishedVideo(**{k: raw[k] for k in _VIDEO_KEYS})
        except (TypeError, ValueError) as exc:
            logger.warning("skipping invalid video record: %s", exc)
            return None

    def videos(self) -> list[PublishedVideo]:
        parsed: list[PublishedVideo] = []
        for raw in self._read()["videos"]:
            video = self._parse_video(raw)
            if video is not None:
                parsed.append(video)
        return parsed

    def add_video(self, video: PublishedVideo, limit: int = 100) -> None:
        data = self._read()
        rows = [
            video.to_dict(),
            *[v for v in data["videos"] if v.get("video_id") != video.video_id],
        ]
        data["videos"] = rows[:limit]
        self._write(data)

    def save_pipeline_result(
        self,
        transcript: dict[str, Any],
        video: PublishedVideo,
        *,
        transcript_limit: int = 50,
        video_limit: int = 100,
    ) -> None:
        """Atomically persist a pipeline transcript + published video."""
        data = self._read()
        key = transcript.get("created_at")
        if key:
            transcripts = [
                transcript,
                *[t for t in data["transcripts"] if t.get("created_at") != key],
            ]
        else:
            transcripts = [transcript, *data["transcripts"]]
        videos = [
            video.to_dict(),
            *[v for v in data["videos"] if v.get("video_id") != video.video_id],
        ]
        data["transcripts"] = transcripts[:transcript_limit]
        data["videos"] = videos[:video_limit]
        self._write(data)

    def hydrate_publisher(self, publisher: Any) -> None:
        for video in self.videos():
            publisher._videos[video.video_id] = video
