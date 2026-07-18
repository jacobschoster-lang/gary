"""FastAPI application: dashboard + agent API (issue #7).

Run in development with:

    uvicorn gary.app:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field

from gary.agents import ThumbnailAgent, TranscriptAgent, TrendsAgent
from gary.pipeline import ContentPipeline
from gary.render import render_story

app = FastAPI(title="gary", version="0.1.0")

_TEMPLATE = (Path(__file__).parent / "templates" / "dashboard.html").read_text(
    encoding="utf-8"
)

# In-memory store of generated transcripts (swap for a DB later).
_transcripts: list[dict[str, Any]] = []

transcript_agent = TranscriptAgent()
trends_agent = TrendsAgent()
thumbnail_agent = ThumbnailAgent()
pipeline = ContentPipeline()


class TranscriptRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Finance topic for the video")
    data_points: list[str] = Field(default_factory=list)


class PipelineRequest(BaseModel):
    topic: str | None = Field(default=None, description="Optional topic; auto-picked if omitted")
    market: str = Field(default="crypto")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "gary"}


@app.get("/api/trends")
def trends(market: str = "stocks", limit: int = 5) -> dict[str, Any]:
    try:
        results = trends_agent.top(market, limit)  # type: ignore[arg-type]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"market": market, "trends": [t.to_dict() for t in results]}


@app.get("/api/youtube-trends")
def youtube_trends(limit: int = 5) -> dict[str, Any]:
    try:
        topics = trends_agent.youtube_topics(limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"topics": [t.to_dict() for t in topics]}


@app.post("/api/transcript")
def create_transcript(req: TranscriptRequest) -> dict[str, Any]:
    try:
        transcript = transcript_agent.generate(req.topic, req.data_points)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record = transcript.to_dict()
    _transcripts.insert(0, record)
    return record


@app.get("/api/transcripts")
def list_transcripts() -> dict[str, Any]:
    return {"count": len(_transcripts), "transcripts": _transcripts}


@app.get("/api/thumbnail.svg")
def thumbnail_svg(topic: str) -> Response:
    try:
        spec = thumbnail_agent.design(topic)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(content=thumbnail_agent.render_svg(spec), media_type="image/svg+xml")


@app.post("/api/pipeline/run")
def run_pipeline(req: PipelineRequest) -> dict[str, Any]:
    try:
        result = pipeline.run_daily(req.topic, req.market)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _transcripts.insert(0, result["transcript"])
    return result


@app.get("/api/story.mp4")
def story_video(topic: str) -> FileResponse:
    """Render a short animated stick-figure video for a topic (preview)."""
    plan = pipeline.run_daily(topic=topic)
    out_path = Path(tempfile.gettempdir()) / "gary_preview.mp4"
    try:
        render_story(plan, out_path=str(out_path), fps=10, seconds_per_scene=2.5)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(str(out_path), media_type="video/mp4", filename="story.mp4")


@app.get("/api/videos")
def list_videos() -> dict[str, Any]:
    videos = pipeline.publisher.videos()
    return {
        "count": len(videos),
        "videos": [
            {**v.to_dict(), "metrics": pipeline.publisher.track(v.video_id)} for v in videos
        ],
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    rows = "".join(
        f"<li><strong>{t['title']}</strong> "
        f"<span class='muted'>({t['word_count']} words, {t['created_at']})</span></li>"
        for t in _transcripts[:10]
    )
    if not rows:
        rows = "<li class='muted'>No transcripts yet. Generate one above.</li>"
    return _TEMPLATE.replace("<!--TRANSCRIPTS-->", rows)
