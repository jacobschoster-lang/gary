"""Text-to-speech narration via gTTS.

gTTS needs internet (no API key). ``synthesize`` returns False on any failure so
video rendering can gracefully fall back to a silent clip. Swap this module for
a cloud/offline TTS engine to change the voice.
"""

from __future__ import annotations

from pathlib import Path


def synthesize(text: str, out_path: str, lang: str = "en") -> bool:
    """Render ``text`` to an MP3 at ``out_path``. Returns True on success."""
    text = (text or "").strip()
    if not text:
        return False
    try:
        from gtts import gTTS

        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        gTTS(text=text, lang=lang).save(out_path)
        return Path(out_path).exists() and Path(out_path).stat().st_size > 0
    except Exception:
        return False
