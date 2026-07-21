"""Tests for the paper trading bot.

The autouse ``offline`` fixture (tests/conftest.py) forces price fetches to fall
back to the deterministic synthetic series, so every simulation here is
reproducible without network access.
"""

from fastapi.testclient import TestClient

from gary.app import app
from gary.trading import (
    BotConfig,
    PaperBroker,
    RobinhoodCryptoBroker,
    TradingBot,
    TradingStore,
    optimize,
)
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


# ---------- tuning: config, trailing stop, add-ons, min strength ----------
def test_config_roundtrip_preserves_tuning_knobs():
    cfg = BotConfig(
        trailing_stop_pct=0.18, allow_add_ons=True, min_signal_strength=0.3,
        momentum_lookback=7, momentum_threshold=0.05, sma_short=3, sma_long=15,
        mr_window=10, mr_z=1.5, weights={"momentum": 2.0, "price_history": 1.0,
                                          "mean_reversion": 0.5},
    )
    restored = BotConfig.from_dict(cfg.to_dict())
    assert restored.trailing_stop_pct == 0.18
    assert restored.allow_add_ons is True
    assert restored.momentum_lookback == 7
    assert restored.weights["momentum"] == 2.0


def test_trailing_stop_lets_winner_run_then_exits_on_pullback():
    cfg = BotConfig(
        universe=["NVDA"], strategies=["momentum"], trailing_stop_pct=0.15,
        take_profit_pct=5.0,  # effectively disable fixed take-profit
    )
    broker = PaperBroker(cash=0.0)
    broker.positions["NVDA"] = Position("NVDA", 10.0, avg_cost=100.0, peak_price=100.0)
    bot = TradingBot(cfg, broker, use_live=False)
    # +50% — a fixed +30% take-profit would have sold; trailing lets it run.
    bot.run_tick({"NVDA": [100.0] * 20 + [150.0]}, on="d1")
    assert "NVDA" in bot.broker.positions
    assert bot.broker.positions["NVDA"].peak_price == 150.0
    # Pull back 20% from the 150 peak (>15% trail) -> exit, still in profit.
    bot.run_tick({"NVDA": [100.0] * 20 + [150.0, 120.0]}, on="d2")
    assert "NVDA" not in bot.broker.positions
    assert bot.broker.realized_pnl == 200.0
    assert bot.broker.reserve == 100.0  # 50% of the realized gain


def test_add_ons_pyramid_into_winner():
    cfg = BotConfig(
        universe=["NVDA"], strategies=["momentum"], allow_add_ons=True, max_position_pct=0.6,
    )
    broker = PaperBroker(cash=10_000.0)
    bot = TradingBot(cfg, broker, use_live=False)
    trend = [100.0 + i for i in range(20)]
    bot.run_tick({"NVDA": trend}, on="d1")
    q1 = bot.broker.positions["NVDA"].quantity
    bot.run_tick({"NVDA": trend + [trend[-1] + 1]}, on="d2")
    assert bot.broker.positions["NVDA"].quantity > q1


def test_add_ons_disabled_does_not_double_buy():
    cfg = BotConfig(universe=["NVDA"], strategies=["momentum"], allow_add_ons=False)
    broker = PaperBroker(cash=10_000.0)
    bot = TradingBot(cfg, broker, use_live=False)
    trend = [100.0 + i for i in range(20)]
    bot.run_tick({"NVDA": trend}, on="d1")
    q1 = bot.broker.positions["NVDA"].quantity
    bot.run_tick({"NVDA": trend + [trend[-1] + 1]}, on="d2")
    assert bot.broker.positions["NVDA"].quantity == q1


def test_min_signal_strength_blocks_weak_entries():
    cfg = BotConfig(universe=["NVDA"], strategies=["momentum"], min_signal_strength=0.99)
    bot = TradingBot(cfg, PaperBroker(cash=10_000.0), use_live=False)
    bot.run_tick({"NVDA": [100.0 + i * 0.1 for i in range(20)]}, on="d1")  # mild trend
    assert "NVDA" not in bot.broker.positions


