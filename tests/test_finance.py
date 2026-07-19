from datetime import date

from fastapi.testclient import TestClient

from gary.app import app
from gary.finance import (
    ProfileStore,
    compare_strategies,
    financial_health,
    net_worth,
    net_worth_breakdown,
    payoff_plan,
    record_snapshot,
    sample_profile,
)
from gary.finance.models import Asset, Debt, Profile

client = TestClient(app)


def test_net_worth_and_breakdown():
    p = Profile(
        assets=[Asset("Cash", 5000, "cash"), Asset("401k", 20000, "investment")],
        debts=[Debt("Card", 3000, 20, 100), Debt("Loan", 7000, 5, 150)],
    )
    assert net_worth(p) == 15000.0
    b = net_worth_breakdown(p)
    assert b["total_assets"] == 25000.0
    assert b["total_debts"] == 10000.0
    assert b["assets_by_kind"]["cash"] == 5000.0


def test_networth_snapshot_dedupes_per_day():
    p = Profile(assets=[Asset("Cash", 1000, "cash")])
    record_snapshot(p, on=date(2026, 1, 1))
    p.assets[0].value = 2000
    record_snapshot(p, on=date(2026, 1, 1))  # same day -> replace
    assert len(p.networth_history) == 1
    assert p.networth_history[0]["value"] == 2000.0


def test_payoff_plan_converges_and_pays_off():
    debts = [Debt("Card", 2000, 24, 50), Debt("Loan", 4000, 6, 80)]
    plan = payoff_plan(debts, extra=300, strategy="avalanche")
    assert plan["converged"] is True
    assert plan["months"] > 0
    assert plan["total_interest"] > 0
    # Avalanche targets the highest APR (Card) first.
    assert plan["order"][0] == "Card"


def test_avalanche_beats_or_ties_snowball_on_interest():
    debts = [Debt("Card", 6500, 22.99, 150), Debt("Car", 12000, 6.5, 320),
             Debt("Student", 18000, 4.5, 190)]
    cmp = compare_strategies(debts, extra=400)
    assert cmp["avalanche"]["total_interest"] <= cmp["snowball"]["total_interest"]
    assert cmp["recommended"] == "avalanche"


def test_payoff_plan_rejects_bad_strategy():
    import pytest
    with pytest.raises(ValueError):
        payoff_plan([Debt("x", 100, 5, 10)], strategy="turbo")


def test_health_flags_high_interest_and_low_emergency():
    p = Profile(
        monthly_income=5000, monthly_expenses=4500,
        assets=[Asset("Cash", 1000, "cash")],
        debts=[Debt("Card", 8000, 25, 200)],
    )
    h = financial_health(p)
    assert 0 <= h["score"] <= 100
    text = " ".join(r["text"] for r in h["recommendations"]).lower()
    assert "emergency fund" in text
    assert "high-interest" in text or "apr" in text


def test_store_roundtrip(tmp_path):
    store = ProfileStore(tmp_path / "p.json")
    assert store.load().assets == []  # missing file -> empty
    p = sample_profile()
    record_snapshot(p)
    store.save(p)
    loaded = store.load()
    assert loaded.monthly_income == p.monthly_income
    assert len(loaded.debts) == len(p.debts)
    assert len(loaded.networth_history) == 1


def test_finance_api_sample_and_get(tmp_path, monkeypatch):
    # Point the app's store at a temp file so the test is isolated.
    monkeypatch.setattr("gary.app.finance_store", ProfileStore(tmp_path / "api.json"))

    res = client.post("/api/finance/sample")
    assert res.status_code == 200
    body = res.json()
    assert body["net_worth"]["net_worth"] != 0
    assert body["debt_plan"]["recommended"] in ("avalanche", "snowball")
    assert body["health"]["grade"] in ("A", "B", "C", "D", "F")

    res2 = client.get("/api/finance")
    assert res2.status_code == 200
    assert len(res2.json()["profile"]["debts"]) == 3


def test_finance_api_post_profile(tmp_path, monkeypatch):
    monkeypatch.setattr("gary.app.finance_store", ProfileStore(tmp_path / "api2.json"))
    payload = {
        "monthly_income": 5000, "monthly_expenses": 3000, "extra_debt_payment": 500,
        "assets": [{"name": "Cash", "value": 10000, "kind": "cash"}],
        "debts": [{"name": "Card", "balance": 4000, "apr": 20, "min_payment": 100}],
    }
    res = client.post("/api/finance", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["net_worth"]["net_worth"] == 6000.0
    assert len(body["history"]) >= 1
