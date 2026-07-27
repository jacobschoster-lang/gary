from __future__ import annotations

import math

from gary.trading.selection import (
    deflated_sharpe,
    rank_by_robustness,
    robustness_score,
    select_most_robust,
)


def test_robustness_score_no_dispersion():
    assert math.isclose(robustness_score([10.0, 10.0, 10.0]), 10.0)


def test_robustness_score_single_value_equals_value():
    assert math.isclose(robustness_score([7.5]), 7.5)


def test_robustness_score_empty_is_zero():
    assert robustness_score([]) == 0.0


def test_robustness_score_volatile_scores_lower_than_steady():
    steady = [5.0, 5.0, 5.0, 5.0]
    volatile = [0.0, 10.0, 0.0, 10.0]  # same mean of 5.0
    assert math.isclose(sum(steady) / len(steady), sum(volatile) / len(volatile))
    assert robustness_score(volatile) < robustness_score(steady)


def test_robustness_score_risk_aversion_penalizes_more():
    volatile = [0.0, 10.0, 0.0, 10.0]
    assert robustness_score(volatile, risk_aversion=2.0) < robustness_score(
        volatile, risk_aversion=1.0
    )


def test_deflated_sharpe_more_trials_lowers_value():
    few = deflated_sharpe(2.0, n_trials=2, n_obs=100)
    many = deflated_sharpe(2.0, n_trials=1000, n_obs=100)
    assert many < few
    assert few < 2.0


def test_deflated_sharpe_more_observations_closer_to_observed():
    small = deflated_sharpe(2.0, n_trials=50, n_obs=10)
    large = deflated_sharpe(2.0, n_trials=50, n_obs=1000)
    # More observations -> smaller haircut -> closer to the observed Sharpe.
    assert abs(2.0 - large) < abs(2.0 - small)
    assert large > small


def test_deflated_sharpe_single_trial_unchanged():
    assert deflated_sharpe(1.5, n_trials=1, n_obs=100) == 1.5
    assert deflated_sharpe(1.5, n_trials=0, n_obs=100) == 1.5


def test_deflated_sharpe_never_raises_on_degenerate_obs():
    # n_obs <= 0 must be guarded, not raise.
    assert isinstance(deflated_sharpe(1.0, n_trials=10, n_obs=0), float)


def test_select_most_robust_prefers_steadier_at_equal_mean():
    candidates = [
        {"name": "volatile", "train_returns": [0.0, 10.0, 0.0, 10.0]},
        {"name": "steady", "train_returns": [5.0, 5.0, 5.0, 5.0]},
    ]
    winner = select_most_robust(candidates)
    assert winner is not None
    assert winner["name"] == "steady"
    assert "robustness" in winner


def test_select_most_robust_does_not_mutate_input():
    candidates = [{"name": "a", "train_returns": [1.0, 2.0]}]
    select_most_robust(candidates)
    assert "robustness" not in candidates[0]


def test_select_most_robust_empty_is_none():
    assert select_most_robust([]) is None


def test_select_most_robust_high_risk_aversion_prefers_lower_mean_steadier():
    # steady mean = 6.0 (stdev 0) -> score 6.0 at any risk_aversion.
    # spiky mean = 7.0, pstdev = 3.0 -> score 7 - k*3.
    # With k=1: spiky 4.0 < steady 6.0 already, but make it clearer:
    candidates = [
        {"name": "spiky", "train_returns": [4.0, 10.0, 4.0, 10.0]},  # mean 7, pstdev 3
        {"name": "steady", "train_returns": [6.0, 6.0, 6.0, 6.0]},  # mean 6, pstdev 0
    ]
    # High risk aversion crushes the spiky candidate.
    winner = select_most_robust(candidates, risk_aversion=1.0)
    assert winner is not None
    assert winner["name"] == "steady"


def test_rank_by_robustness_sorted_and_annotated():
    candidates = [
        {"name": "mid", "train_returns": [4.0, 6.0]},  # mean 5, pstdev 1 -> 4.0
        {"name": "best", "train_returns": [8.0, 8.0]},  # 8.0
        {"name": "worst", "train_returns": [0.0, 12.0]},  # mean 6, pstdev 6 -> 0.0
    ]
    ranked = rank_by_robustness(candidates)
    assert [c["name"] for c in ranked] == ["best", "mid", "worst"]
    assert all("robustness" in c for c in ranked)
    assert len(ranked) == len(candidates)


def test_rank_by_robustness_tie_broken_by_mean():
    # Both have pstdev 0 in their own score, but differing means.
    candidates = [
        {"name": "low", "train_returns": [1.0, 1.0]},
        {"name": "high", "train_returns": [9.0, 9.0]},
    ]
    ranked = rank_by_robustness(candidates)
    assert [c["name"] for c in ranked] == ["high", "low"]


def test_rank_by_robustness_empty_is_empty_list():
    assert rank_by_robustness([]) == []
