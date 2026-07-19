"""Data models for the personal-finance module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from gary.finance.transactions import Transaction

AssetKind = Literal["cash", "investment", "property", "other"]


@dataclass
class Asset:
    name: str
    value: float
    kind: AssetKind = "other"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Debt:
    name: str
    balance: float
    apr: float  # annual percentage rate, e.g. 19.99
    min_payment: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Profile:
    monthly_income: float = 0.0
    monthly_expenses: float = 0.0
    extra_debt_payment: float = 0.0
    assets: list[Asset] = field(default_factory=list)
    debts: list[Debt] = field(default_factory=list)
    networth_history: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[Transaction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "monthly_income": self.monthly_income,
            "monthly_expenses": self.monthly_expenses,
            "extra_debt_payment": self.extra_debt_payment,
            "assets": [a.to_dict() for a in self.assets],
            "debts": [d.to_dict() for d in self.debts],
            "networth_history": self.networth_history,
            "transactions": [t.to_dict() for t in self.transactions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Profile:
        from gary.finance.transactions import Transaction

        data = data or {}
        return cls(
            monthly_income=float(data.get("monthly_income", 0) or 0),
            monthly_expenses=float(data.get("monthly_expenses", 0) or 0),
            extra_debt_payment=float(data.get("extra_debt_payment", 0) or 0),
            assets=[
                Asset(
                    name=str(a.get("name", "")),
                    value=float(a.get("value", 0) or 0),
                    kind=a.get("kind", "other"),
                )
                for a in data.get("assets", [])
            ],
            debts=[
                Debt(
                    name=str(d.get("name", "")),
                    balance=float(d.get("balance", 0) or 0),
                    apr=float(d.get("apr", 0) or 0),
                    min_payment=float(d.get("min_payment", 0) or 0),
                )
                for d in data.get("debts", [])
            ],
            networth_history=list(data.get("networth_history", [])),
            transactions=[
                Transaction(
                    date=str(t.get("date", "")),
                    description=str(t.get("description", "")),
                    amount=float(t.get("amount", 0) or 0),
                    category=str(t.get("category", "Other")),
                )
                for t in data.get("transactions", [])
            ],
        )
