"""Pluggable LLM scripting for transcripts (issue #1, quality upgrade).

Uses any OpenAI-compatible chat-completions endpoint via httpx (no extra SDK).
Enabled when ``OPENAI_API_KEY`` is set; otherwise ``generate_script`` returns
None and the caller falls back to the deterministic script. Configure with:

    OPENAI_API_KEY   (required to enable)
    OPENAI_BASE_URL  (default https://api.openai.com/v1)
    OPENAI_MODEL     (default gpt-4o-mini)
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

REQUIRED_HEADINGS = ["Hook", "The Data", "Analysis", "Call To Action"]
_DEFAULT_BASE = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o-mini"


def _chat_completion(messages: list[dict[str, str]], env: dict[str, str]) -> str | None:
    """Low-level call. Returns the assistant message text, or None on failure."""
    api_key = env.get("OPENAI_API_KEY")
    if not api_key:
        return None
    base = env.get("OPENAI_BASE_URL", _DEFAULT_BASE).rstrip("/")
    model = env.get("OPENAI_MODEL", _DEFAULT_MODEL)
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.8,
                "response_format": {"type": "json_object"},
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return None


def generate_script(
    topic: str,
    headlines: list[str],
    channel_name: str = "Stickfigure Finance",
    env: dict[str, str] | None = None,
) -> list[dict[str, str]] | None:
    """Return transcript sections via an LLM, or None if unavailable/invalid."""
    env = env if env is not None else dict(os.environ)
    if not env.get("OPENAI_API_KEY"):
        return None

    headline_block = "\n".join(f"- {h}" for h in headlines) or "- (no fresh headlines)"
    system = (
        "You are a punchy YouTube finance scriptwriter for a channel called "
        f"{channel_name}. Write tight, energetic, retail-investor-friendly copy. "
        "Never give financial advice; always include a disclaimer in the outro."
    )
    user = (
        f"Topic: {topic}\n\n"
        f"Recent headlines to ground the script:\n{headline_block}\n\n"
        "Write a short video script as JSON with this exact shape:\n"
        '{"sections": [{"heading": "Hook", "script": "..."}, '
        '{"heading": "The Data", "script": "..."}, '
        '{"heading": "Analysis", "script": "..."}, '
        '{"heading": "Call To Action", "script": "..."}]}\n'
        "Use exactly those four headings in that order. Each script is 2-3 "
        "sentences. The Hook must greet viewers with the channel name."
    )

    content = _chat_completion(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        env,
    )
    if not content:
        return None

    return _parse_sections(content)


def _parse_sections(content: str) -> list[dict[str, str]] | None:
    try:
        data: Any = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None

    sections = data.get("sections") if isinstance(data, dict) else None
    if not isinstance(sections, list):
        return None

    cleaned: list[dict[str, str]] = []
    for item in sections:
        if not isinstance(item, dict):
            return None
        heading = str(item.get("heading", "")).strip()
        script = str(item.get("script", "")).strip()
        if not heading or not script:
            return None
        cleaned.append({"heading": heading, "script": script})

    # Must contain exactly the headings the video renderer knows how to style.
    if [s["heading"] for s in cleaned] != REQUIRED_HEADINGS:
        return None
    return cleaned
