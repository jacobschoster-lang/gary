"""Compounding goal-projection math for planning a path to wealth targets.

Given a starting balance, a monthly contribution, and an annual return, these
pure functions project account growth and answer the two planning questions:
how many years to hit a target (e.g. $1M, $18M), and what annual return is
required to hit a target within a fixed horizon.

Contributions compound MONTHLY (12 periods/year) at the end of each month, and
``annual_return`` is a decimal (``0.10`` = 10%/yr) converted to a monthly rate
via ``(1 + annual_return)**(1/12) - 1``.

Everything here is pure: no I/O, no network, standard library only. Inputs are
handled defensively -- degenerate inputs return sensible values (``start``,
``0.0``, or ``None`` on non-convergence) rather than raising.
"""

from __future__ import annotations


def monthly_rate(annual_return: float) -> float:
    """(1+annual_return)**(1/12) - 1."""
    base = 1.0 + annual_return
    if base <= 0:
        return -1.0
    return base ** (1.0 / 12.0) - 1.0


def future_value(
    start: float,
    monthly_contribution: float,
    annual_return: float,
    years: float,
) -> float:
    """Balance after ``years`` with monthly compounding and end-of-month contributions."""
    if years <= 0:
        return start
    months = round(years * 12)
    if months <= 0:
        return start
    m = monthly_rate(annual_return)
    value = start
    for _ in range(months):
        value = value * (1.0 + m) + monthly_contribution
    return value


def project_path(
    start: float,
    monthly_contribution: float,
    annual_return: float,
    years: float,
) -> list[dict]:
    """Month-by-month path: list of {'month': int (1..N), 'value': float rounded 2dp}.

    ``N = round(years * 12)``. Empty list if ``N <= 0``.
    """
    months = round(years * 12) if years > 0 else 0
    if months <= 0:
        return []
    m = monthly_rate(annual_return)
    path: list[dict] = []
    value = start
    for month in range(1, months + 1):
        value = value * (1.0 + m) + monthly_contribution
        path.append({"month": month, "value": round(value, 2)})
    return path


def years_to_target(
    start: float,
    monthly_contribution: float,
    annual_return: float,
    target: float,
    max_years: float = 100.0,
) -> float | None:
    """Fractional years to reach ``target`` (month granularity, returned as months/12).

    ``None`` if not reached within ``max_years``. If already ``>= target``, return 0.0.
    """
    if start >= target:
        return 0.0
    max_months = round(max_years * 12) if max_years > 0 else 0
    if max_months <= 0:
        return None
    m = monthly_rate(annual_return)
    value = start
    for month in range(1, max_months + 1):
        value = value * (1.0 + m) + monthly_contribution
        if value >= target:
            return month / 12.0
    return None


def required_return(
    start: float,
    monthly_contribution: float,
    target: float,
    years: float,
    lo: float = -0.5,
    hi: float = 3.0,
    tol: float = 1e-4,
) -> float | None:
    """Annual return needed to reach ``target`` in ``years``, via bisection on future_value.

    ``None`` if even ``hi`` can't reach it (or ``years <= 0``).
    ``future_value`` is monotonically increasing in the annual return, so
    bisection converges.
    """
    if years <= 0:
        return None
    if future_value(start, monthly_contribution, hi, years) < target:
        return None
    if future_value(start, monthly_contribution, lo, years) >= target:
        return lo
    low, high = lo, hi
    while high - low > tol:
        mid = (low + high) / 2.0
        if future_value(start, monthly_contribution, mid, years) >= target:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


def goal_summary(
    start: float,
    monthly_contribution: float,
    annual_return: float,
    targets: list[float],
) -> dict:
    """Summarize progress toward each target at a fixed annual return.

    Returns::

        {
            'annual_return': ...,
            'targets': [
                {'target': T, 'years_to_target': y_or_None, 'future_value_10y': fv},
                ...
            ],
        }

    Floats are rounded to 2 dp; ``years_to_target`` is rounded to 2 dp or ``None``.
    """
    fv_10y = round(future_value(start, monthly_contribution, annual_return, 10.0), 2)
    entries: list[dict] = []
    for target in targets:
        y = years_to_target(start, monthly_contribution, annual_return, target)
        entries.append(
            {
                "target": round(float(target), 2),
                "years_to_target": round(y, 2) if y is not None else None,
                "future_value_10y": fv_10y,
            }
        )
    return {
        "annual_return": round(annual_return, 2),
        "targets": entries,
    }
