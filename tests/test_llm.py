import json

from gary.agents import TranscriptAgent, llm

_VALID = json.dumps({
    "sections": [
        {"heading": "Hook", "script": "Welcome to Stickfigure Finance! Big moves today."},
        {"heading": "The Data", "script": "Inflows jumped. Volume spiked."},
        {"heading": "Analysis", "script": "Momentum is building. Watch liquidity."},
        {"heading": "Call To Action", "script": "Subscribe. Not financial advice."},
    ]
})

_BAD_HEADINGS = json.dumps({
    "sections": [
        {"heading": "Intro", "script": "x"},
        {"heading": "Outro", "script": "y"},
    ]
})


def test_generate_script_none_without_key(monkeypatch):
    assert llm.generate_script("Bitcoin", [], env={}) is None


def test_generate_script_parses_valid(monkeypatch):
    monkeypatch.setattr("gary.agents.llm._chat_completion", lambda *a, **k: _VALID)
    sections = llm.generate_script("Bitcoin", ["headline"], env={"OPENAI_API_KEY": "k"})
    assert sections is not None
    assert [s["heading"] for s in sections] == llm.REQUIRED_HEADINGS


def test_generate_script_rejects_wrong_headings(monkeypatch):
    monkeypatch.setattr("gary.agents.llm._chat_completion", lambda *a, **k: _BAD_HEADINGS)
    assert llm.generate_script("Bitcoin", [], env={"OPENAI_API_KEY": "k"}) is None


def test_generate_script_handles_garbage(monkeypatch):
    monkeypatch.setattr("gary.agents.llm._chat_completion", lambda *a, **k: "not json")
    assert llm.generate_script("Bitcoin", [], env={"OPENAI_API_KEY": "k"}) is None


def test_transcript_agent_uses_llm_when_available(monkeypatch):
    monkeypatch.setattr("gary.agents.llm._chat_completion", lambda *a, **k: _VALID)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    t = TranscriptAgent(use_live=False, use_llm=True).generate("Bitcoin ETF inflows")
    joined = " ".join(s["script"] for s in t.sections)
    assert "Big moves today" in joined


def test_transcript_agent_falls_back_without_llm():
    # offline fixture forces _chat_completion -> None, so deterministic script.
    t = TranscriptAgent(use_live=False, use_llm=True).generate("Bitcoin ETF inflows")
    joined = " ".join(s["script"] for s in t.sections)
    assert "Welcome back to Stickfigure Finance" in joined
