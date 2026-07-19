"""Financial-health score and recommendations from a Profile.

Heuristics based on common personal-finance guidance (emergency fund, savings
rate, debt-to-income, high-interest debt). Educational only, not advice.
"""

from __future__ import annotations

from typing import Any

from gary.finance.models import Profile
from gary.finance.networth import net_worth

_HIGH_APR = 10.0


def _metrics(profile: Profile) -> dict[str, Any]:
    income = profile.monthly_income
    expenses = profile.monthly_expenses
    cash = sum(a.value for a in profile.assets if a.kind == "cash")
    total_debt = sum(d.balance for d in profile.debts)
    min_payments = sum(d.min_payment for d in profile.debts)

    savings_rate = ((income - expenses) / income) if income > 0 else 0.0
    emergency_months = (cash / expenses) if expenses > 0 else 0.0
    dti = (min_payments / income) if income > 0 else 0.0  # monthly debt-to-income
    return {
        "net_worth": net_worth(profile),
        "monthly_surplus": round(income - expenses, 2),
        "savings_rate": round(savings_rate, 3),
        "emergency_fund_months": round(emergency_months, 1),
        "debt_to_income": round(dti, 3),
        "total_debt": round(total_debt, 2),
        "cash": round(cash, 2),
    }


def financial_health(profile: Profile) -> dict[str, Any]:
    m = _metrics(profile)
    score = 0
    recs: list[dict[str, str]] = []

    def rec(priority: str, text: str) -> None:
        recs.append({"priority": priority, "text": text})

    # Emergency fund (0-25)
    ef = m["emergency_fund_months"]
    if ef >= 6:
        score += 25
    elif ef >= 3:
        score += 18
        rec("medium", f"Build your emergency fund from {ef:.1f} to 6 months of expenses.")
    else:
        score += max(0, int(ef / 3 * 12))
        rec("high", f"Emergency fund is only {ef:.1f} months. Aim for 3-6 months of expenses.")

    # Savings rate (0-25)
    sr = m["savings_rate"]
    if sr >= 0.20:
        score += 25
    elif sr >= 0.10:
        score += 18
        rec("medium", f"Savings rate is {sr*100:.0f}%. Push toward 20%+ to accelerate goals.")
    elif sr > 0:
        score += 10
        rec("high", f"Savings rate is only {sr*100:.0f}%. Trim expenses or grow income.")
    else:
        rec("high", "You are spending at or above your income. Cut expenses to free up cash.")

    # Debt-to-income (0-25)
    dti = m["debt_to_income"]
    if dti == 0:
        score += 25
    elif dti <= 0.20:
        score += 20
    elif dti <= 0.36:
        score += 12
        rec("medium", f"Debt payments are {dti*100:.0f}% of income. Keep below 36%.")
    else:
        score += 4
        rec("high", f"Debt payments are {dti*100:.0f}% of income (high). Prioritize payoff.")

    # High-interest debt (0-25)
    high = [d for d in profile.debts if d.apr >= _HIGH_APR and d.balance > 0]
    if not profile.debts:
        score += 25
    elif not high:
        score += 20
    else:
        score += 8
        worst = max(high, key=lambda d: d.apr)
        rec("high", f"Attack high-interest debt first: {worst.name} at {worst.apr:.1f}% APR "
                    "(avalanche method saves the most interest).")

    if m["net_worth"] < 0:
        rec("high", "Net worth is negative — focus on paying down debt before investing.")

    score = max(0, min(100, score))
    grade = next(g for cutoff, g in [(85, "A"), (70, "B"), (55, "C"), (40, "D"), (0, "F")]
                 if score >= cutoff)
    if not recs:
        rec("low", "Great shape! Keep investing and review annually.")

    return {"score": score, "grade": grade, "metrics": m, "recommendations": recs}
