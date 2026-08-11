from __future__ import annotations

import math

from gary.research.projection import (
    future_value,
    goal_summary,
    monthly_rate,
    project_path,
    required_return,
    years_to_target,
)


def test_monthly_rate_zero():
    assert monthly_rate(0.0) == 0.0


def test_monthly_rate_twelve_percent_annualizes():
    # An annual return of ~12.6825% corresponds to a ~1%/month compounding rate.
    assert abs(monthly_rate(0.1268250301) - 0.01) < 1e-6
    # A 12%/yr return is roughly 0.949%/month.
    assert abs(monthly_rate(0.12) - 0.0094888) < 1e-5


def test_future_value_zero_return_is_sum_of_contributions():
    assert future_value(0.0, 100.0, 0.0, 1.0) == 1200.0


def test_future_value_years_zero_returns_start():
    assert future_value(5000.0, 100.0, 0.10, 0.0) == 5000.0


def test_future_value_positive_return_beats_contributions():
    # With a positive return, the balance exceeds the plain sum of contributions.
    contributed = 100.0 * 12 * 5
    fv = future_value(0.0, 100.0, 0.08, 5.0)
    assert fv > contributed


def test_project_path_length_and_shape():
    path = project_path(1000.0, 50.0, 0.06, 2.0)
    assert len(path) == 24
    assert path[0]["month"] == 1
    assert path[-1]["month"] == 24
    for row in path:
        assert set(row.keys()) == {"month", "value"}
        assert isinstance(row["month"], int)
        # value is rounded to 2dp
        assert round(row["value"], 2) == row["value"]
    # Monotonically increasing with positive return + contributions.
    values = [row["value"] for row in path]
    assert values == sorted(values)


def test_project_path_empty_when_no_months():
    assert project_path(1000.0, 50.0, 0.06, 0.0) == []


def test_project_path_last_value_matches_future_value():
    start, contrib, annual, years = 2000.0, 75.0, 0.07, 3.0
    path = project_path(start, contrib, annual, years)
    assert abs(path[-1]["value"] - round(future_value(start, contrib, annual, years), 2)) < 0.01


def test_years_to_target_already_reached():
    assert years_to_target(1_000_000.0, 500.0, 0.08, 1_000_000.0) == 0.0
    assert years_to_target(2_000_000.0, 500.0, 0.08, 1_000_000.0) == 0.0


def test_years_to_target_unreachable_returns_none():
    # Tiny contribution and zero growth cannot reach a huge target within max_years.
    assert years_to_target(0.0, 1.0, 0.0, 18_000_000.0, max_years=100.0) is None


def test_years_to_target_reachable_is_positive_finite():
    y = years_to_target(10_000.0, 1000.0, 0.08, 1_000_000.0)
    assert y is not None
    assert y > 0.0
    assert math.isfinite(y)


def test_years_to_target_higher_return_is_faster():
    slow = years_to_target(10_000.0, 1000.0, 0.04, 1_000_000.0)
    fast = years_to_target(10_000.0, 1000.0, 0.12, 1_000_000.0)
    assert slow is not None and fast is not None
    assert fast < slow


def test_required_return_round_trips():
    start, contrib, years, target = 10_000.0, 1000.0, 20.0, 1_000_000.0
    r = required_return(start, contrib, target, years)
    assert r is not None
    fv = future_value(start, contrib, r, years)
    # Solved return should reach the target (within a small tolerance band).
    assert fv >= target * (1 - 1e-3)


def test_required_return_none_when_impossible():
    # No return within [lo, hi] can turn tiny inputs into $18M in one year.
    assert required_return(100.0, 10.0, 18_000_000.0, 1.0) is None


def test_required_return_none_when_years_nonpositive():
    assert required_return(10_000.0, 1000.0, 1_000_000.0, 0.0) is None


def test_required_return_monotonic_reach():
    # A higher required return, plugged into future_value, must reach a higher target.
    start, contrib, years = 5000.0, 500.0, 15.0
    low_target, high_target = 200_000.0, 800_000.0
    r_low = required_return(start, contrib, low_target, years)
    r_high = required_return(start, contrib, high_target, years)
    assert r_low is not None and r_high is not None
    assert r_high >= r_low


def test_goal_summary_structure():
    targets = [1_000_000.0, 18_000_000.0]
    summary = goal_summary(50_000.0, 2000.0, 0.10, targets)
    assert set(summary.keys()) == {"annual_return", "targets"}
    assert summary["annual_return"] == 0.1
    assert len(summary["targets"]) == len(targets)
    for entry, target in zip(summary["targets"], targets, strict=True):
        assert set(entry.keys()) == {"target", "years_to_target", "future_value_10y"}
        assert entry["target"] == round(target, 2)
        assert entry["years_to_target"] is None or isinstance(entry["years_to_target"], float)
        assert isinstance(entry["future_value_10y"], float)
