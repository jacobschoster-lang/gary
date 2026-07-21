"""Tests for the paper trading bot.

The autouse ``offline`` fixture (tests/conftest.py) forces price fetches to fall
back to the deterministic synthetic series, so every simulation here is
reproducible without network access.
"""

from fastapi.testclient import TestClient

from gary.app import app
from gary.trading import BotConfig, PaperBroker, RobinhoodCryptoBroker, TradingBot, TradingStore
from gary.trading.models import Position
from gary.trading.risk import (
    rebalance_amount,
    should_stop_loss,
    should_take_profit,
    target_position_notional,
)
from gary.trading.strategies import (
    combine,
    mean_reversion_signal,
    momentum_signal,
    sma_crossover_signal,
)

client = TestClient(app)


# ---------- strategies ----------
def test_momentum_signal_buy_sell_hold():
    up = [100 + i for i in range(20)]
    assert momentum_signal(up).action == "buy"
    down = [100 - i for i in range(20)]
    assert momentum_signal(down).action == "sell"
    flat = [100.0] * 20
    assert momentum_signal(flat).action == "hold"


def test_sma_crossover_direction():
    up = [100 + i for i in range(30)]
    assert sma_crossover_signal(up).action == "buy"
    down = [100 - i for i in range(30)]
    assert sma_crossover_signal(down).action == "sell"


def test_mean_reversion_fades_extremes():
    prices = [100.0] * 20 + [70.0]  # sharp drop -> oversold -> buy
    assert mean_reversion_signal(prices).action == "buy"
    prices = [100.0] * 20 + [130.0]  # spike -> overbought -> sell
    assert mean_reversion_signal(prices).action == "sell"


def test_combine_majority_wins():
    from gary.trading.models import Signal

    buys = [
        Signal("buy", 0.8, "x", "a"),
        Signal("buy", 0.5, "y", "b"),
        Signal("sell", 0.2, "z", "c"),
    ]
    action, strength, _ = combine(buys)
    assert action == "buy" and strength > 0


# ---------- risk ----------
def test_take_profit_and_stop_loss_thresholds():
    assert should_take_profit(0.30, 0.30) is True
    assert should_take_profit(0.29, 0.30) is False
    assert should_stop_loss(-0.15, 0.15) is True
    assert should_stop_loss(-0.10, 0.15) is False


def test_position_sizing_respects_caps():
    # 25% of 10k equity = 2500 cap; strength 1 -> full cap, bounded by cash.
    assert target_position_notional(10_000, 10_000, 0.25, 0.0, 1.0) == 2500.0
    # existing 2000 already in name -> only 500 room left.
    assert target_position_notional(10_000, 10_000, 0.25, 2000.0, 1.0) == 500.0
    # limited by available cash.
    assert target_position_notional(10_000, 300, 0.25, 0.0, 1.0) == 300.0


def test_rebalance_amount_half_of_profit():
    assert rebalance_amount(1000.0, 0.5) == 500.0
    assert rebalance_amount(-100.0, 0.5) == 0.0


# ---------- broker ----------
def test_paper_broker_buy_sell_realizes_pnl():
    b = PaperBroker(cash=1000.0)
    b.buy("NVDA", 500.0, 100.0)  # 5 shares @ 100
    assert b.cash == 500.0
    assert b.positions["NVDA"].quantity == 5.0
    fill = b.sell("NVDA", 5.0, 120.0)  # +20/share -> +100 realized
    assert fill.realized_pnl == 100.0
    assert b.realized_pnl == 100.0
    assert "NVDA" not in b.positions
    assert b.cash == 1100.0


def test_paper_broker_average_cost():
    b = PaperBroker(cash=1000.0)
    b.buy("X", 100.0, 10.0)   # 10 @ 10
    b.buy("X", 100.0, 20.0)   # 5 @ 20 -> 15 units, cost 200 -> avg ~13.333
    assert round(b.positions["X"].avg_cost, 4) == round(200.0 / 15.0, 4)


