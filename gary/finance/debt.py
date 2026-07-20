"""Debt payoff planning: avalanche (highest APR) vs snowball (smallest balance).

Simulates month by month with interest accrual and a constant monthly budget
(sum of minimum payments + a fixed extra), rolling freed-up payments into the
next target debt.
"""

from __future__ import annotations

from typing import Any, Literal

from gary.finance.models import Debt

Strategy = Literal["avalanche", "snowball"]
_MAX_MONTHS = 1200  # 100 years cap to guard against non-converging inputs
_TIMELINE_DISPLAY_CAP = 120


def _order(debts: list[Debt], strategy: Strategy) -> list[int]:
    idx = list(range(len(debts)))
    if strategy == "avalanche":
        idx.sort(key=lambda i: debts[i].apr, reverse=True)
    else:  # snowball
        idx.sort(key=lambda i: debts[i].balance)
    return idx


def payoff_plan(
    debts: list[Debt],
    extra: float = 0.0,
    strategy: Strategy = "avalanche",
) -> dict[str, Any]:
    if strategy not in ("avalanche", "snowball"):
        raise ValueError(f"unknown strategy: {strategy!r}")
    if extra < 0:
        raise ValueError("extra must be >= 0")

    active = [{"name": d.name, "balance": float(d.balance), "apr": float(d.apr),
              "min": float(d.min_payment)} for d in debts if d.balance > 0]
    if not active:
        return {
            "strategy": strategy, "months": 0, "duration": "0 months",
            "total_interest": 0.0, "total_paid": 0.0, "order": [],
            "payoff_month": {}, "timeline": [], "timeline_truncated": False, "converged": True,
        }

    order = _order([Debt(a["name"], a["balance"], a["apr"], a["min"]) for a in active], strategy)
    budget = sum(a["min"] for a in active) + extra

    total_interest = 0.0
    total_paid = 0.0
    payoff_month: dict[str, int] = {}
    timeline: list[float] = []
    months = 0

    while any(a["balance"] > 0.005 for a in active) and months < _MAX_MONTHS:
        timeline.append(round(sum(max(a["balance"], 0) for a in active), 2))
        months += 1
        # Accrue interest.
        for a in active:
            if a["balance"] > 0:
                interest = a["balance"] * a["apr"] / 1200.0
                a["balance"] += interest
                total_interest += interest

        pool = budget
        # Pay minimums first.
        for a in active:
            if a["balance"] <= 0:
                continue
            pay = min(a["min"], a["balance"], pool)
            a["balance"] -= pay
            pool -= pay
            total_paid += pay

        # Roll remaining pool into debts by strategy priority.
        for i in order:
            if pool <= 0:
                break
            a = active[i]
            if a["balance"] <= 0:
                continue
            pay = min(a["balance"], pool)
            a["balance"] -= pay
            pool -= pay
            total_paid += pay

        for a in active:
            if a["balance"] <= 0.005 and a["name"] not in payoff_month:
                payoff_month[a["name"]] = months

    converged = all(a["balance"] <= 0.005 for a in active)
    if timeline and timeline[-1] > 0.005:
        timeline.append(0.0)
    truncated = len(timeline) > _TIMELINE_DISPLAY_CAP or not converged
    display_timeline = timeline[:_TIMELINE_DISPLAY_CAP]
    if truncated and timeline and (not display_timeline or display_timeline[-1] != timeline[-1]):
        display_timeline = [*display_timeline, timeline[-1]]
    return {
        "strategy": strategy,
        "months": months,
        "duration": _humanize(months),
        "total_interest": round(total_interest, 2),
        "total_paid": round(total_paid, 2),
        "monthly_budget": round(budget, 2),
        "order": [active[i]["name"] for i in order],
        "payoff_month": payoff_month,
        "timeline": display_timeline,
        "timeline_truncated": truncated,
        "converged": converged,
    }


def compare_strategies(debts: list[Debt], extra: float = 0.0) -> dict[str, Any]:
    avalanche = payoff_plan(debts, extra, "avalanche")
    snowball = payoff_plan(debts, extra, "snowball")
    interest_saved = round(snowball["total_interest"] - avalanche["total_interest"], 2)
    return {
        "avalanche": avalanche,
        "snowball": snowball,
        "interest_saved_with_avalanche": interest_saved,
        "recommended": "avalanche" if interest_saved >= 0 else "snowball",
    }


def _humanize(months: int) -> str:
    if months <= 0:
        return "0 months"
    years, rem = divmod(months, 12)
    parts = []
    if years:
        parts.append(f"{years} yr" + ("s" if years != 1 else ""))
    if rem:
        parts.append(f"{rem} mo" + ("s" if rem != 1 else ""))
    return " ".join(parts) or "0 months"
