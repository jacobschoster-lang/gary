from fastapi.testclient import TestClient

from gary.app import app
from gary.finance import retirement_plan
from gary.finance.models import Asset, Profile

client = TestClient(app)


def test_retirement_on_track():
    p = Profile(
        monthly_expenses=4000, age=30, retirement_age=65,
        monthly_retirement_contribution=1500,
        assets=[Asset("401k", 100000, "investment")],
    )
    r = retirement_plan(p)
    assert r["years_to_retirement"] == 35
    assert r["current_retirement_savings"] == 100000
    assert r["nest_egg_needed"] > 0
    assert r["projected_savings"] > r["current_retirement_savings"]
    assert r["on_track"] is True
    assert len(r["projection"]) == 36  # inclusive of both endpoints


def test_retirement_behind_recommends_more():
    p = Profile(
        monthly_income=5000, monthly_expenses=5000, age=50, retirement_age=65,
        monthly_retirement_contribution=100,
        assets=[Asset("401k", 20000, "investment")],
    )
    r = retirement_plan(p)
    assert r["on_track"] is False
    assert r["gap"] > 0
    assert r["recommended_monthly_contribution"] > r["monthly_contribution"]
    assert any("close the gap" in x["text"] or "short of" in x["text"]
               for x in r["recommendations"])


def test_retirement_no_age_prompts():
    r = retirement_plan(Profile(monthly_expenses=3000))
    assert any("Enter your age" in x["text"] for x in r["recommendations"])


def test_retirement_only_counts_investment_assets():
    p = Profile(age=40, monthly_expenses=3000, assets=[
        Asset("Checking", 10000, "cash"),
        Asset("Brokerage", 50000, "investment"),
        Asset("House", 300000, "property"),
    ])
    r = retirement_plan(p)
    assert r["current_retirement_savings"] == 50000


def test_finance_payload_includes_retirement(tmp_path, monkeypatch):
    from gary.finance import ProfileStore
    monkeypatch.setattr("gary.app.finance_store", ProfileStore(tmp_path / "r.json"))
    body = client.post("/api/finance/sample").json()
    assert "retirement" in body
    assert body["retirement"]["age"] == 34
    assert body["profile"]["monthly_retirement_contribution"] == 300.0
