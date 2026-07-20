from gary.integrations.youtube_data import api_key, fetch_finance_topics, fetch_video_statistics


def test_api_key_from_env(monkeypatch):
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    assert api_key() is None
    monkeypatch.setenv("YOUTUBE_API_KEY", "test-key")
    assert api_key() == "test-key"


def test_fetch_finance_topics_without_key():
    assert fetch_finance_topics(env={}) is None


def test_fetch_finance_topics_parses_response(monkeypatch):
    payload = {
        "items": [
            {
                "id": {"videoId": "abc123"},
                "snippet": {"title": "Fed pivot explained", "channelTitle": "MacroDaily"},
            }
        ]
    }
    monkeypatch.setattr("gary.integrations.youtube_data.get_json", lambda *a, **k: payload)
    topics = fetch_finance_topics(limit=1, env={"YOUTUBE_API_KEY": "k"})
    assert topics is not None
    assert topics[0]["title"] == "Fed pivot explained"
    assert topics[0]["channel"] == "MacroDaily"


def test_fetch_video_statistics_parses_counts(monkeypatch):
    payload = {
        "items": [{"statistics": {"viewCount": "1200", "likeCount": "40", "commentCount": "5"}}]
    }
    monkeypatch.setattr("gary.integrations.youtube_data.get_json", lambda *a, **k: payload)
    stats = fetch_video_statistics("abc123", env={"YOUTUBE_API_KEY": "k"})
    assert stats is not None
    assert stats["views"] == 1200
    assert stats["source"] == "youtube"