def test_paper_broker_reserve_and_serialize_roundtrip():
    b = PaperBroker(cash=1000.0)
    b.buy("BTC", 400.0, 100.0)
    b.move_to_reserve(200.0)
    assert b.reserve == 200.0 and b.cash == 400.0
    data = b.serialize()
    restored = PaperBroker.deserialize(data)
    assert restored.reserve == 200.0
    assert restored.positions["BTC"].quantity == b.positions["BTC"].quantity


# ---------- engine ----------
def test_simulate_is_deterministic_and_offline():
    bot1 = TradingBot(BotConfig(), use_live=False)
    bot2 = TradingBot(BotConfig(), use_live=False)
    r1 = bot1.simulate(30)
    r2 = bot2.simulate(30)
    assert r1["end_equity"] == r2["end_equity"]
    assert r1["start_equity"] == 10_000.0
    assert len(r1["equity_curve"]) == 30
    assert r1["num_trades"] > 0


def test_take_profit_triggers_rebalance_to_reserve():
    cfg = BotConfig(universe=["NVDA"], strategies=["momentum"])
    broker = PaperBroker(cash=cfg.starting_cash)
    broker.positions["NVDA"] = Position("NVDA", quantity=10.0, avg_cost=100.0)
    broker.cash = 0.0
    bot = TradingBot(cfg, broker, use_live=False)
    # Price up 50% -> exceeds +30% take-profit; profit 500 -> 250 to reserve.
    bot.run_tick({"NVDA": [100.0] * 20 + [150.0]}, on="2026-01-01")
    assert "NVDA" not in bot.broker.positions
    assert bot.broker.reserve == 250.0
    assert bot.broker.realized_pnl == 500.0


def test_stop_loss_closes_position():
    cfg = BotConfig(universe=["NVDA"], strategies=["momentum"], stop_loss_pct=0.15)
    broker = PaperBroker(cash=0.0)
    broker.positions["NVDA"] = Position("NVDA", quantity=10.0, avg_cost=100.0)
    bot = TradingBot(cfg, broker, use_live=False)
    bot.run_tick({"NVDA": [100.0] * 20 + [80.0]}, on="2026-01-01")  # -20% -> stop
    assert "NVDA" not in bot.broker.positions
    assert bot.broker.reserve == 0.0  # no profit to skim


# ---------- store ----------
def test_store_roundtrip(tmp_path):
    store = TradingStore(path=tmp_path / "trading.json")
    cfg = BotConfig(starting_cash=5000.0)
    bot = TradingBot(cfg, use_live=False)
    bot.simulate(20)
    store.save(cfg, bot.broker)
    loaded_cfg, loaded_broker = store.load()
    assert loaded_cfg.starting_cash == 5000.0
    assert round(loaded_broker.realized_pnl, 2) == round(bot.broker.realized_pnl, 2)


# ---------- robinhood seam ----------
def test_robinhood_env_gating():
    assert RobinhoodCryptoBroker.from_env(env={}) is None
    broker = RobinhoodCryptoBroker.from_env(
        env={"ROBINHOOD_API_KEY": "k", "ROBINHOOD_PRIVATE_KEY": "p"}
    )
    assert broker is not None and broker.live_enabled is False


# ---------- API ----------
def test_api_trading_run_and_status(tmp_path, monkeypatch):
    monkeypatch.setenv("GARY_TRADING_FILE", str(tmp_path / "trading.json"))
    import gary.app as app_module

    app_module.trading_store = TradingStore()

    resp = client.post("/api/trading/run", json={"days": 20})
    assert resp.status_code == 200
    body = resp.json()
    assert body["start_equity"] == 10_000.0
    assert len(body["equity_curve"]) == 20
    assert body["mode"] == "paper"

    status = client.get("/api/trading/status").json()
    assert status["has_run"] is True
    assert "equity" in status["account"]

    reset = client.post("/api/trading/reset", json={}).json()
    assert reset["account"]["equity"] == 10_000.0
