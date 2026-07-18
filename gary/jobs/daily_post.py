"""Daily post job (issue #4 + #6).

Runs the content pipeline and publishes the result to YouTube. Designed to be
invoked by a scheduler (GitHub Actions) at 08:00 America/New_York.

Behavior:
  * Always runs the pipeline and builds the video metadata (title/description/tags).
  * If a rendered video file exists (``--video-file`` or ``GARY_VIDEO_FILE``) AND
    YouTube credentials are configured, it uploads.
  * Otherwise it performs a safe DRY RUN: writes a manifest JSON and skips upload.

CLI:
    python -m gary.jobs.daily_post [--topic "..."] [--video-file path.mp4]
                                   [--thumbnail path] [--out out/] [--force]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gary.integrations.youtube import YouTubeUploader
from gary.jobs.schedule import should_run_now
from gary.pipeline import ContentPipeline

CHANNEL_HANDLE = "@StickfigureFinance-r8m"


def build_description(plan: dict[str, Any]) -> str:
    transcript = plan["transcript"]
    body = "\n\n".join(f"{s['heading']}: {s['script']}" for s in transcript["sections"])
    tags = "#finance #investing #stocks #crypto #money"
    return (
        f"{transcript['title']}\n\n"
        f"{body}\n\n"
        "This video is for education/entertainment only and is not financial advice.\n\n"
        f"{tags}"
    )


def build_tags(plan: dict[str, Any]) -> list[str]:
    base = ["finance", "investing", "stocks", "crypto", "money", "markets"]
    topic_words = [w.strip("()").lower() for w in plan["topic"].split()][:4]
    return list(dict.fromkeys(base + topic_words))


def run(
    topic: str | None = None,
    video_file: str | None = None,
    thumbnail: str | None = None,
    out_dir: str = "out",
    force: bool = False,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    scheduled_ok = force or should_run_now(now_utc=now_utc)
    plan = ContentPipeline().run_daily(topic=topic)
    title = plan["transcript"]["title"]
    description = build_description(plan)
    tags = build_tags(plan)

    result: dict[str, Any] = {
        "channel": CHANNEL_HANDLE,
        "scheduled_ok": scheduled_ok,
        "title": title,
        "tags": tags,
        "uploaded": False,
        "dry_run": True,
        "reason": None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not scheduled_ok:
        result["reason"] = "not the scheduled 08:00 America/New_York hour (use --force to override)"
        _write_manifest(out_dir, plan, result)
        return result

    uploader = YouTubeUploader.from_env()
    video_file = video_file or os.environ.get("GARY_VIDEO_FILE")

    if uploader is None:
        result["reason"] = (
            "YouTube credentials not configured "
            "(YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN)"
        )
    elif not video_file:
        result["reason"] = "no rendered video file provided (--video-file / GARY_VIDEO_FILE)"
    else:
        upload = uploader.upload(
            video_path=video_file,
            title=title,
            description=description,
            tags=tags,
            thumbnail_path=thumbnail,
        )
        result.update(uploaded=True, dry_run=False, reason=None, **upload)

    _write_manifest(out_dir, plan, result)
    return result


def _write_manifest(out_dir: str, plan: dict[str, Any], result: dict[str, Any]) -> Path:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(out_dir) / f"daily_post_{stamp}.json"
    path.write_text(json.dumps({"result": result, "plan": plan}, indent=2), encoding="utf-8")
    result["manifest"] = str(path)
    return path


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="gary daily YouTube post")
    parser.add_argument("--topic", default=None)
    parser.add_argument("--video-file", default=None)
    parser.add_argument("--thumbnail", default=None)
    parser.add_argument("--out", default="out")
    parser.add_argument("--force", action="store_true", help="ignore the 08:00 ET schedule guard")
    args = parser.parse_args(argv)

    result = run(
        topic=args.topic,
        video_file=args.video_file,
        thumbnail=args.thumbnail,
        out_dir=args.out,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
