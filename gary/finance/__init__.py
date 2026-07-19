"""Personal finance: net worth, debt payoff, and health recommendations.

Data is entered/imported by the user and persisted locally (no bank access).
Real account aggregation (e.g. Plaid) is a future seam that would populate the
same ``Profile`` model.
"""

from gary.finance.advice import financial_health
from gary.finance.debt import compare_strategies, payoff_plan
from gary.finance.models import Asset, Debt, Profile
from gary.finance.networth import net_worth, net_worth_breakdown, record_snapshot
from gary.finance.store import ProfileStore, sample_profile

__all__ = [
    "Asset",
    "Debt",
    "Profile",
    "net_worth",
    "net_worth_breakdown",
    "record_snapshot",
    "payoff_plan",
    "compare_strategies",
    "financial_health",
    "ProfileStore",
    "sample_profile",
]
