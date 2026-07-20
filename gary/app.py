"""FastAPI application: dashboard + agent API (issue #7).

Run in development with:

    uvicorn gary.app:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import Request

from gary.agents import ThumbnailAgent, TranscriptAgent, TrendsAgent
from gary.content import ContentStore
from gary.content.store import ContentStoreError
from gary.finance import (
    PlaidClient,
    PlaidError,
    PlaidTokenStore,
    ProfileStore,
    cashflow_summary,
    compare_strategies,
    dedupe,
    financial_health,
    net_worth_breakdown,
    ocr_import,
    parse_csv,
    record_snapshot,
    retirement_plan,
    sample_profile,
)
from gary.finance.models import Profile
from gary.integrations.youtube import YouTubeUploader
from gary.pipeline import ContentPipeline
from gary.realestate import search_listings
from gary.render import render_story
from gary.render.preview_cache import get_or_render

app = FastAPI(title="gary", version="0.1.0")

_TEMPLATE = (Path(__file__).parent / "templates" / "dashboard.html").read_text(
    encoding="utf-8"
)

transcript_agent = TranscriptAgent()
trends_agent = TrendsAgent()
thumbnail_agent = ThumbnailAgent()
finance_store = ProfileStore()
plaid_tokens = PlaidTokenStore()
pipeline = ContentPipeline()
content_store = ContentStore()
content_store.hydrate_publisher(pipeline.publisher)
_PLAID_NOT_CONFIGURED = "Plaid not configured (set PLAID_CLIENT_ID/SECRET)"

_STATIC = Path(__file__).parent / "static"
if _STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")


@app.middleware("http")
async def cache_static_assets(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "public, max-age=3600")
    return response


def _save_transcript(record: dict[str, Any]) -> None:
    content_store.add_transcript(record)


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
    _save_transcript(record)
    return record


@app.get("/api/transcripts")
def list_transcripts() -> dict[str, Any]:
    rows = content_store.transcripts()
    return {"count": len(rows), "transcripts": rows}


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
    video = pipeline.publisher._videos[result["published"]["video_id"]]
    try:
        content_store.save_pipeline_result(result["transcript"], video)
    except ContentStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return result


@app.get("/api/story.mp4")
def story_video(topic: str, voice: bool = False) -> FileResponse:
    """Render a short animated stick-figure video for a topic (preview).

    ``voice=false`` (default) renders a fast silent preview; ``voice=true`` adds
    gTTS narration (slower, needs internet). Results are cached by topic.
    """
    try:
        path = get_or_render(
            topic,
            voice,
            lambda t: pipeline.run_daily(topic=t),
            render_story,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return FileResponse(str(path), media_type="video/mp4", filename="story.mp4")


@app.get("/api/videos")
def list_videos() -> dict[str, Any]:
    content_store.hydrate_publisher(pipeline.publisher)
    videos = pipeline.publisher.videos()
    videos.sort(key=lambda v: v.published_at, reverse=True)
    return {
        "count": len(videos),
        "videos": [
            {**v.to_dict(), "metrics": pipeline.publisher.track(v.video_id)} for v in videos
        ],
    }


class CommentDraftIn(BaseModel):
    comments: list[str] = Field(default_factory=list)
    top_n: int = Field(default=10, ge=1, le=50)


@app.post("/api/videos/{video_id}/comments")
def draft_comment_replies(video_id: str, req: CommentDraftIn) -> dict[str, Any]:
    content_store.hydrate_publisher(pipeline.publisher)
    try:
        replies = pipeline.publisher.manage_comments(video_id, req.comments, req.top_n)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"video_id": video_id, "replies": replies}


@app.get("/api/content/status")
def content_status() -> dict[str, Any]:
    return {
        "transcripts": len(content_store.transcripts()),
        "videos": len(content_store.videos()),
        "llm_enabled": bool(os.environ.get("OPENAI_API_KEY")),
        "plaid_configured": PlaidClient.from_env() is not None,
        "rentcast_configured": bool(os.environ.get("RENTCAST_API_KEY")),
        "youtube_upload_configured": YouTubeUploader.from_env() is not None,
        "youtube_api_configured": bool(os.environ.get("YOUTUBE_API_KEY")),
        "daily_post_schedule": "08:00 America/New_York via GitHub Actions",
    }


class AssetIn(BaseModel):
    name: str
    value: float = 0.0
    kind: str = "other"


class DebtIn(BaseModel):
    name: str
    balance: float = 0.0
    apr: float = 0.0
    min_payment: float = 0.0


class FinanceProfileIn(BaseModel):
    monthly_income: float = 0.0
    monthly_expenses: float = 0.0
    extra_debt_payment: float = 0.0
    age: int = 0
    retirement_age: int = 65
    monthly_retirement_contribution: float = 0.0
    assets: list[AssetIn] = Field(default_factory=list)
    debts: list[DebtIn] = Field(default_factory=list)


def _finance_payload(profile: Profile) -> dict[str, Any]:
    cashflow = cashflow_summary(profile.transactions)
    return {
        "profile": profile.to_dict(),
        "net_worth": net_worth_breakdown(profile),
        "history": profile.networth_history,
        "debt_plan": compare_strategies(profile.debts, profile.extra_debt_payment),
        "health": financial_health(profile),
        "retirement": retirement_plan(profile),
        "cashflow": cashflow,
        "recent_transactions": [t.to_dict() for t in profile.transactions[-15:][::-1]],
    }


def _apply_cashflow_to_profile(profile: Profile) -> None:
    """Derive monthly income/expenses from imported transactions when present."""
    if not profile.transactions:
        return
    cf = cashflow_summary(profile.transactions)
    if cf["avg_monthly_income"]:
        profile.monthly_income = cf["avg_monthly_income"]
    if cf["avg_monthly_expenses"]:
        profile.monthly_expenses = cf["avg_monthly_expenses"]


@app.get("/api/finance")
def get_finance() -> dict[str, Any]:
    return _finance_payload(finance_store.load())


@app.post("/api/finance")
def set_finance(req: FinanceProfileIn) -> dict[str, Any]:
    existing = finance_store.load()
    profile = Profile.from_dict({**req.model_dump(), "networth_history": existing.networth_history})
    record_snapshot(profile)
    finance_store.save(profile)
    return _finance_payload(profile)


@app.post("/api/finance/import")
async def import_finance_document(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
    """Import a bank CSV export or an image snapshot (best-effort OCR)."""
    raw = await file.read()
    name = (file.filename or "").lower()
    ctype = (file.content_type or "").lower()

    if name.endswith(".csv") or "csv" in ctype or "text" in ctype:
        try:
            text = raw.decode("utf-8-sig", errors="replace")
        except Exception as exc:  # pragma: no cover - decode is very permissive
            raise HTTPException(status_code=400, detail=f"could not read file: {exc}") from exc
        incoming = parse_csv(text)
        source = "csv"
    elif name.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) or "image" in ctype:
        incoming = ocr_import(raw)
        source = "image"
    else:
        raise HTTPException(status_code=400, detail="upload a .csv or an image file")

    if not incoming:
        raise HTTPException(
            status_code=422,
            detail="no transactions found (CSV needs date/description/amount columns)",
        )

    profile = finance_store.load()
    profile.transactions = dedupe(profile.transactions, incoming)
    _apply_cashflow_to_profile(profile)
    record_snapshot(profile)
    finance_store.save(profile)
    payload = _finance_payload(profile)
    payload["imported"] = {"source": source, "added": len(incoming)}
    return payload


class PlaidExchangeIn(BaseModel):
    public_token: str = Field(..., min_length=1)


def _merge_plaid_pull(assets, debts, txns) -> Profile:
    """Merge freshly pulled Plaid data into the saved profile."""
    profile = finance_store.load()
    # Replace Plaid-sourced accounts by name, keep user-added ones.
    plaid_asset_names = {a.name for a in assets}
    plaid_debt_names = {d.name for d in debts}
    profile.assets = [a for a in profile.assets if a.name not in plaid_asset_names] + assets
    profile.debts = [d for d in profile.debts if d.name not in plaid_debt_names] + debts
    profile.transactions = dedupe(profile.transactions, txns)
    _apply_cashflow_to_profile(profile)
    record_snapshot(profile)
    finance_store.save(profile)
    return profile


@app.get("/api/finance/plaid/status")
def plaid_status() -> dict[str, Any]:
    client = PlaidClient.from_env()
    return {
        "configured": client is not None,
        "env": (os.environ.get("PLAID_ENV", "sandbox") if client else None),
        "linked": plaid_tokens.linked(),
    }


@app.post("/api/finance/plaid/link-token")
def plaid_link_token() -> dict[str, Any]:
    client = PlaidClient.from_env()
    if client is None:
        raise HTTPException(status_code=400, detail=_PLAID_NOT_CONFIGURED)
    try:
        return {"link_token": client.create_link_token()}
    except PlaidError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/finance/plaid/exchange")
def plaid_exchange(req: PlaidExchangeIn) -> dict[str, Any]:
    client = PlaidClient.from_env()
    if client is None:
        raise HTTPException(status_code=400, detail=_PLAID_NOT_CONFIGURED)
    try:
        access_token = client.exchange_public_token(req.public_token)
        plaid_tokens.add(access_token)
        assets, debts, txns = client.pull(access_token)
    except PlaidError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    profile = _merge_plaid_pull(assets, debts, txns)
    payload = _finance_payload(profile)
    payload["imported"] = {"source": "plaid", "added": len(txns)}
    return payload


@app.post("/api/finance/plaid/sync")
def plaid_sync() -> dict[str, Any]:
    client = PlaidClient.from_env()
    if client is None:
        raise HTTPException(status_code=400, detail=_PLAID_NOT_CONFIGURED)
    tokens = plaid_tokens.access_tokens()
    if not tokens:
        raise HTTPException(status_code=400, detail="no linked bank; connect one first")
    all_assets, all_debts, all_txns = [], [], []
    try:
        for tok in tokens:
            a, d, t = client.pull(tok)
            all_assets += a
            all_debts += d
            all_txns += t
    except PlaidError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    profile = _merge_plaid_pull(all_assets, all_debts, all_txns)
    payload = _finance_payload(profile)
    payload["imported"] = {"source": "plaid", "added": len(all_txns)}
    return payload


@app.post("/api/finance/sample")
def load_sample_finance() -> dict[str, Any]:
    existing = finance_store.load()
    profile = sample_profile()
    profile.networth_history = existing.networth_history
    record_snapshot(profile)
    finance_store.save(profile)
    return _finance_payload(profile)


@app.get("/api/realestate")
def realestate(
    city: str = "Cincinnati",
    state: str = "OH",
    radius: float = 25,
    min_acres: float = 5.0,
    max_price: float = 350000.0,
) -> dict[str, Any]:
    return search_listings(
        city=city, state=state, radius=radius, min_acres=min_acres, max_price=max_price
    )


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return _TEMPLATE
