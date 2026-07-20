"""Disk cache for rendered story preview MP4s."""

from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

_CACHE_ROOT = Path(os.environ.get("GARY_PREVIEW_CACHE", tempfile.gettempdir())) / "gary_previews"


def _cache_path(topic: str, voice: bool) -> Path:
    digest = hashlib.sha256(f"{topic.strip()}|voice={voice}".encode()).hexdigest()[:20]
    return _CACHE_ROOT / f"{digest}.mp4"


def get_or_render(
    topic: str,
    voice: bool,
    plan_factory: Callable[[str], dict[str, Any]],
    render_fn: Callable[..., str],
    *,
    fps: int = 10,
    seconds_per_scene: float = 2.5,
) -> Path:
    """Return a cached preview MP4 path, rendering on first request."""
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic must not be empty")

    path = _cache_path(topic, voice)
    if path.exists() and path.stat().st_size > 0:
        return path

    _CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    plan = plan_factory(topic)
    render_fn(
        plan,
        out_path=str(path),
        fps=fps,
        seconds_per_scene=seconds_per_scene,
        voiceover=voice,
    )
    return path


def clear() -> None:
    if _CACHE_ROOT.exists():
        for item in _CACHE_ROOT.glob("*.mp4"):
            item.unlink(missing_ok=True)
