"""Tests for the factor backtester, research harness, and API.

The autouse offline fixture forces the deterministic synthetic price series, so
these are reproducible without network.
"""

from fastapi.testclient import TestClient

from gary.app import app
from gary.research.backtest import FactorConfig, buy_hold_return, run_factor
from gary.research.harness import candidate_configs, research

client = TestClient(app)


def _panel(n=400):
    # Two deterministic ramps + one flat series (enough symbols to rank).
    return {
        "UP": [100 + i for i in range(n)],
        "UP2": [100 + 0.5 * i for i in range(n)],
        "FLAT": [100.0 for _ in range(n)],
        "DOWN": [max(1.0, 300 - 0.3 * i) for i in range(n)],
    }


def test_run_factor_produces_curve_and_metrics():
    panel = _panel()
    rebar = list(range(205, 400, 21))
    rep = run_factor(panel, FactorConfig(factor="trend"), rebar)
    assert rep["rebalances"] >= 1
    assert "metrics" in rep and "sharpe" in rep["metrics"]
    assert "benchmark_return_pct" in rep
    assert len(rep["period_returns"]) == rep["rebalances"]


def test_buy_hold_return_basic():
    panel = {"A": [100, 110, 120], "B": [100, 100, 100]}
    assert round(buy_hold_return(panel, 0, 2), 4) == 0.10  # mean of +20% and 0%


def test_candidate_grid_size():
    assert len(candidate_configs()) == 12  # 6 factors x {long, long/short}


def test_research_harness_holdout_and_projection():
    r1 = research(years=5, use_live=False)
    r2 = research(years=5, use_live=False)
    assert r1["n_trials"] == 12
    assert len(r1["factors"]) == 12
    # Deterministic offline.
    assert r1["chosen_cagr_pct"] == r2["chosen_cagr_pct"]
    # A locked out-of-sample holdout is reported separately from the research window.
    assert "holdout" in r1 and "benchmark_return_pct" in r1["holdout"]
    assert r1["holdout"]["rebalances"] >= 1
    # Honest projection has both an optimistic and a market-baseline path.
    proj = r1["projection"]
    assert proj["market_baseline"]["annual_return"] == 0.08
    targets = [t["target"] for t in proj["market_baseline"]["targets"]]
    assert 1_000_000.0 in targets and 18_000_000.0 in targets


def test_deflated_sharpe_is_not_above_raw():
    r = research(years=5, use_live=False)
    for f in r["factors"]:
        assert f["deflated_sharpe"] <= f["sharpe"] + 1e-9  # multiple-testing haircut


def test_holdout_regime_split_present_when_survivors():
    r = research(years=5, use_live=False)
    if r["survivors"]:
        assert r["holdout"]["combined"] is not None
        reg = r["holdout"]["regime"]
        assert reg is not None and "bull_return_pct" in reg and "bear_return_pct" in reg


def test_api_research_factors():
    resp = client.post("/api/research/factors", json={"years": 5, "start": 10000,
                                                      "monthly_contribution": 2000,
                                                      "offline": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["n_trials"] == 12 and "verdict" in body
    assert "holdout" in body and "projection" in body and "data" in body
