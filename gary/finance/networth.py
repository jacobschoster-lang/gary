"""Net worth calculation and history tracking."""

from __future__ import annotations

from datetime import date
from typing import Any

from gary.finance.models import Profile


def net_worth(profile: Profile) -> float:
    assets = sum(a.value for a in profile.assets)
    debts = sum(d.balance for d in profile.debts)
    return round(assets - debts, 2)


def net_worth_breakdown(profile: Profile) -> dict[str, Any]:
    total_assets = round(sum(a.value for a in profile.assets), 2)
    total_debts = round(sum(d.balance for d in profile.debts), 2)
    by_kind: dict[str, float] = {}
    for a in profile.assets:
        by_kind[a.kind] = round(by_kind.get(a.kind, 0.0) + a.value, 2)
    return {
        "net_worth": round(total_assets - total_debts, 2),
        "total_assets": total_assets,
        "total_debts": total_debts,
        "assets_by_kind": by_kind,
    }


def record_snapshot(profile: Profile, on: date | None = None) -> dict[str, Any]:
    """Append (or replace) today's net-worth snapshot in the history."""
    on = on or date.today()
    stamp = on.isoformat()
    value = net_worth(profile)
    profile.networth_history = [h for h in profile.networth_history if h.get("date") != stamp]
    snap = {"date": stamp, "value": value}
    profile.networth_history.append(snap)
    profile.networth_history.sort(key=lambda h: h["date"])
    return snap
