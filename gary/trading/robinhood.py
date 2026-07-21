"""Robinhood broker seam (env-gated) — the live path for later.

This week the bot runs on :class:`~gary.trading.broker.PaperBroker`. This module
is the extension point for going live, mirroring how
``gary.finance.plaid.PlaidClient.from_env`` gates a real integration on env vars
and returns ``None`` when unconfigured (so the app degrades to paper).

Robinhood has **no official equities trading API**; unofficial endpoints require
password/MFA sharing, violate the ToS, and can get an account locked — avoid
them. Robinhood *does* offer an official **Crypto Trading API** (API key +
Ed25519 request signing). Wire that in below when you're ready to trade real
crypto; keep equities on paper (or use an official broker like Alpaca).

Config (only the crypto API is safe to enable):
    ROBINHOOD_API_KEY          Robinhood Crypto API key
    ROBINHOOD_PRIVATE_KEY      base64-encoded Ed25519 private key seed
    TRADING_LIVE=1             explicit opt-in before any live order is sent
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from gary.trading.models import Fill


class RobinhoodError(RuntimeError):
    """Raised when a Robinhood API call fails or live trading is misconfigured."""


@dataclass
class RobinhoodCryptoBroker:
    """Env-gated live crypto broker. Order placement is intentionally a seam."""

    api_key: str
    private_key_b64: str
    live_enabled: bool = False

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RobinhoodCryptoBroker | None:
        env = env if env is not None else dict(os.environ)
        api_key = env.get("ROBINHOOD_API_KEY")
        private_key = env.get("ROBINHOOD_PRIVATE_KEY")
        if not (api_key and private_key):
            return None
        return cls(
            api_key=api_key,
            private_key_b64=private_key,
            live_enabled=env.get("TRADING_LIVE", "").strip() in ("1", "true", "yes"),
        )

    def buy(self, symbol: str, notional: float, price: float, *, on: str = "") -> Fill:
        raise NotImplementedError(
            "Live Robinhood Crypto order placement is not wired up. Implement Ed25519 "
            "request signing against the official Crypto Trading API here, and only send "
            "orders when TRADING_LIVE=1. The bot runs on PaperBroker until then."
        )

    def sell(self, symbol: str, quantity: float, price: float, *, on: str = "") -> Fill:
        raise NotImplementedError(
            "Live Robinhood Crypto order placement is not wired up (see buy())."
        )
