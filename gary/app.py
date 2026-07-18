"""FastAPI application: dashboard + agent API (issue #7).

Run in development with:

    uvicorn gary.app:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from gary.agents import TranscriptAgent, TrendsAgent

app = FastAPI(title="gary", version="0.1.0")

_TEMPLATE = (Path(__file__).parent / "templates" / "dashboard.html").read_text(
    encoding="utf-8"
)

# In-memory store of generated transcripts (swap for a DB later).
_transcripts: list[dict[str, Any]] = []

transcript_agent = TranscriptAgent()
trends_agent = TrendsAgent()


class TranscriptRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Finance topic for the video")
    data_points: list[str] = Field(default_factory=list)


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
