"""High-level listing search with live (RentCast) + sample fallback."""

from __future__ import annotations

import math
from typing import Any

from gary.realestate.models import Listing
from gary.realestate.rentcast import RentCastClient, RentCastError

# Coordinates for supported metro centers (extend as needed).
CITY_COORDS: dict[str, tuple[float, float]] = {
    "cincinnati,oh": (39.1031, -84.5120),
    "columbus,oh": (39.9612, -82.9988),
    "dayton,oh": (39.7589, -84.1916),
    "louisville,ky": (38.2527, -85.7585),
    "indianapolis,in": (39.7684, -86.1581),
}


def _coords(city: str, state: str) -> tuple[float, float]:
    return CITY_COORDS.get(f"{city.strip().lower()},{state.strip().lower()}",
                           CITY_COORDS["cincinnati,oh"])


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.8  # earth radius in miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return round(r * 2 * math.asin(math.sqrt(a)), 1)


def search_listings(
    city: str = "Cincinnati",
    state: str = "OH",
    radius: float = 25,
    min_acres: float = 5.0,
    max_price: float = 350000.0,
) -> dict[str, Any]:
    lat, lng = _coords(city, state)
    filters = {
        "city": city, "state": state, "radius": radius,
        "min_acres": min_acres, "max_price": max_price,
        "center": {"latitude": lat, "longitude": lng},
    }

    client = RentCastClient.from_env()
    if client is not None:
        try:
            listings = client.find(lat, lng, radius, min_acres, max_price)
            for x in listings:
                if x.latitude and x.longitude:
                    x.distance_mi = haversine_mi(lat, lng, x.latitude, x.longitude)
            return {"source": "rentcast", "count": len(listings),
                    "listings": [x.to_dict() for x in listings], "filters": filters}
        except RentCastError as exc:
            filters["error"] = str(exc)

    # Fallback: labeled sample data filtered by the same criteria.
    listings = _filter_sample(lat, lng, radius, min_acres, max_price)
    return {"source": "sample", "count": len(listings),
            "listings": [x.to_dict() for x in listings], "filters": filters}


def _filter_sample(lat, lng, radius, min_acres, max_price) -> list[Listing]:
    out = []
    for x in _sample_listings():
        if x.price > max_price or x.acres < min_acres:
            continue
        if x.latitude and x.longitude:
            x.distance_mi = haversine_mi(lat, lng, x.latitude, x.longitude)
            if x.distance_mi > radius:
                continue
        out.append(x)
    out.sort(key=lambda v: v.price)
    return out


def _sample_listings() -> list[Listing]:
    # Representative Cincinnati-area acreage listings (SAMPLE data, not live).
    raw = [
        ("1450 Bethel New Richmond Rd", "New Richmond", "OH", "45157", 289000, 6.8,
         3, 2, 1800, 38.965, -84.190),
        ("7820 Hamilton Cleves Rd", "Cleves", "OH", "45002", 315000, 8.2,
         4, 2, 2200, 39.163, -84.749),
        ("2205 US-52", "Moscow", "OH", "45153", 245000, 5.5,
         3, 1, 1500, 38.859, -84.229),
        ("5533 Bucktown Rd", "Williamsburg", "OH", "45176", 335000, 12.0,
         3, 2, 1950, 39.057, -84.049),
        ("980 Trareva Dr", "Cincinnati", "OH", "45238", 349000, 5.1,
         4, 3, 2400, 39.128, -84.612),
    ]
    listings = []
    for (a, c, s, z, p, ac, b, ba, sf, la, lo) in raw:
        query = f"{a} {c} {s} for sale".replace(" ", "+")
        listings.append(Listing(
            address=a, city=c, state=s, zip_code=z, price=float(p), acres=ac,
            beds=b, baths=ba, sqft=sf, latitude=la, longitude=lo, status="Active",
            listed_date=None, url=f"https://www.google.com/search?q={query}",
        ))
    return listings
