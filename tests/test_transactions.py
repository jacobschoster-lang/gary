import io

from fastapi.testclient import TestClient

from gary.app import app
from gary.finance import ProfileStore
from gary.finance.transactions import (
    Transaction,
    cashflow_summary,
    categorize,
    dedupe,
    parse_amount,
    parse_csv,
)

client = TestClient(app)

_CSV_SIGNED = """Date,Description,Amount
2026-01-02,PAYROLL DIRECT DEP,3000.00
2026-01-03,Whole Foods Market,-120.50
2026-01-05,Netflix subscription,-15.99
2026-01-10,Shell Gas Station,-45.00
"""

_CSV_DEBIT_CREDIT = """Date,Description,Debit,Credit
01/02/2026,Employer Payroll,,3000.00
01/04/2026,Trader Joe's,88.20,
01/06/2026,Rent Payment,1500.00,
"""


def test_parse_amount_variants():
    assert parse_amount("$1,234.56") == 1234.56
    assert parse_amount("(50.00)") == -50.0
    assert parse_amount("-45") == -45.0
    assert parse_amount("") is None
    assert parse_amount("abc") is None


def test_categorize():
    assert categorize("PAYROLL DIRECT DEP", 3000) == "Income"
    assert categorize("Whole Foods Market", -120) == "Groceries"
    assert categorize("Netflix subscription", -15.99) == "Subscriptions"
    assert categorize("Rent Payment", -1500) == "Housing"


def test_parse_csv_signed_amount():
    txns = parse_csv(_CSV_SIGNED)
    assert len(txns) == 4
    assert txns[0].amount == 3000.0 and txns[0].category == "Income"
    assert txns[1].amount == -120.5 and txns[1].category == "Groceries"


def test_parse_csv_debit_credit():
    txns = parse_csv(_CSV_DEBIT_CREDIT)
    assert len(txns) == 3
    assert txns[0].amount == 3000.0  # credit -> positive
    assert txns[2].amount == -1500.0  # debit -> negative
    assert txns[0].date == "2026-01-02"  # normalized from 01/02/2026


def test_cashflow_summary():
    txns = parse_csv(_CSV_SIGNED)
    cf = cashflow_summary(txns)
    assert cf["total_income"] == 3000.0
    assert cf["total_expenses"] == round(120.50 + 15.99 + 45.00, 2)
    assert cf["net_cashflow"] == round(3000 - (120.50 + 15.99 + 45.00), 2)
    cats = {c["category"] for c in cf["expenses_by_category"]}
    assert {"Groceries", "Subscriptions", "Transport"} <= cats


def test_dedupe():
    a = [Transaction("2026-01-01", "X", -10.0, "Other")]
    b = [Transaction("2026-01-01", "X", -10.0, "Other"),
         Transaction("2026-01-02", "Y", -5.0, "Other")]
    merged = dedupe(a, b)
    assert len(merged) == 2


def test_import_endpoint_csv(tmp_path, monkeypatch):
    monkeypatch.setattr("gary.app.finance_store", ProfileStore(tmp_path / "imp.json"))
    files = {"file": ("statement.csv", io.BytesIO(_CSV_SIGNED.encode()), "text/csv")}
    res = client.post("/api/finance/import", files=files)
    assert res.status_code == 200
    body = res.json()
    assert body["imported"]["added"] == 4
    assert body["cashflow"]["total_income"] == 3000.0
    # monthly income/expenses were derived from the import
    assert body["profile"]["monthly_income"] == 3000.0
    assert len(body["recent_transactions"]) == 4


def test_import_endpoint_rejects_unparseable(tmp_path, monkeypatch):
    monkeypatch.setattr("gary.app.finance_store", ProfileStore(tmp_path / "imp2.json"))
    files = {"file": ("junk.csv", io.BytesIO(b"hello world\nno amounts here"), "text/csv")}
    res = client.post("/api/finance/import", files=files)
    assert res.status_code == 422
