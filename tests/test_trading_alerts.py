from __future__ import annotations

import pytest

from gary.trading.alerts import (
    WEBHOOK_ENV,
    alert_enabled,
    format_daily_summary,
    send_alert,
)

WEBHOOK_URL = "https://hooks.example.com/services/T000/B000/XXXX"


def test_alert_enabled_false_when_missing():
    assert alert_enabled({}) is False


def test_alert_enabled_false_when_blank():
    assert alert_enabled({WEBHOOK_ENV: ""}) is False


def test_alert_enabled_true_when_set():
    assert alert_enabled({WEBHOOK_ENV: WEBHOOK_URL}) is True


def test_format_daily_summary_full():
    msg = format_daily_summary(
        {
            "date": "2026-07-30",
            "mode": "paper",
            "equity": 10240.0,
            "actions": ["buy NVDA", "sell AAPL", "hold MSFT"],
            "options": {
                "symbol": "NVDA",
                "strategy": "iron_condor",
                "action": "held",
                "equity": 9980.0,
            },
        }
    )
    assert "2026-07-30" in msg
    assert "$10,240.00" in msg
    assert "3 actions" in msg
    assert "options NVDA/iron_condor: held $9,980.00" in msg


def test_format_daily_summary_includes_date_and_equity():
    msg = format_daily_summary({"date": "2026-01-01", "equity": 5000})
    assert "2026-01-01" in msg
    assert "$5,000.00" in msg


def test_format_daily_summary_tolerates_missing_options_and_actions():
    msg = format_daily_summary({"date": "2026-02-02", "equity": 1234.5})
    assert "2026-02-02" in msg
    assert "$1,234.50" in msg
    assert "options" not in msg
    assert "action" not in msg


def test_format_daily_summary_tolerates_empty_dict():
    msg = format_daily_summary({})
    assert isinstance(msg, str)
    assert "gary" in msg


def test_format_daily_summary_single_action_not_plural():
    msg = format_daily_summary({"date": "d", "actions": ["one"]})
    assert "1 action" in msg
    assert "1 actions" not in msg


def test_send_alert_disabled_does_not_call_transport():
    calls: list[tuple[str, dict]] = []

    def fake_transport(url: str, payload: dict):
        calls.append((url, payload))

    assert send_alert("hello", transport=fake_transport, env={}) is False
    assert calls == []


def test_send_alert_enabled_calls_transport_once():
    calls: list[tuple[str, dict]] = []

    def fake_transport(url: str, payload: dict):
        calls.append((url, payload))
        return "ok"

    result = send_alert(
        "daily summary",
        transport=fake_transport,
        env={WEBHOOK_ENV: WEBHOOK_URL},
    )
    assert result is True
    assert len(calls) == 1
    url, payload = calls[0]
    assert url == WEBHOOK_URL
    assert payload == {"text": "daily summary"}


def test_send_alert_transport_raises_fails_soft():
    def boom(url: str, payload: dict):
        raise RuntimeError("network down")

    result = send_alert(
        "will fail",
        transport=boom,
        env={WEBHOOK_ENV: WEBHOOK_URL},
    )
    assert result is False


def test_send_alert_disabled_with_blank_webhook():
    def boom(url: str, payload: dict):
        raise AssertionError("transport should not be called when disabled")

    assert send_alert("x", transport=boom, env={WEBHOOK_ENV: ""}) is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
