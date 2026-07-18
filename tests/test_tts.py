from gary.render import tts


def test_synthesize_empty_returns_false():
    assert tts.synthesize("", "/tmp/none.mp3") is False


def test_synthesize_returns_false_when_backend_unavailable(tmp_path):
    # The offline fixture makes the gTTS backend raise -> graceful False.
    assert tts.synthesize("hello world", str(tmp_path / "out.mp3")) is False
