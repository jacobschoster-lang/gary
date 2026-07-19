"""Plaid connector: pull real bank balances + transactions (issue: real data).

Talks to the Plaid REST API via httpx (no SDK dependency). Enabled only when
``PLAID_CLIENT_ID`` and ``PLAID_SECRET`` are set; otherwise ``from_env`` returns
None and the app falls back to manual entry / file import.

Config:
    PLAID_CLIENT_ID   (required to enable)
    PLAID_SECRET      (required to enable)
    PLAID_ENV         sandbox (default) | development | production
    PLAID_BASE_URL    optional explicit override

Flow: create_link_token -> (frontend Plaid Link) -> exchange_public_token ->
pull(access_token) which returns assets, debts, and transactions.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx

from gary.finance.models import Asset, Debt
from gary.finance.transactions import Transaction, categorize

_ENV_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "development": "https://development.plaid.com",
    "production": "https://production.plaid.com",
}


class PlaidError(RuntimeError):
    """Raised when a Plaid API call fails."""


@dataclass
class PlaidClient:
    client_id: str
    secret: str
    base_url: str = _ENV_HOSTS["sandbox"]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> PlaidClient | None:
        env = env if env is not None else dict(os.environ)
        client_id = env.get("PLAID_CLIENT_ID")
        secret = env.get("PLAID_SECRET")
        if not (client_id and secret):
            return None
        base = env.get("PLAID_BASE_URL") or _ENV_HOSTS.get(
            env.get("PLAID_ENV", "sandbox").lower(), _ENV_HOSTS["sandbox"]
        )
        return cls(client_id=client_id, secret=secret, base_url=base.rstrip("/"))

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {"client_id": self.client_id, "secret": self.secret, **payload}
        try:
            resp = httpx.post(f"{self.base_url}{path}", json=body, timeout=30.0)
        except httpx.HTTPError as exc:
            raise PlaidError(f"network error calling Plaid: {exc}") from exc
        if resp.status_code >= 400:
            try:
                err = resp.json()
                msg = err.get("error_message") or err.get("error_code") or resp.text
            except Exception:
                msg = resp.text
            raise PlaidError(f"Plaid {path} failed: {msg}")
        return resp.json()

    def create_link_token(self, user_id: str = "gary-user") -> str:
        data = self._post("/link/token/create", {
            "user": {"client_user_id": user_id},
            "client_name": "Stickfigure Finance",
            "products": ["transactions"],
            "country_codes": ["US"],
            "language": "en",
        })
        return data["link_token"]

    def exchange_public_token(self, public_token: str) -> str:
        data = self._post("/item/public_token/exchange", {"public_token": public_token})
        return data["access_token"]

    def get_accounts(self, access_token: str) -> tuple[list[Asset], list[Debt]]:
        data = self._post("/accounts/balance/get", {"access_token": access_token})
        assets: list[Asset] = []
        debts: list[Debt] = []
        for acct in data.get("accounts", []):
            name = acct.get("name") or acct.get("official_name") or "Account"
            atype = acct.get("type")
            balances = acct.get("balances", {})
            current = balances.get("current") or 0.0
            if atype in ("credit", "loan"):
                debts.append(Debt(name=name, balance=abs(float(current)), apr=0.0, min_payment=0.0))
            else:
                kind = "investment" if atype == "investment" else \
                    "cash" if atype == "depository" else "other"
                assets.append(Asset(name=name, value=float(current), kind=kind))
        return assets, debts

    def get_transactions(self, access_token: str, days: int = 90) -> list[Transaction]:
        end = date.today()
        start = end - timedelta(days=days)
        data = self._post("/transactions/get", {
            "access_token": access_token,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "options": {"count": 250, "offset": 0},
        })
        txns: list[Transaction] = []
        for t in data.get("transactions", []):
            # Plaid: positive amount = money out; negate for our convention.
            amount = round(-float(t.get("amount", 0.0)), 2)
            desc = t.get("merchant_name") or t.get("name") or "Transaction"
            txns.append(Transaction(
                date=str(t.get("date", "")),
                description=desc,
                amount=amount,
                category=categorize(desc, amount),
            ))
        return txns

    def pull(
        self, access_token: str, days: int = 90
    ) -> tuple[list[Asset], list[Debt], list[Transaction]]:
        assets, debts = self.get_accounts(access_token)
        txns = self.get_transactions(access_token, days=days)
        return assets, debts, txns


class PlaidTokenStore:
    """Persists the Plaid access token(s) locally (gitignored)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("GARY_PLAID_FILE", "finance_data/plaid.json"))

    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8")).get("items", [])
        except (json.JSONDecodeError, OSError):
            return []

    def add(self, access_token: str, institution: str = "bank") -> None:
        items = self.load()
        items.append({"access_token": access_token, "institution": institution})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")

    def access_tokens(self) -> list[str]:
        return [i["access_token"] for i in self.load() if i.get("access_token")]

    def linked(self) -> bool:
        return bool(self.access_tokens())
