import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Keep tests deterministic/offline.

    Live HTTP returns None (agents fall back to stubs) and the gTTS backend
    raises (so ``tts.synthesize`` returns False -> silent video). Individual
    tests opt back in by patching these seams with canned data.
    """
    monkeypatch.setattr("gary.data.http.get_json", lambda *a, **k: None)
    monkeypatch.setattr("gary.data.http.get_text", lambda *a, **k: None)
    monkeypatch.setattr("gary.agents.llm._chat_completion", lambda *a, **k: None)

    def _no_network_tts(*a, **k):
        raise RuntimeError("offline in tests")

    monkeypatch.setattr("gtts.gTTS", _no_network_tts)
