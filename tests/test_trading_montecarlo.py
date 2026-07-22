from __future__ import annotations

import pytest

from gary.trading import montecarlo as mc


def test_simulate_paths_shape_and_movement():
    pnls = [10.0, -5.0, 3.0]
    paths = mc.simulate_paths(pnls, starting_equity=100.0, n_paths=50, seed=1)
    assert len(paths) == 50
    assert all(len(path) == len(pnls) for path in paths)

    # Every step moves by one of the resampled pnls, starting from equity.
    for path in paths:
        prev = 100.0
        for value in path:
            assert round(value - prev, 6) in {10.0, -5.0, 3.0}
            prev = value


def test_simulate_paths_custom_path_len():
    paths = mc.simulate_paths([1.0, 2.0], starting_equity=10.0, n_paths=5, path_len=7, seed=0)
    assert len(paths) == 5
    assert all(len(path) == 7 for path in paths)


def test_simulate_paths_degenerate_inputs():
    assert mc.simulate_paths([], 100.0) == []
    assert mc.simulate_paths([1.0], 100.0, n_paths=0) == []
    assert mc.simulate_paths([1.0], 100.0, path_len=0) == []


def test_determinism_same_seed():
    pnls = [4.0, -2.0, 1.0, -3.0, 6.0]
    a = mc.summarize(pnls, 100.0, goal_equity=120.0, seed=42, n_paths=500)
    b = mc.summarize(pnls, 100.0, goal_equity=120.0, seed=42, n_paths=500)
    assert a == b


def test_different_seed_may_differ():
    pnls = [4.0, -2.0, 1.0, -3.0, 6.0]
    a = mc.summarize(pnls, 100.0, goal_equity=120.0, seed=1, n_paths=500)
    b = mc.summarize(pnls, 100.0, goal_equity=120.0, seed=2, n_paths=500)
    # Not a hard guarantee, but with this data the seeds should diverge.
    assert a != b


def test_all_positive_high_goal_prob_and_no_ruin():
    pnls = [5.0, 8.0, 3.0, 10.0]
    summary = mc.summarize(pnls, 100.0, goal_equity=101.0, n_paths=1000, seed=0)
    assert summary["prob_reach_goal_pct"] == 100.0
    assert summary["risk_of_ruin_pct"] == 0.0
    assert summary["median_final_equity"] > 100.0
    assert summary["mean_return_pct"] > 0.0


def test_all_negative_high_ruin_and_no_goal():
    pnls = [-5.0, -8.0, -3.0, -10.0]
    summary = mc.summarize(pnls, 100.0, goal_equity=110.0, n_paths=1000, path_len=30, seed=0)
    # Ruin defaults to 0.5*start = 50; with only losses over 30 trades every
    # path is well below that, and no path reaches the goal above start.
    assert summary["risk_of_ruin_pct"] == 100.0
    assert summary["prob_reach_goal_pct"] == 0.0
    assert summary["median_return_pct"] < 0.0


def test_empty_summarize_zeros_without_raising():
    summary = mc.summarize([], 100.0, goal_equity=120.0)
    assert summary["paths"] == 0
    assert summary["trades_per_path"] == 0
    assert summary["prob_reach_goal_pct"] == 0.0
    assert summary["risk_of_ruin_pct"] == 0.0
    assert summary["median_return_pct"] == 0.0
    assert summary["mean_return_pct"] == 0.0
    assert summary["median_final_equity"] == 100.0
    assert summary["p5_final_equity"] == 100.0
    assert summary["p95_final_equity"] == 100.0


def test_final_equities():
    paths = [[10.0, 12.0], [5.0], []]
    assert mc.final_equities(paths, starting_equity=100.0) == [12.0, 5.0, 100.0]


def test_probability_reach_goal():
    paths = [[110.0], [90.0], [120.0], [100.0]]
    assert mc.probability_reach_goal(paths, goal_equity=100.0) == 75.0
    assert mc.probability_reach_goal([], goal_equity=100.0) == 0.0


def test_risk_of_ruin_touches_along_path():
    # First path ends below 50; second dips to 40 mid-path even though it
    # recovers to 105; third never approaches ruin.
    paths = [[90.0, 70.0, 45.0], [90.0, 40.0, 105.0], [110.0, 120.0, 130.0]]
    assert mc.risk_of_ruin(paths, ruin_equity=50.0) == pytest.approx(2 / 3 * 100.0)
    assert mc.risk_of_ruin([], ruin_equity=50.0) == 0.0


def test_percentile_interpolation_and_empty():
    result = mc.percentile([1.0, 2.0, 3.0, 4.0], 50.0)
    assert 2.0 < result < 3.0
    assert mc.percentile([], 50.0) == 0.0
    assert mc.percentile([7.0], 90.0) == 7.0
    assert mc.percentile([1.0, 2.0, 3.0, 4.0], 0.0) == 1.0
    assert mc.percentile([1.0, 2.0, 3.0, 4.0], 100.0) == 4.0


def test_summarize_rounding_and_keys():
    pnls = [3.0, -1.0, 2.0]
    summary = mc.summarize(pnls, 100.0, goal_equity=105.0, n_paths=200, seed=7)
    expected_keys = {
        "paths",
        "trades_per_path",
        "prob_reach_goal_pct",
        "risk_of_ruin_pct",
        "median_final_equity",
        "p5_final_equity",
        "p95_final_equity",
        "median_return_pct",
        "mean_return_pct",
    }
    assert set(summary) == expected_keys
    assert summary["paths"] == 200
    assert summary["trades_per_path"] == 3
    for key in expected_keys - {"paths", "trades_per_path"}:
        assert round(summary[key], 2) == summary[key]
