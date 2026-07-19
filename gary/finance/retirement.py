"""Retirement / savings planning.

Projects retirement savings to the retirement age (compounding current
investment balances + monthly contributions), compares against the nest egg
needed using the 4% rule, and recommends a monthly savings target to close any
gap. Educational only, not financial advice.
"""

from __future__ import annotations

from typing import Any

from gary.finance.models import Profile

DEFAULT_RETURN = 0.07  # nominal annual return
DEFAULT_WITHDRAWAL = 0.04  # 4% safe withdrawal rule
DEFAULT_INCOME_REPLACEMENT = 0.80  # fraction of current spending needed in retirement


def _fv_lump(principal: float, monthly_rate: float, months: int) -> float:
    return principal * ((1 + monthly_rate) ** months)


def _fv_annuity(payment: float, monthly_rate: float, months: int) -> float:
    if monthly_rate == 0:
        return payment * months
    return payment * (((1 + monthly_rate) ** months - 1) / monthly_rate)


def retirement_plan(
    profile: Profile,
    annual_return: float = DEFAULT_RETURN,
    withdrawal_rate: float = DEFAULT_WITHDRAWAL,
    income_replacement: float = DEFAULT_INCOME_REPLACEMENT,
) -> dict[str, Any]:
    age = profile.age or 0
    retirement_age = profile.retirement_age or 65
    years = max(0, retirement_age - age)
    months = years * 12
    mr = annual_return / 12.0

    current_savings = round(sum(a.value for a in profile.assets if a.kind == "investment"), 2)
    contribution = profile.monthly_retirement_contribution
    annual_expenses = profile.monthly_expenses * 12.0
    target_annual_income = annual_expenses * income_replacement
    nest_egg_needed = round(target_annual_income / withdrawal_rate, 2) if withdrawal_rate else 0.0

    projected = round(
        _fv_lump(current_savings, mr, months) + _fv_annuity(contribution, mr, months), 2
    )
    gap = round(nest_egg_needed - projected, 2)
    on_track = projected >= nest_egg_needed

    factor = (((1 + mr) ** months - 1) / mr) if mr and months else float(months or 1)
    extra_monthly = round(max(0.0, gap) / factor, 2) if factor else 0.0
    recommended_monthly = round(contribution + extra_monthly, 2)

    # Year-by-year projection for charting.
    projection: list[dict[str, Any]] = []
    balance = current_savings
    for y in range(years + 1):
        projection.append({"age": age + y, "balance": round(balance, 2)})
        for _ in range(12):
            balance = balance * (1 + mr) + contribution

    recommendations: list[dict[str, str]] = []
    if age <= 0:
        recommendations.append({
            "priority": "medium",
            "text": "Enter your age to get a personalized retirement projection.",
        })
    elif on_track:
        recommendations.append({
            "priority": "low",
            "text": f"On track: projected ${projected:,.0f} at {retirement_age} "
                    f"vs. ${nest_egg_needed:,.0f} needed. Keep it up.",
        })
    else:
        recommendations.append({
            "priority": "high",
            "text": f"Projected ${projected:,.0f} at {retirement_age} is short of the "
                    f"${nest_egg_needed:,.0f} needed. Save ~${recommended_monthly:,.0f}/mo "
                    f"(+${extra_monthly:,.0f}) to close the gap.",
        })
        if profile.monthly_income:
            pct = recommended_monthly / profile.monthly_income
            recommendations.append({
                "priority": "medium",
                "text": f"That is ~{pct*100:.0f}% of your income; aim for 15%+ toward retirement.",
            })

    return {
        "age": age,
        "retirement_age": retirement_age,
        "years_to_retirement": years,
        "current_retirement_savings": current_savings,
        "monthly_contribution": round(contribution, 2),
        "assumed_annual_return": annual_return,
        "nest_egg_needed": nest_egg_needed,
        "projected_savings": projected,
        "gap": gap,
        "on_track": on_track,
        "recommended_monthly_contribution": recommended_monthly,
        "additional_monthly_needed": extra_monthly,
        "projection": projection,
        "recommendations": recommendations,
    }
