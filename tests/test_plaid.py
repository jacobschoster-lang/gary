import httpx

from gary.finance.plaid import PlaidClient, PlaidError, PlaidTokenStore

_ENV = {"PLAID_CLIENT_ID": "cid", "PLAID_SECRET": "sec", "PLAID_ENV": "sandbox"}


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = str(data)

    def json(self):
        return self._data


def _mock_post(monkeypatch, router):
    def fake(url, json=None, timeout=None):
        for key, resp in router.items():
            if url.endswith(key):
                return resp
        return _FakeResp({"error_message": "unexpected"}, 400)
    monkeypatch.setattr("gary.finance.plaid.httpx.post", fake)


def test_from_env_absent():
    assert PlaidClient.from_env({}) is None


def test_from_env_present_sandbox():
    c = PlaidClient.from_env(_ENV)
    assert c is not None
    assert c.base_url == "https://sandbox.plaid.com"


def test_create_and_exchange(monkeypatch):
    _mock_post(monkeypatch, {
        "/link/token/create": _FakeResp({"link_token": "link-123"}),
        "/item/public_token/exchange": _FakeResp({"access_token": "access-abc"}),
    })
    c = PlaidClient.from_env(_ENV)
    assert c.create_link_token() == "link-123"
    assert c.exchange_public_token("public-xyz") == "access-abc"


def test_get_accounts_maps_assets_and_debts(monkeypatch):
    _mock_post(monkeypatch, {
        "/accounts/balance/get": _FakeResp({"accounts": [
            {"name": "Checking", "type": "depository", "balances": {"current": 5000}},
            {"name": "Brokerage", "type": "investment", "balances": {"current": 20000}},
            {"name": "Visa", "type": "credit", "balances": {"current": 1500}},
            {"name": "Auto Loan", "type": "loan", "balances": {"current": 9000}},
        ]}),
    })
    c = PlaidClient.from_env(_ENV)
    assets, debts = c.get_accounts("access")
    kinds = {a.name: a.kind for a in assets}
    assert kinds == {"Checking": "cash", "Brokerage": "investment"}
    debt_names = {d.name: d.balance for d in debts}
    assert debt_names == {"Visa": 1500.0, "Auto Loan": 9000.0}


def test_get_transactions_sign_and_category(monkeypatch):
    _mock_post(monkeypatch, {
        "/transactions/get": _FakeResp({"transactions": [
            {"date": "2026-06-01", "name": "ACME Payroll", "amount": -3000.0},
            {"date": "2026-06-02", "name": "Whole Foods", "amount": 120.0},
        ]}),
    })
    c = PlaidClient.from_env(_ENV)
    txns = c.get_transactions("access")
    # Plaid negative = money in -> our positive (income)
    assert txns[0].amount == 3000.0 and txns[0].category == "Income"
    # Plaid positive = money out -> our negative (expense)
    assert txns[1].amount == -120.0 and txns[1].category == "Groceries"


def test_error_raised_on_http_error(monkeypatch):
    _mock_post(monkeypatch, {
        "/link/token/create": _FakeResp({"error_message": "invalid client"}, 400),
    })
    c = PlaidClient.from_env(_ENV)
    try:
        c.create_link_token()
        raise AssertionError("expected PlaidError")
    except PlaidError as e:
        assert "invalid client" in str(e)


def test_network_error_wrapped(monkeypatch):
    def boom(url, json=None, timeout=None):
        raise httpx.ConnectError("down")
    monkeypatch.setattr("gary.finance.plaid.httpx.post", boom)
    c = PlaidClient.from_env(_ENV)
    try:
        c.exchange_public_token("x")
        raise AssertionError("expected PlaidError")
    except PlaidError as e:
        assert "network error" in str(e)


def test_token_store_roundtrip(tmp_path):
    store = PlaidTokenStore(tmp_path / "plaid.json")
    assert store.linked() is False
    store.add("access-1", "Chase")
    assert store.access_tokens() == ["access-1"]
    assert store.linked() is True


# ---- API endpoint tests ----

from fastapi.testclient import TestClient  # noqa: E402

from gary.app import app  # noqa: E402
from gary.finance import ProfileStore  # noqa: E402

client = TestClient(app)


def test_api_status_not_configured(monkeypatch):
    for k in ("PLAID_CLIENT_ID", "PLAID_SECRET"):
        monkeypatch.delenv(k, raising=False)
    res = client.get("/api/finance/plaid/status")
    assert res.status_code == 200
    assert res.json()["configured"] is False


def test_api_link_token_requires_config(monkeypatch):
    for k in ("PLAID_CLIENT_ID", "PLAID_SECRET"):
        monkeypatch.delenv(k, raising=False)
    res = client.post("/api/finance/plaid/link-token")
    assert res.status_code == 400


def test_api_exchange_full_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAID_CLIENT_ID", "cid")
    monkeypatch.setenv("PLAID_SECRET", "sec")
    monkeypatch.setattr("gary.app.finance_store", ProfileStore(tmp_path / "p.json"))
    monkeypatch.setattr("gary.app.plaid_tokens", PlaidTokenStore(tmp_path / "plaid.json"))
    _mock_post(monkeypatch, {
        "/item/public_token/exchange": _FakeResp({"access_token": "access-abc"}),
        "/accounts/balance/get": _FakeResp({"accounts": [
            {"name": "Checking", "type": "depository", "balances": {"current": 5000}},
            {"name": "Visa", "type": "credit", "balances": {"current": 1500}},
        ]}),
        "/transactions/get": _FakeResp({"transactions": [
            {"date": "2026-06-01", "name": "ACME Payroll", "amount": -3000.0},
            {"date": "2026-06-02", "name": "Whole Foods", "amount": 120.0},
        ]}),
    })
    res = client.post("/api/finance/plaid/exchange", json={"public_token": "public-xyz"})
    assert res.status_code == 200
    body = res.json()
    assert body["imported"] == {"source": "plaid", "added": 2}
    assert body["net_worth"]["net_worth"] == 3500.0  # 5000 asset - 1500 debt
    assert body["cashflow"]["total_income"] == 3000.0
