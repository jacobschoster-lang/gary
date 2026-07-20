"""Tests for persisted content store and dashboard API additions."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from gary.agents.publisher_agent import PublishedVideo, Publisher
from gary.app import app
from gary.content.store import ContentStore


def test_content_store_roundtrip(tmp_path: Path):
    path = tmp_path / "content.json"
    store = ContentStore(path)
    store.add_transcript({"title": "T1", "topic": "Bitcoin", "word_count": 100})
    video = PublishedVideo("vid1", "Title", "long", "https://youtu.be/vid1", "2026-01-01T00:00:00Z")
    store.add_video(video)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["transcripts"]) == 1
    assert len(data["videos"]) == 1

    pub = Publisher()
    store.hydrate_publisher(pub)
    assert "vid1" in pub._videos


def test_content_status_endpoint():
    client = TestClient(app)
    res = client.get("/api/content/status")
    assert res.status_code == 200
    body = res.json()
    assert "transcripts" in body
    assert "daily_post_schedule" in body


def test_comment_drafts_endpoint():
    client = TestClient(app)
    run = client.post("/api/pipeline/run", json={"topic": "Fed rate cuts"})
    assert run.status_code == 200
    video_id = run.json()["published"]["video_id"]

    res = client.post(
        f"/api/videos/{video_id}/comments",
        json={"comments": ["What ETF do you recommend?", "Is this financial advice?"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert len(body["replies"]) == 2
    assert body["replies"][0]["reply"]


def test_dashboard_static_assets():
    client = TestClient(app)
    for path in ("/static/dashboard.css", "/static/dashboard.js"):
        res = client.get(path)
        assert res.status_code == 200
