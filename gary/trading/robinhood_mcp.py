"""Robinhood MCP trading broker (live-execution adapter, env-gated).

Routes orders to Robinhood's official **MCP trading server**:

    https://agent.robinhood.com/mcp/trading

Official equities tools (see Robinhood "Trading with your agent"):
  * Read: ``get_accounts``, ``get_portfolio``, ``get_equity_positions``,
    ``get_equity_quotes``, ``get_equity_orders``, ``get_equity_tradability``,
    ``search``
  * Trade: ``review_equity_order`` → ``place_equity_order``,
    ``cancel_equity_order``

Safety:
  * **Paper stays default.** This adapter is only constructed when configured,
    and it refuses to place orders unless ``TRADING_LIVE=1``.
  * **Review before place.** ``place_order`` / ``buy`` / ``sell`` call
    ``review_equity_order`` first (unless ``skip_review=True``) and surface
    pre-trade alerts; placement still requires live mode.
  * **Injectable ``caller``.** All MCP access goes through
    ``caller(tool_name, arguments) -> result``. Tests inject a fake; a real
    deployment uses the built-in JSON-RPC-over-HTTP client, or a caller that
    forwards to Cursor's ``CallMcpTool`` after the server is authenticated.

Config:
    ROBINHOOD_MCP_URL              MCP endpoint (defaults to the official URL)
    ROBINHOOD_MCP_TOKEN            bearer / session token (required to enable)
    ROBINHOOD_MCP_ACCOUNT          agentic account number (optional; auto-picked
                                   from ``get_accounts`` when omitted)
    TRADING_LIVE=1                 explicit opt-in before any live order is sent
    ROBINHOOD_MCP_TOOL_<NAME>      optional overrides for tool names
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from gary.trading.models import Fill

DEFAULT_MCP_URL = "https://agent.robinhood.com/mcp/trading"

# Official tool names from Robinhood Agentic Trading docs. Override via env if
# the live server renames anything after you confirm with GetMcpTools.
_DEFAULT_TOOLS = {
    "get_accounts": "get_accounts",
    "get_portfolio": "get_portfolio",
    "get_equity_positions": "get_equity_positions",
    "get_equity_quotes": "get_equity_quotes",
    "get_equity_orders": "get_equity_orders",
    "get_equity_tradability": "get_equity_tradability",
    "search": "search",
    "review_equity_order": "review_equity_order",
    "place_equity_order": "place_equity_order",
    "cancel_equity_order": "cancel_equity_order",
}

Caller = Callable[[str, dict], Any]  # (tool_name, arguments) -> result


class RobinhoodMcpError(RuntimeError):
    """Raised when an MCP trading call fails or live trading is misconfigured."""


def _unwrap(result: Any) -> Any:
    """Normalize MCP tool payloads that wrap content under ``data``."""
    if isinstance(result, dict) and "data" in result and len(result) <= 2:
        return result["data"]
    return result


@dataclass
class RobinhoodMcpBroker:
    url: str = DEFAULT_MCP_URL
    token: str | None = None
    account_number: str | None = None
    live_enabled: bool = False
    caller: Caller | None = None
    tools: dict[str, str] = field(default_factory=lambda: dict(_DEFAULT_TOOLS))
    timeout: float = 30.0
    require_review: bool = True
    _rpc_id: int = 0
    _resolved_account: str | None = None

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
            account_number=env.get("ROBINHOOD_MCP_ACCOUNT") or None,
            live_enabled=env.get("TRADING_LIVE", "").strip().lower() in ("1", "true", "yes"),
            tools=tools,
        )

    # -- MCP plumbing ---------------------------------------------------------
    def call_tool(self, tool: str, arguments: dict) -> Any:
        """Invoke an MCP tool through the configured caller (or the HTTP client)."""
        caller = self.caller or self._http_caller
        return caller(tool, arguments)

    def _http_caller(self, tool: str, arguments: dict) -> Any:
        """Minimal MCP JSON-RPC (tools/call) over HTTP.

        Untested against the live OAuth flow — prefer authenticating the MCP
        server in Cursor and forwarding via ``CallMcpTool``, or swap in a
        verified transport before real trading.
        """
        import httpx

        self._rpc_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._rpc_id,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
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

    def resolve_account(self) -> str:
        """Return the agentic account number (cached)."""
        if self.account_number:
            return self.account_number
        if self._resolved_account:
            return self._resolved_account
        raw = _unwrap(self.call_tool(self.tools["get_accounts"], {}))
        accounts = []
        if isinstance(raw, dict):
            accounts = raw.get("accounts") or raw.get("results") or []
        elif isinstance(raw, list):
            accounts = raw
        agentic = [
            a for a in accounts
            if isinstance(a, dict) and a.get("agentic_allowed")
        ]
        pick = (agentic or accounts or [None])[0]
        if not isinstance(pick, dict):
            raise RobinhoodMcpError("no Robinhood accounts returned by get_accounts")
        number = (
            pick.get("account_number")
            or pick.get("accountNumber")
            or pick.get("id")
        )
        if not number:
            raise RobinhoodMcpError(f"account payload missing account_number: {pick!r}")
        self._resolved_account = str(number)
        return self._resolved_account

    def _order_args(
        self,
        symbol: str,
        side: str,
        *,
        quantity: float | None = None,
        dollar_amount: float | None = None,
        order_type: str = "market",
        limit_price: float | None = None,
        ref_id: str | None = None,
    ) -> dict[str, Any]:
        if side not in ("buy", "sell"):
            raise RobinhoodMcpError(f"invalid side: {side!r}")
        if order_type not in ("market", "limit"):
            raise RobinhoodMcpError(f"invalid order type: {order_type!r}")
        if quantity is None and dollar_amount is None:
            raise RobinhoodMcpError("quantity or dollar_amount is required")
        if quantity is not None and quantity <= 0:
            raise RobinhoodMcpError("quantity must be positive")
        if dollar_amount is not None and dollar_amount <= 0:
            raise RobinhoodMcpError("dollar_amount must be positive")
        if order_type == "limit" and (limit_price is None or limit_price <= 0):
            raise RobinhoodMcpError("limit orders require a positive limit_price")
        args: dict[str, Any] = {
            "account_number": self.resolve_account(),
            "symbol": symbol.upper(),
            "side": side,
            "type": order_type,
        }
        if quantity is not None:
            args["quantity"] = float(quantity)
        if dollar_amount is not None:
            args["dollar_amount"] = float(dollar_amount)
        if limit_price is not None:
            args["limit_price"] = float(limit_price)
        if ref_id is not None:
            args["ref_id"] = ref_id
        return args

    # -- read API -------------------------------------------------------------
    def get_accounts(self) -> Any:
        return _unwrap(self.call_tool(self.tools["get_accounts"], {}))

    def get_portfolio(self, account_number: str | None = None) -> Any:
        acct = account_number or self.resolve_account()
        return _unwrap(self.call_tool(self.tools["get_portfolio"], {"account_number": acct}))

    def get_equity_positions(self, account_number: str | None = None) -> Any:
        acct = account_number or self.resolve_account()
        return _unwrap(
            self.call_tool(self.tools["get_equity_positions"], {"account_number": acct})
        )

    def get_equity_quotes(self, symbols: list[str]) -> Any:
        return _unwrap(
            self.call_tool(
                self.tools["get_equity_quotes"],
                {"symbols": [s.upper() for s in symbols]},
            )
        )

    def get_equity_orders(
        self,
        account_number: str | None = None,
        *,
        state: str | None = None,
        symbol: str | None = None,
    ) -> Any:
        acct = account_number or self.resolve_account()
        args: dict[str, Any] = {"account_number": acct}
        if state:
            args["state"] = state
        if symbol:
            args["symbol"] = symbol.upper()
        return _unwrap(self.call_tool(self.tools["get_equity_orders"], args))

    def search(self, query: str) -> Any:
        return _unwrap(self.call_tool(self.tools["search"], {"query": query}))

    # -- trade API ------------------------------------------------------------
    def review_order(
        self,
        symbol: str,
        side: str,
        *,
        quantity: float | None = None,
        dollar_amount: float | None = None,
        order_type: str = "market",
        limit_price: float | None = None,
    ) -> Any:
        """Simulate an equity order (no state change) via ``review_equity_order``."""
        args = self._order_args(
            symbol, side, quantity=quantity, dollar_amount=dollar_amount,
            order_type=order_type, limit_price=limit_price,
        )
        return _unwrap(self.call_tool(self.tools["review_equity_order"], args))

    def place_order(
        self,
        symbol: str,
        side: str,
        *,
        quantity: float | None = None,
        dollar_amount: float | None = None,
        order_type: str = "market",
        limit_price: float | None = None,
        ref_id: str | None = None,
        skip_review: bool = False,
    ) -> Any:
        """Review (optional) then place an equity order. Requires ``TRADING_LIVE=1``."""
        if not self.live_enabled:
            raise RobinhoodMcpError("live trading disabled; set TRADING_LIVE=1 to enable")
        args = self._order_args(
            symbol, side, quantity=quantity, dollar_amount=dollar_amount,
            order_type=order_type, limit_price=limit_price,
            ref_id=ref_id or str(uuid.uuid4()),
        )
        if self.require_review and not skip_review:
            review_args = {k: v for k, v in args.items() if k != "ref_id"}
            review = _unwrap(self.call_tool(self.tools["review_equity_order"], review_args))
            if isinstance(review, dict) and review.get("error"):
                raise RobinhoodMcpError(f"order review failed: {review['error']}")
        return _unwrap(self.call_tool(self.tools["place_equity_order"], args))

    def cancel_order(self, order_id: str, account_number: str | None = None) -> Any:
        if not self.live_enabled:
            raise RobinhoodMcpError("live trading disabled; set TRADING_LIVE=1 to enable")
        acct = account_number or self.resolve_account()
        return _unwrap(
            self.call_tool(
                self.tools["cancel_equity_order"],
                {"account_number": acct, "order_id": order_id},
            )
        )

    # -- Broker surface (so the engine can route to it like PaperBroker) ------
    def buy(
        self,
        symbol: str,
        notional: float,
        price: float,
        *,
        on: str = "",
        strategy: str = "",
        reason: str = "",
    ) -> Fill | None:
        if notional <= 0 or price <= 0:
            return None
        quantity = notional / price
        self.place_order(symbol, "buy", quantity=quantity)
        return Fill(
            date=on,
            symbol=symbol,
            side="buy",
            quantity=round(quantity, 8),
            price=round(price, 6),
            notional=round(notional, 2),
            strategy=strategy or "robinhood-mcp",
            reason=reason,
        )

    def sell(
        self,
        symbol: str,
        quantity: float,
        price: float,
        *,
        on: str = "",
        strategy: str = "",
        reason: str = "",
    ) -> Fill | None:
        if quantity <= 0 or price <= 0:
            return None
        self.place_order(symbol, "sell", quantity=quantity)
        return Fill(
            date=on,
            symbol=symbol,
            side="sell",
            quantity=round(quantity, 8),
            price=round(price, 6),
            notional=round(quantity * price, 2),
            strategy=strategy or "robinhood-mcp",
            reason=reason,
        )