# ---------- costs & next-bar execution ----------
def test_costs_reduce_proceeds_and_track_fees():
    b = PaperBroker(cash=1000.0, fee_bps=10.0, slippage_bps=5.0)
    b.buy("X", 1000.0, 100.0)
    assert b.cash == 0.0
    assert b.fees_paid > 0
    qty = 999.0 / (100.0 * 1.0005)  # invested (net of 0.1% fee) / slipped price
    assert abs(b.positions["X"].quantity - qty) < 1e-6
    assert abs(b.positions["X"].avg_cost - 1000.0 / qty) < 1e-6
    # A round trip at the same nominal price must lose money to costs.
    b.sell("X", b.positions["X"].quantity, 100.0)
    assert b.realized_pnl < 0
    assert b.fees_paid > 1.0


def test_zero_costs_are_backward_compatible():
    b = PaperBroker(cash=1000.0)  # fee/slippage default to 0
    b.buy("X", 500.0, 100.0)
    fill = b.sell("X", 5.0, 120.0)
    assert fill.realized_pnl == 100.0
    assert b.fees_paid == 0.0


def test_next_bar_execution_fills_at_following_price():
    cfg = BotConfig(
        universe=["NVDA"], strategies=["momentum"], fee_bps=0.0, slippage_bps=0.0,
        max_position_pct=1.0,
    )
    bot = TradingBot(cfg, use_live=False)
    prices = [100.0 + i for i in range(35)]  # steady uptrend -> momentum buy
    bot._run({"NVDA": prices}, [34])  # decide on data <34, fill at bar 34
    buys = [f for f in bot.broker.fills if f.side == "buy"]
    assert buys
    assert abs(buys[0].price - prices[34]) < 1e-9  # filled at bar 34, not bar 33


# ---------- regime filter, cross-sectional, vol targeting ----------
def test_regime_filter_exits_below_moving_average():
    cfg = BotConfig(
        universe=["NVDA"], strategies=["momentum"], regime_ma=20,
        stop_loss_pct=0.90,  # keep the stop out of the way so we isolate the regime exit
    )
    broker = PaperBroker(cash=0.0)
    broker.positions["NVDA"] = Position("NVDA", 10.0, avg_cost=100.0)
    bot = TradingBot(cfg, broker, use_live=False)
    # Last price (95) sits below the 20-bar SMA (~99.75) -> regime exit.
    acts = bot.run_tick({"NVDA": [100.0] * 20 + [95.0]}, on="d1")
    assert "NVDA" not in bot.broker.positions
    assert any("regime" in a.get("reason", "") for a in acts)


def test_cross_sectional_holds_only_top_n():
    cfg = BotConfig(
        universe=["A", "B", "C", "D"], selection_mode="cross_sectional", top_n_positions=2,
        strategies=["momentum"],
    )
    bot = TradingBot(cfg, PaperBroker(cash=10_000.0), use_live=False)
    history = {
        "A": [100.0 + 3 * i for i in range(20)],   # strongest momentum
        "B": [100.0 + 1.5 * i for i in range(20)],  # second
        "C": [100.0 + 0.2 * i for i in range(20)],  # weak
        "D": [100.0 - 2 * i for i in range(20)],    # negative -> never a candidate
    }
    bot.run_tick(history, on="d1")
    held = set(bot.broker.positions)
    assert held <= {"A", "B"}  # only the top-2 momentum names
    assert "A" in held and "D" not in held


