"""Real-estate listing search (land/acreage focused).

Pulls active for-sale listings from RentCast when ``RENTCAST_API_KEY`` is set,
and otherwise falls back to a small labeled sample dataset so the feature is
usable offline. Filters by radius, minimum acreage, and maximum price.
"""

from gary.realestate.models import Listing
from gary.realestate.search import CITY_COORDS, search_listings

__all__ = ["Listing", "search_listings", "CITY_COORDS"]
