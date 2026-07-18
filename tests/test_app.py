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
    assert "gary" in res.text
