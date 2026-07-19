"""Real-estate data models."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Listing:
    address: str
    city: str
    state: str
    zip_code: str
    price: float
    acres: float
    beds: float | None
    baths: float | None
    sqft: float | None
    latitude: float | None
    longitude: float | None
    status: str
    listed_date: str | None
    url: str
    distance_mi: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
