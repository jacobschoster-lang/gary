"""Tests for option strategies, the options backtester, and its optimizer.

The autouse offline fixture forces the deterministic synthetic price series, so
every backtest here is reproducible without network access.
"""

from fastapi.testclient import TestClient

from gary.app import app
from gary.trading.option_strategies import build, payoff_at, payoff_curve
from gary.trading.options_backtest import (
    OptionsBacktester,
    OptionsConfig,
    OptionsPaperTrader,
    OptionsStore,
)
from gary.trading.options_optimize import candidate_configs, optimize

client = TestClient(app)


# ---------- strategy builders ----------
def test_iron_condor_is_defined_risk_credit():
    s = build("iron_condor", S=100, r=0.04, t=0.1, sigma=0.3, moneyness=0.05, width=0.05)
    assert len(s["legs"]) == 4
    assert s["entry_credit"] > 0  # net credit received
    assert 0 < s["max_loss"] < 1e8  # defined (finite) risk
    assert s["max_profit"] > 0


def test_cash_secured_put_is_short_put_credit():
    s = build("cash_secured_put", S=100, r=0.04, t=0.1, sigma=0.3)
    assert len(s["legs"]) == 1 and s["legs"][0]["kind"] == "put" and s["legs"][0]["qty"] == -1
    assert s["entry_credit"] > 0


def test_long_straddle_is_a_debit():
    s = build("long_straddle", S=100, r=0.04, t=0.1, sigma=0.3)
    assert s["entry_credit"] < 0  # you pay a debit
    assert s["max_loss"] > 0


def test_payoff_short_put_otm_expires_worthless():
    legs = [{"kind": "put", "strike": 90, "qty": -1}]
    assert payoff_at(legs, 100.0) == 0.0  # above strike -> put expires worthless
    assert payoff_at(legs, 80.0) == -1000.0  # 10 in-the-money * 100


# ---------- backtester ----------
def test_backtester_runs_and_reports():
    r = OptionsBacktester(OptionsConfig(symbol="NVDA", strategy="iron_condor"),
                          use_live=False).run()
    assert r["num_trades"] > 0
    assert "metrics" in r and "sharpe" in r["metrics"]
    assert "underlying_return_pct" in r
    assert len(r["equity_curve"]) >= 1


def test_backtester_is_deterministic_offline():
    a = OptionsBacktester(OptionsConfig(symbol="AAPL", strategy="bull_put_spread"),
                          use_live=False).run()
    b = OptionsBacktester(OptionsConfig(symbol="AAPL", strategy="bull_put_spread"),
                          use_live=False).run()
    assert a["end_equity"] == b["end_equity"]


# ---------- optimizer ----------
def test_options_optimizer_walk_forward():
    grid = candidate_configs(OptionsConfig())
    assert len(grid) == 24
    o1 = optimize(OptionsConfig(symbol="NVDA"), use_live=False)
    o2 = optimize(OptionsConfig(symbol="NVDA"), use_live=False)
    assert o1["tried"] == 24
    assert o1["out_of_sample"]["return_pct"] == o2["out_of_sample"]["return_pct"]  # deterministic
    assert "benchmark" in o1 and "monte_carlo" in o1 and "cost_sensitivity" in o1
    assert o1["selection"]["deflated_sharpe"] <= o1["selection"]["observed_sharpe"]
    assert o1["out_of_sample"]["num_trades"] >= 3  # picks a config that actually trades
    board = o1["leaderboard"]
    assert board and "train_return_pct" in board[0] and "test_return_pct" in board[0]


# ---------- forward options paper trader ----------
def test_options_paper_trader_opens_and_tracks_equity():
    t = OptionsPaperTrader(OptionsConfig(symbol="NVDA", strategy="iron_condor"), use_live=False)
    state: dict = {}
    r1 = t.step(state, on="2026-01-01")
    assert r1["action"] == "opened"
    assert state["position"] is not None
    assert len(state["equity_history"]) == 1
    r2 = t.step(state, on="2026-01-02")
    assert r2["action"] == "held"
    assert len(state["equity_history"]) == 2


def test_options_paper_trader_closes_or_rolls_at_expiry():
    cfg = OptionsConfig(symbol="NVDA", strategy="iron_condor")
    t = OptionsPaperTrader(cfg, use_live=False)
    state: dict = {}
    t.step(state, on="d0", S=100.0, sigma=0.3)
    state["position"]["days_left"] = 1  # force expiry on the next step
    r = t.step(state, on="d1", S=100.0, sigma=0.3)
    assert r["action"] in ("closed", "rolled")
    assert state.get("realized")  # a realized P&L was recorded


def test_options_store_roundtrip(tmp_path):
    store = OptionsStore(path=tmp_path / "options.json")
    cfg = OptionsConfig(symbol="AAPL", strategy="bull_put_spread")
    store.save(cfg, {"cash": 10_000.0, "equity_history": [{"date": "d", "equity": 10_000.0}]})
    loaded_cfg, state = store.load()
    assert loaded_cfg.symbol == "AAPL" and loaded_cfg.strategy == "bull_put_spread"
    assert state["cash"] == 10_000.0 and len(state["equity_history"]) == 1


# ---------- payoff diagram ----------
def test_payoff_curve_iron_condor_shape():
    pf = payoff_curve("iron_condor", 100, 0.04, 0.1, 0.3)
    assert len(pf["prices"]) == len(pf["pnl"]) == 41
    assert pf["max_profit"] > 0 and pf["max_loss"] > 0
    mid = pf["pnl"][len(pf["pnl"]) // 2]  # near the money
    assert mid > pf["pnl"][0] and mid > pf["pnl"][-1]  # condor profits mid, loses at the wings


# ---------- API ----------
def test_api_options_optimize_and_run():
    resp = client.post("/api/trading/options/optimize", json={"symbol": "NVDA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tried"] == 24 and "out_of_sample" in body and "benchmark" in body
    assert "payoff" in body and body["payoff"]["prices"]


def test_api_options_optimize_apply_persists_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GARY_OPTIONS_FILE", str(tmp_path / "options.json"))
    resp = client.post("/api/trading/options/optimize", json={"symbol": "NVDA", "apply": True})
    body = resp.json()
    assert body.get("applied") is True
    cfg, _ = OptionsStore().load()
    assert cfg.strategy == body["out_of_sample"]["params"]["strategy"]

    run = client.post("/api/trading/options/run",
                      json={"symbol": "NVDA", "strategy": "iron_condor", "dte": 21})
    assert run.status_code == 200
    assert "return_pct" in run.json() and "metrics" in run.json()
