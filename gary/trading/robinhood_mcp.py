"""Robinhood MCP trading broker (live-execution adapter, env-gated).

Routes the bot's orders to Robinhood's official **MCP trading server**
(``https://agent.robinhood.com/mcp/trading``). MCP exposes trading as callable
tools, so — unlike the Ed25519 seam in ``robinhood.py`` — we don't sign requests
ourselves; we call the server's tools.

Design goals so this is safe to have in the repo before going live:
  * **Paper stays default.** This adapter is only constructed when configured,
    and it refuses to place orders unless ``TRADING_LIVE=1``.
  * **Injectable ``caller``.** All MCP access goes through a
    ``caller(tool_name, arguments) -> result`` callable. Tests inject a fake; a
    real deployment uses the built-in JSON-RPC-over-HTTP client (or, when driven
    from inside Cursor, a caller that forwards to ``CallMcpTool``).
  * **Configurable tool names.** The exact tool names/schemas must be confirmed
    against the live server (via ``GetMcpTools``) after it's authenticated; they
    are overridable via env so we don't hard-code guesses.

Config:
    ROBINHOOD_MCP_URL      MCP endpoint (defaults to the official trading URL)
    ROBINHOOD_MCP_TOKEN    bearer token / session (required to enable)
    TRADING_LIVE=1         explicit opt-in before any live order is sent
    ROBINHOOD_MCP_TOOL_*   optional overrides for tool names (see _DEFAULT_TOOLS)
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gary.trading.models import Fill

DEFAULT_MCP_URL = "https://agent.robinhood.com/mcp/trading"

# Placeholder tool names — CONFIRM these against the live server with GetMcpTools
# once it's authenticated, then override via ROBINHOOD_MCP_TOOL_* if they differ.
_DEFAULT_TOOLS = {
    "place_order": "place_order",
    "get_quote": "get_quote",
    "get_positions": "get_positions",
    "cancel_order": "cancel_order",
}

Caller = Callable[[str, dict], Any]  # (tool_name, arguments) -> result


class RobinhoodMcpError(RuntimeError):
    """Raised when an MCP trading call fails or live trading is misconfigured."""


@dataclass
class RobinhoodMcpBroker:
    url: str = DEFAULT_MCP_URL
    token: str | None = None
    live_enabled: bool = False
    caller: Caller | None = None
    tools: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_TOOLS))
    timeout: float = 30.0
    _rpc_id: int = 0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RobinhoodMcpBroker | None:
        env = env if env is not None else dict(os.environ)
        token = env.get("ROBINHOOD_MCP_TOKEN")
        if not token:
            return None  # not configured -> caller falls back to paper
        tools = dict(_DEFAULT_TOOLS)
        for key in tools:
            override = env.get(f"ROBINHOOD_MCP_TOOL_{key.upper()}")
            if override:
                tools[key] = override
        return cls(
            url=env.get("ROBINHOOD_MCP_URL") or DEFAULT_MCP_URL,
            token=token,
            live_enabled=env.get("TRADING_LIVE", "").strip() in ("1", "true", "yes"),
            tools=tools,
        )

    # -- MCP plumbing ---------------------------------------------------------
    def call_tool(self, tool: str, arguments: dict) -> Any:
        """Invoke an MCP tool through the configured caller (or the HTTP client)."""
        caller = self.caller or self._http_caller
        return caller(tool, arguments)

    def _http_caller(self, tool: str, arguments: dict) -> Any:
        """Minimal MCP JSON-RPC (tools/call) over HTTP. Untested against the live
        server — swap in a verified caller/transport before real trading."""
        import httpx

        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            resp = httpx.post(self.url, json=payload, headers=headers, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise RobinhoodMcpError(f"MCP transport error calling {tool}: {exc}") from exc
        if isinstance(data, dict) and data.get("error"):
            raise RobinhoodMcpError(f"MCP error from {tool}: {data['error']}")
        return data.get("result") if isinstance(data, dict) else data

    # -- trading API ----------------------------------------------------------
    def get_quote(self, symbol: str) -> Any:
        return self.call_tool(self.tools["get_quote"], {"symbol": symbol})

    def get_positions(self) -> Any:
        return self.call_tool(self.tools["get_positions"], {})

    def place_order(self, symbol: str, side: str, quantity: float) -> Any:
        if side not in ("buy", "sell"):
            raise RobinhoodMcpError(f"invalid side: {side!r}")
        if not self.live_enabled:
            raise RobinhoodMcpError("live trading disabled; set TRADING_LIVE=1 to enable")
        if quantity <= 0:
            raise RobinhoodMcpError("quantity must be positive")
        return self.call_tool(
            self.tools["place_order"],
            {"symbol": symbol, "side": side, "type": "market", "quantity": quantity},
        )

    # -- Broker surface (so the engine can route to it like PaperBroker) ------
    def buy(self, symbol: str, notional: float, price: float, *, on: str = "",
            strategy: str = "", reason: str = "") -> Fill | None:
        if notional <= 0 or price <= 0:
            return None
        quantity = notional / price
        self.place_order(symbol, "buy", quantity)
        return Fill(date=on, symbol=symbol, side="buy", quantity=round(quantity, 8),
                    price=round(price, 6), notional=round(notional, 2),
                    strategy=strategy or "robinhood-mcp", reason=reason)

    def sell(self, symbol: str, quantity: float, price: float, *, on: str = "",
             strategy: str = "", reason: str = "") -> Fill | None:
        if quantity <= 0 or price <= 0:
            return None
        self.place_order(symbol, "sell", quantity)
        return Fill(date=on, symbol=symbol, side="sell", quantity=round(quantity, 8),
                    price=round(price, 6), notional=round(quantity * price, 2),
                    strategy=strategy or "robinhood-mcp", reason=reason)
