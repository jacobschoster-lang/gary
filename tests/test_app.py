from fastapi.testclient import TestClient

from gary.app import app

client = TestClient(app)


def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


def test_trends_endpoint():
    res = client.get("/api/trends?market=stocks&limit=2")
    assert res.status_code == 200
    body = res.json()
    assert body["market"] == "stocks"
    assert len(body["trends"]) == 2


def test_create_and_list_transcript():
    res = client.post("/api/transcript", json={"topic": "Solana DeFi surge"})
    assert res.status_code == 200
    assert res.json()["topic"] == "Solana DeFi surge"

    listing = client.get("/api/transcripts")
    assert listing.status_code == 200
    assert listing.json()["count"] >= 1


def test_dashboard_renders():
    res = client.get("/")
    assert res.status_code == 200
    assert "Stickfigure Finance" in res.text


def test_youtube_trends_endpoint():
    res = client.get("/api/youtube-trends?limit=3")
    assert res.status_code == 200
    assert len(res.json()["topics"]) == 3


def test_thumbnail_svg_endpoint():
    res = client.get("/api/thumbnail.svg?topic=Bitcoin ETF inflows")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("image/svg+xml")
    assert res.text.startswith("<svg")


def test_pipeline_endpoint_and_videos():
    res = client.post("/api/pipeline/run", json={"topic": "Ethereum staking"})
    assert res.status_code == 200
    body = res.json()
    assert body["topic"] == "Ethereum staking"
    assert body["published"]["url"].startswith("https://youtu.be/")

    videos = client.get("/api/videos")
    assert videos.status_code == 200
    assert videos.json()["count"] >= 1
