"""Robinhood Crypto broker seam (env-gated) — the live path.

This week the bot runs on :class:`~gary.trading.broker.PaperBroker` (no real
money). This module is the extension point for going live, mirroring how
``gary.finance.plaid.PlaidClient.from_env`` gates a real integration on env vars.

Robinhood has **no official equities trading API** — unofficial endpoints share
your password/MFA, violate the ToS, and can get an account locked; don't use
them. Robinhood *does* offer an official **Crypto Trading API** that signs each
request with an Ed25519 key. This module builds and signs those requests. The
actual Ed25519 signing is injected (``signer``) so request construction is
unit-testable offline and we don't hard-depend on a crypto library; a real
signer is used only when a key + a signing lib are available.

Config:
    ROBINHOOD_API_KEY          Robinhood Crypto API key
    ROBINHOOD_PRIVATE_KEY      base64 Ed25519 private key seed
    TRADING_LIVE=1             explicit opt-in before any live order is sent
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from gary.trading.models import Fill

_ORDERS_PATH = "/api/v1/crypto/trading/orders/"
Signer = Callable[[str], str]  # message -> base64 signature


class RobinhoodError(RuntimeError):
    """Raised when a Robinhood API call fails or live trading is misconfigured."""


def canonical_message(api_key: str, timestamp: str, path: str, method: str, body: str = "") -> str:
    """The exact string Robinhood Crypto requires you to sign for a request."""
    return f"{api_key}{timestamp}{path}{method}{body}"


def default_ed25519_signer(private_key_b64: str) -> Signer | None:
    """Return an Ed25519 signer if a crypto lib is installed, else ``None``.

    Tries ``cryptography`` then ``PyNaCl``. Kept optional so the package has no
    hard crypto dependency; callers can also inject their own signer.
    """
    import base64

    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_key_b64))

        def _sign(message: str) -> str:
            return base64.b64encode(key.sign(message.encode())).decode()

        return _sign
    except Exception:
        pass
    try:
        from nacl.signing import SigningKey

        signing_key = SigningKey(base64.b64decode(private_key_b64))

        def _sign_nacl(message: str) -> str:
            return base64.b64encode(signing_key.sign(message.encode()).signature).decode()

        return _sign_nacl
    except Exception:
        return None


@dataclass
class RobinhoodCryptoBroker:
    """Env-gated live crypto broker. Request construction is testable; the actual
    network send is intentionally left to an injected ``transport``."""

    api_key: str
    private_key_b64: str
    live_enabled: bool = False
    signer: Signer | None = None
    base_url: str = "https://trading.robinhood.com"

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
            signer=default_ed25519_signer(private_key),
        )

    def sign(self, message: str) -> str:
        if self.signer is None:
            raise RobinhoodError(
                "no Ed25519 signer available — install 'cryptography' or 'PyNaCl' and set "
                "ROBINHOOD_PRIVATE_KEY, or inject a signer."
            )
        return self.signer(message)

    def prepare_order(
        self, symbol: str, side: str, quantity: float, timestamp: int | None = None
    ) -> dict:
        """Build the signed request dict (method/path/body/headers) for a market
        order. Deterministic given a fixed timestamp + signer — this is what the
        unit tests exercise."""
        if side not in ("buy", "sell"):
            raise RobinhoodError(f"invalid side: {side!r}")
        ts = str(timestamp if timestamp is not None else int(time.time()))
        body = json.dumps(
            {
                "symbol": symbol,
                "side": side,
                "type": "market",
                "market_order_config": {"asset_quantity": str(quantity)},
            },
            separators=(",", ":"),
        )
        message = canonical_message(self.api_key, ts, _ORDERS_PATH, "POST", body)
        signature = self.sign(message)
        headers = {
            "x-api-key": self.api_key,
            "x-signature": signature,
            "x-timestamp": ts,
            "Content-Type": "application/json",
        }
        return {"method": "POST", "url": self.base_url + _ORDERS_PATH, "body": body,
                "headers": headers}

    def place_order(
        self, symbol: str, side: str, quantity: float,
        transport: Callable[[dict], dict] | None = None,
    ) -> dict:
        """Place a live order. Requires TRADING_LIVE=1 and a ``transport`` that
        performs the HTTP POST (kept injectable so nothing sends by accident)."""
        if not self.live_enabled:
            raise RobinhoodError("live trading disabled; set TRADING_LIVE=1 to enable")
        request = self.prepare_order(symbol, side, quantity)
        if transport is None:
            raise RobinhoodError("no transport provided; refusing to send a live order")
        return transport(request)

    # -- Broker protocol (engine integration not wired to live yet) -----------
    def buy(self, symbol: str, notional: float, price: float, *, on: str = "") -> Fill:
        raise NotImplementedError(
            "Live order routing is not wired into the engine; the bot runs on PaperBroker. "
            "Use prepare_order()/place_order() with a transport to trade live crypto."
        )

    def sell(self, symbol: str, quantity: float, price: float, *, on: str = "") -> Fill:
        raise NotImplementedError("See buy(): live routing is intentionally gated.")
