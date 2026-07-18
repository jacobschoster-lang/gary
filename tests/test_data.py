from gary.agents import TranscriptAgent, TrendsAgent
from gary.data import fetch_crypto_trends, fetch_headlines, fetch_stock_trends

_CG_MARKETS = [
    {"symbol": "btc", "name": "Bitcoin", "current_price": 64000,
     "price_change_percentage_24h": 3.5, "total_volume": 1},
    {"symbol": "usdt", "name": "Tether", "current_price": 1.0,
     "price_change_percentage_24h": 0.01, "total_volume": 1},
    {"symbol": "eth", "name": "Ethereum", "current_price": 3200,
     "price_change_percentage_24h": -2.0, "total_volume": 1},
]

_YF = {"chart": {"result": [{"meta": {"symbol": "NVDA", "regularMarketPrice": 120.0,
                                      "chartPreviousClose": 100.0}}]}}

_RSS = (
    "<rss><channel>"
    "<item><title>Bitcoin surges past resistance</title></item>"
    "<item><title>ETF inflows hit record</title></item>"
    "</channel></rss>"
)


def test_fetch_crypto_trends_parses_and_skips_stablecoins(monkeypatch):
    monkeypatch.setattr("gary.data.http.get_json", lambda *a, **k: _CG_MARKETS)
    trends = fetch_crypto_trends(limit=5)
    assert trends is not None
    symbols = [t.symbol for t in trends]
    assert "BTC" in symbols and "ETH" in symbols
    assert "USDT" not in symbols  # stablecoin filtered
    assert all(t.market == "crypto" for t in trends)


def test_fetch_crypto_trends_none_on_failure(monkeypatch):
    monkeypatch.setattr("gary.data.http.get_json", lambda *a, **k: None)
    assert fetch_crypto_trends() is None


def test_fetch_stock_trends_parses(monkeypatch):
    monkeypatch.setattr("gary.data.http.get_json", lambda *a, **k: _YF)
    trends = fetch_stock_trends(limit=3)
    assert trends is not None
    assert trends[0].market == "stocks"
    assert "%" in trends[0].note


def test_fetch_headlines_parses(monkeypatch):
    monkeypatch.setattr("gary.data.http.get_text", lambda *a, **k: _RSS)
    heads = fetch_headlines("bitcoin", limit=5)
    assert heads == ["Bitcoin surges past resistance", "ETF inflows hit record"]


def test_trends_agent_uses_live_when_available(monkeypatch):
    monkeypatch.setattr("gary.data.http.get_json", lambda *a, **k: _CG_MARKETS)
    agent = TrendsAgent(use_live=True)
    top = agent.top("crypto", limit=2)
    assert {t.symbol for t in top} <= {"BTC", "ETH"}


def test_trends_agent_falls_back_to_stub(monkeypatch):
    # get_json patched to None by the offline fixture -> stub data.
    agent = TrendsAgent(use_live=True)
    top = agent.top("crypto", limit=3)
    # Stub crypto set includes SOL, which the live mock never returns.
    assert any(t.symbol == "SOL" for t in top)


def test_transcript_grounds_in_live_headlines(monkeypatch):
    monkeypatch.setattr("gary.data.http.get_text", lambda *a, **k: _RSS)
    agent = TranscriptAgent(use_live=True)
    t = agent.generate("Bitcoin ETF inflows")
    joined = " ".join(s["script"] for s in t.sections)
    assert "ETF inflows hit record" in joined
