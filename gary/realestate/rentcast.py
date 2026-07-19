"""RentCast connector for active for-sale listings.

Enabled when ``RENTCAST_API_KEY`` is set (free tier available). We request a
radius search around a coordinate and filter by acreage and price client-side,
since RentCast returns ``lotSize`` (sqft) and ``price`` per listing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from gary.realestate.models import Listing

_BASE = "https://api.rentcast.io/v1"
SQFT_PER_ACRE = 43560.0


class RentCastError(RuntimeError):
    pass


@dataclass
class RentCastClient:
    api_key: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> RentCastClient | None:
        env = env if env is not None else dict(os.environ)
        key = env.get("RENTCAST_API_KEY")
        return cls(api_key=key) if key else None

    def search_sale(
        self,
        latitude: float,
        longitude: float,
        radius: float = 25,
        limit: int = 500,
    ) -> list[dict]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "radius": radius,
            "status": "Active",
            "limit": limit,
        }
        try:
            resp = httpx.get(
                f"{_BASE}/listings/sale",
                params=params,
                headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
                timeout=30.0,
            )
        except httpx.HTTPError as exc:
            raise RentCastError(f"network error calling RentCast: {exc}") from exc
        if resp.status_code >= 400:
            raise RentCastError(f"RentCast error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return data if isinstance(data, list) else data.get("listings", [])

    def find(
        self,
        latitude: float,
        longitude: float,
        radius: float = 25,
        min_acres: float = 5.0,
        max_price: float = 350000.0,
    ) -> list[Listing]:
        raw = self.search_sale(latitude, longitude, radius)
        out: list[Listing] = []
        for r in raw:
            price = r.get("price") or 0
            lot = r.get("lotSize") or 0
            acres = round(lot / SQFT_PER_ACRE, 2) if lot else 0.0
            if not price or price > max_price:
                continue
            if acres < min_acres:
                continue
            out.append(Listing(
                address=r.get("formattedAddress") or r.get("addressLine1") or "Address n/a",
                city=r.get("city", ""),
                state=r.get("state", ""),
                zip_code=r.get("zipCode", ""),
                price=float(price),
                acres=acres,
                beds=r.get("bedrooms"),
                baths=r.get("bathrooms"),
                sqft=r.get("squareFootage"),
                latitude=r.get("latitude"),
                longitude=r.get("longitude"),
                status=r.get("status", "Active"),
                listed_date=(r.get("listedDate") or "")[:10] or None,
                url=_listing_url(r),
            ))
        out.sort(key=lambda x: x.price)
        return out


def _listing_url(r: dict) -> str:
    addr = (r.get("formattedAddress") or "").replace(" ", "-").replace(",", "")
    return f"https://www.google.com/search?q={addr}+for+sale" if addr else "https://www.rentcast.io"