def test_vol_targeting_sizes_smaller_for_higher_vol():
    from gary.trading.risk import position_notional

    low = position_notional(10_000, 10_000, 0.5, 0.0, asset_vol=0.01, vol_target=0.20)
    high = position_notional(10_000, 10_000, 0.5, 0.0, asset_vol=0.05, vol_target=0.20)
    assert high < low  # more volatile -> smaller position
    # vol_target off -> falls back to strength * cap
    assert position_notional(10_000, 10_000, 0.5, 0.0, strength=1.0) == 5000.0


# ---------- shorting, long/short, low turnover ----------
def test_short_and_cover_realizes_profit_when_price_falls():
    b = PaperBroker(cash=1000.0)  # zero costs
    b.short("X", 500.0, 100.0)  # short 5 @ 100 -> +500 proceeds
    assert b.cash == 1500.0
    assert b.positions["X"].quantity == -5.0
    fill = b.cover("X", 5.0, 90.0)  # buy back at 90 -> +50 profit
    assert fill.side == "cover"
    assert fill.realized_pnl == 50.0
    assert "X" not in b.positions
    assert round(b.cash, 2) == 1050.0


def test_short_loses_when_price_rises():
    b = PaperBroker(cash=1000.0)
    b.short("X", 500.0, 100.0)
    fill = b.cover("X", 5.0, 120.0)  # price rose -> loss
    assert fill.realized_pnl == -100.0


def test_borrow_cost_charged_on_open_shorts():
    b = PaperBroker(cash=1000.0)
    b.short("X", 1000.0, 100.0)  # qty -10
    before = b.cash
    charged = b.accrue_borrow({"X": 100.0}, 10.0)  # 10 * 100 notional * 0.10%
    assert round(charged, 4) == 1.0
    assert round(b.cash, 4) == round(before - 1.0, 4)


def test_long_short_mode_takes_both_legs():
    cfg = BotConfig(selection_mode="long_short", top_n_positions=2)
    r = TradingBot(cfg, use_live=False).simulate(40)
    sides = {t["side"] for t in r["trades"]}
    assert "short" in sides and "buy" in sides  # both legs traded


def test_low_turnover_reduces_trade_count():
    daily = TradingBot(BotConfig(selection_mode="cross_sectional", rebalance_every=1),
                       use_live=False).simulate(40)
    weekly = TradingBot(BotConfig(selection_mode="cross_sectional", rebalance_every=5),
                        use_live=False).simulate(40)
    assert weekly["num_trades"] < daily["num_trades"]


# ---------- purged walk-forward + robust selection ----------
def test_optimizer_purged_walk_forward_with_selection_and_mc():
    r1 = optimize(BotConfig(), days=25, folds=3, use_live=False)
    r2 = optimize(BotConfig(), days=25, folds=3, use_live=False)
    assert r1["tried"] == 32
    assert r1["folds"] == 3
    assert r1["embargo"] == 3
    assert len(r1["folds_detail"]) == 3
    # Deterministic aggregate OOS.
    assert r1["out_of_sample"]["return_pct"] == r2["out_of_sample"]["return_pct"]
    # Robust selection + deflated Sharpe are reported.
    assert "selection" in r1 and "deflated_sharpe" in r1["selection"]
    assert r1["selection"]["deflated_sharpe"] <= r1["selection"]["observed_sharpe"]
    # Benchmark, Monte Carlo, and a robustness-ranked leaderboard.
    assert "benchmark" in r1 and "monte_carlo" in r1
    board = r1["leaderboard"]
    assert board and "robustness" in board[0] and "test_return_pct" in board[0]


# ---------- smart buy & hold + forward stepping ----------
def test_buy_hold_holds_the_universe():
    cfg = BotConfig(selection_mode="buy_hold", universe=["NVDA", "AAPL", "MSFT"])
    r = TradingBot(cfg, use_live=False).simulate(30)
    held = {p["symbol"] for p in r["account"]["positions"]}
    assert held  # holds names rather than sitting in cash
    assert all(p["quantity"] > 0 for p in r["account"]["positions"])  # long-only


