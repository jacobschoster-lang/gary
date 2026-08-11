"""Opt-in webhook alerting for the daily trading job.

Pushes a short summary (or an error) to a chat webhook (Slack/Discord/generic
JSON) so the operator gets a heads-up without checking the dashboard. Design
goals mirror the rest of ``gary``:

    - opt-in: only active when ``GARY_ALERT_WEBHOOK`` is set
    - fail soft: never raises, so a flaky webhook can't break the trade job
    - testable offline: the HTTP transport is injectable
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

WEBHOOK_ENV = "GARY_ALERT_WEBHOOK"

_TIMEOUT_SECONDS = 10.0


def alert_enabled(env: dict[str, str] | None = None) -> bool:
    """True iff the webhook env var is set (defaults to ``os.environ``)."""
    env = os.environ if env is None else env
    return bool(env.get(WEBHOOK_ENV))


def format_daily_summary(summary: dict) -> str:
    """Build a concise one/two-line message from a ``trade_daily`` summary dict.

    Tolerates missing keys so a partial summary (or an error path) still yields
    a sensible line. Example output::

        gary paper 2026-07-30 | equity $10,240.00 | 3 actions |
        options NVDA/iron_condor: held $9,980.00
    """
    summary = summary or {}
    mode = summary.get("mode", "paper")
    date = summary.get("date", "?")

    parts = [f"gary {mode} {date}"]

    equity = summary.get("equity")
    if isinstance(equity, int | float):
        parts.append(f"equity ${equity:,.2f}")

    actions = summary.get("actions")
    if isinstance(actions, list | tuple):
        count = len(actions)
        parts.append(f"{count} action{'' if count == 1 else 's'}")

    options = summary.get("options")
    if isinstance(options, dict) and options:
        symbol = options.get("symbol", "?")
        strategy = options.get("strategy", "?")
        action = options.get("action", "?")
        opt_line = f"options {symbol}/{strategy}: {action}"
        opt_equity = options.get("equity")
        if isinstance(opt_equity, int | float):
            opt_line += f" ${opt_equity:,.2f}"
        parts.append(opt_line)

    return " | ".join(parts)


def _httpx_transport(url: str, payload: dict) -> Any:
    """Default transport: POST ``payload`` as JSON with a short timeout."""
    import httpx

    return httpx.post(url, json=payload, timeout=_TIMEOUT_SECONDS)


def send_alert(
    message: str,
    transport: Callable[[str, dict], Any] | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    """Post ``{'text': message}`` to the ``GARY_ALERT_WEBHOOK`` URL.

    Returns ``True`` if the message was sent, ``False`` if alerting is disabled
    (no webhook configured) or the post failed. Never raises: any exception from
    the transport is swallowed and reported as ``False``.

    ``transport(url, json_payload)`` is injectable for tests; the default uses
    ``httpx.post`` with a short timeout.
    """
    env = os.environ if env is None else env
    url = env.get(WEBHOOK_ENV)
    if not url:
        return False

    transport = _httpx_transport if transport is None else transport
    try:
        transport(url, {"text": message})
    except Exception:
        return False
    return True
