import pytest

from gary.agents import TranscriptAgent, TrendsAgent


def test_transcript_generation_basic():
    agent = TranscriptAgent()
    t = agent.generate("Bitcoin ETF inflows")
    assert t.topic == "Bitcoin ETF inflows"
    assert t.title
    assert len(t.sections) == 4
    assert t.word_count > 0


def test_transcript_uses_data_points():
    agent = TranscriptAgent()
    t = agent.generate("Fed rate decision", data_points=["CPI cooled to 3.1%"])
    joined = " ".join(s["script"] for s in t.sections)
    assert "CPI cooled to 3.1%" in joined


def test_transcript_rejects_empty_topic():
    agent = TranscriptAgent()
    with pytest.raises(ValueError):
        agent.generate("   ")


def test_trends_ranked_and_limited():
    agent = TrendsAgent()
    top3 = agent.top("crypto", limit=3)
    assert len(top3) == 3
    scores = [t.score for t in top3]
    assert scores == sorted(scores, reverse=True)


def test_quantum_trends_market():
    agent = TrendsAgent()
    top = agent.top("quantum", limit=3)
    assert len(top) == 3
    assert all(t.market == "quantum" for t in top)


def test_trends_rejects_unknown_market():
    agent = TrendsAgent()
    with pytest.raises(ValueError):
        agent.top("forex")  # type: ignore[arg-type]