def test_step_live_mutates_persisted_account_and_records_equity(tmp_path):
    store = TradingStore(path=tmp_path / "trading.json")
    cfg = BotConfig(selection_mode="cross_sectional")
    bot = TradingBot(cfg, use_live=False)
    result = bot.step_live()
    assert "equity" in result and result["equity"] > 0
    store.save(cfg, bot.broker)
    hist = store.record_equity(result["date"], result["equity"])
    assert len(hist) == 1
    # Same-day record de-dupes.
    hist = store.record_equity(result["date"], result["equity"] + 10)
    assert len(hist) == 1 and store.equity_history()[0]["equity"] == result["equity"] + 10


def test_trade_daily_job_paper_and_safe(tmp_path, monkeypatch):
    from gary.jobs.trade_daily import run_once

    store = TradingStore(path=tmp_path / "trading.json")
    summary = run_once(store=store, use_live=False)
    assert summary["mode"] == "paper"
    assert summary["live_broker_configured"] is False  # no keys in test env
    assert summary["equity_history_points"] == 1
    assert "actions" in summary


# ---------- robinhood seam ----------
def test_robinhood_env_gating():
    assert RobinhoodCryptoBroker.from_env(env={}) is None
    broker = RobinhoodCryptoBroker.from_env(
        env={"ROBINHOOD_API_KEY": "k", "ROBINHOOD_PRIVATE_KEY": "p"}
    )
    assert broker is not None and broker.live_enabled is False


def test_robinhood_request_signing_is_deterministic():
    from gary.trading.robinhood import RobinhoodError, canonical_message

    signed = []
    broker = RobinhoodCryptoBroker(
        api_key="mykey", private_key_b64="x", live_enabled=True,
        signer=lambda m: (signed.append(m) or "SIG"),
    )
    req = broker.prepare_order("BTC-USD", "buy", 0.5, timestamp=1700000000)
    assert req["headers"]["x-api-key"] == "mykey"
    assert req["headers"]["x-signature"] == "SIG"
    assert req["headers"]["x-timestamp"] == "1700000000"
    # The signed message is exactly the canonical string over the request.
    assert signed[0] == canonical_message("mykey", "1700000000", req["url"].split(".com")[1],
                                          "POST", req["body"])
    # Live send refuses without a transport, and paper stays default elsewhere.
    try:
        broker.place_order("BTC-USD", "buy", 0.5)
    except RobinhoodError as exc:
        assert "transport" in str(exc)
    else:
        raise AssertionError("expected RobinhoodError without transport")


def test_robinhood_place_order_blocked_when_not_live():
    from gary.trading.robinhood import RobinhoodError

    broker = RobinhoodCryptoBroker(api_key="k", private_key_b64="p", live_enabled=False,
                                   signer=lambda m: "SIG")
    try:
        broker.place_order("BTC-USD", "buy", 1.0, transport=lambda r: {})
    except RobinhoodError as exc:
        assert "TRADING_LIVE" in str(exc)
    else:
        raise AssertionError("expected live-disabled RobinhoodError")


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


def test_api_trading_optimize(tmp_path, monkeypatch):
    monkeypatch.setenv("GARY_TRADING_FILE", str(tmp_path / "trading.json"))
    import gary.app as app_module

    app_module.trading_store = TradingStore()

    resp = client.post("/api/trading/optimize", json={"days": 25})
    assert resp.status_code == 200
    body = resp.json()
    assert "optimization" in body
    opt = body["optimization"]
    assert opt["tried"] == 32
    assert "out_of_sample" in opt and "benchmark" in opt and "monte_carlo" in opt
    assert "selection" in opt
    assert len(opt["leaderboard"]) >= 1
    # The applied run carries the full metrics scorecard.
    assert "metrics" in body and "sharpe" in body["metrics"]
    # The optimized config is persisted and reflected in status.
    status = client.get("/api/trading/status").json()
    assert status["has_run"] is True
