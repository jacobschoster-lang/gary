from fastapi.testclient import TestClient

from gary.app import app
from gary.realestate import search_listings
from gary.realestate.rentcast import RentCastClient
from gary.realestate.search import haversine_mi

client = TestClient(app)

_RAW = [
    {"formattedAddress": "1 Farm Rd, Batavia, OH", "city": "Batavia", "state": "OH",
     "zipCode": "45103", "price": 300000, "lotSize": 6 * 43560, "bedrooms": 3,
     "bathrooms": 2, "squareFootage": 1800, "latitude": 39.077, "longitude": -84.177,
     "status": "Active", "listedDate": "2026-07-01T00:00:00Z"},
    {"formattedAddress": "2 City St, Cincinnati, OH", "city": "Cincinnati", "state": "OH",
     "zipCode": "45202", "price": 250000, "lotSize": 0.2 * 43560, "latitude": 39.10,
     "longitude": -84.51, "status": "Active"},  # too small (acres)
    {"formattedAddress": "3 Big Rd, Milford, OH", "city": "Milford", "state": "OH",
     "zipCode": "45150", "price": 500000, "lotSize": 10 * 43560, "latitude": 39.17,
     "longitude": -84.29, "status": "Active"},  # too expensive
]


def test_haversine_reasonable():
    d = haversine_mi(39.1031, -84.5120, 39.1031, -84.5120)
    assert d == 0.0
    d2 = haversine_mi(39.1031, -84.5120, 39.9612, -82.9988)  # Cincinnati->Columbus ~85mi
    assert 80 < d2 < 110


def test_rentcast_find_filters(monkeypatch):
    monkeypatch.setattr(RentCastClient, "search_sale", lambda self, *a, **k: _RAW)
    c = RentCastClient(api_key="k")
    out = c.find(39.1031, -84.5120, radius=25, min_acres=5, max_price=350000)
    assert len(out) == 1
    assert out[0].city == "Batavia"
    assert out[0].acres == 6.0


def test_search_uses_rentcast_when_configured(monkeypatch):
    monkeypatch.setenv("RENTCAST_API_KEY", "k")
    monkeypatch.setattr(RentCastClient, "search_sale", lambda self, *a, **k: _RAW)
    res = search_listings(city="Cincinnati", state="OH", radius=25, min_acres=5, max_price=350000)
    assert res["source"] == "rentcast"
    assert res["count"] == 1
    assert res["listings"][0]["distance_mi"] is not None


def test_search_falls_back_to_sample(monkeypatch):
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    res = search_listings(city="Cincinnati", state="OH", radius=25, min_acres=5, max_price=350000)
    assert res["source"] == "sample"
    assert res["count"] >= 1
    for lst in res["listings"]:
        assert lst["price"] <= 350000
        assert lst["acres"] >= 5


def test_api_endpoint(monkeypatch):
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    res = client.get(
        "/api/realestate",
        params={"city": "Cincinnati", "state": "OH", "radius": 25,
                "min_acres": 5, "max_price": 350000},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["filters"]["min_acres"] == 5
    assert all(x["acres"] >= 5 and x["price"] <= 350000 for x in body["listings"])
