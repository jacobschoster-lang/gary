"""Local JSON persistence for the finance profile.

No bank access — this just saves/loads what the user enters so net-worth history
survives restarts. Path is configurable via ``GARY_FINANCE_FILE``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from gary.finance.models import Asset, Debt, Profile

_DEFAULT_PATH = os.environ.get("GARY_FINANCE_FILE", "finance_data/profile.json")


class ProfileStore:
    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self.path = Path(path)

    def load(self) -> Profile:
        if not self.path.exists():
            return Profile()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return Profile()
        return Profile.from_dict(data)

    def save(self, profile: Profile) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")


def sample_profile() -> Profile:
    """A realistic starter profile users can load and then edit."""
    return Profile(
        monthly_income=6000.0,
        monthly_expenses=4200.0,
        extra_debt_payment=400.0,
        age=34,
        retirement_age=65,
        monthly_retirement_contribution=300.0,
        assets=[
            Asset("Checking + Savings", 9000.0, "cash"),
            Asset("401(k)", 32000.0, "investment"),
            Asset("Brokerage", 8000.0, "investment"),
            Asset("Car", 15000.0, "property"),
        ],
        debts=[
            # Note: the smallest balance (Store Card) is NOT the highest APR
            # (Credit Card), so avalanche and snowball differ.
            Debt("Store Card", 2000.0, 12.0, 45.0),
            Debt("Credit Card", 6500.0, 22.99, 150.0),
            Debt("Student Loan", 18000.0, 4.5, 190.0),
        ],
    )
