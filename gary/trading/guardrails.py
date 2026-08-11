"""Trading guardrails: manual kill switch + loss/drawdown circuit breakers.

A safety layer for the forward paper/live loop. Given the current equity, the
day's starting equity, and the all-time high-water mark, it decides whether the
bot may OPEN NEW positions. Risk-reducing exits should always be allowed even
when tripped — only new risk is halted. Pure/evaluable, so it's fully testable.

Env (all optional):
    TRADING_HALT=1            manual kill switch — halt all new entries
    GARY_MAX_DAILY_LOSS_PCT   e.g. 0.05 -> halt new entries after -5% on the day
    GARY_MAX_DRAWDOWN_PCT     e.g. 0.20 -> halt new entries at 20% off the peak
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass
class Guardrails:
    max_daily_loss_pct: float = 0.0  # fraction; 0 disables
    max_drawdown_pct: float = 0.0  # fraction; 0 disables
    halted: bool = False  # manual kill switch

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Guardrails:
        env = env if env is not None else dict(os.environ)

        def num(key: str) -> float:
            try:
                return float(env.get(key, "") or 0.0)
            except ValueError:
                return 0.0

        return cls(
            max_daily_loss_pct=num("GARY_MAX_DAILY_LOSS_PCT"),
            max_drawdown_pct=num("GARY_MAX_DRAWDOWN_PCT"),
            halted=env.get("TRADING_HALT", "").strip() in ("1", "true", "yes"),
        )

    def evaluate(self, equity: float, day_start_equity: float,
                 high_water: float) -> dict[str, Any]:
        """Decide whether new entries are allowed given current equity."""
        reasons: list[str] = []
        daily_pnl_pct = ((equity / day_start_equity - 1) * 100
                         if day_start_equity > 0 else 0.0)
        drawdown_pct = ((high_water - equity) / high_water * 100
                        if high_water > 0 else 0.0)
        if self.halted:
            reasons.append("manual kill switch (TRADING_HALT)")
        if self.max_daily_loss_pct > 0 and daily_pnl_pct <= -self.max_daily_loss_pct * 100:
            reasons.append(
                f"daily loss {daily_pnl_pct:.1f}% <= -{self.max_daily_loss_pct * 100:.0f}%")
        if self.max_drawdown_pct > 0 and drawdown_pct >= self.max_drawdown_pct * 100:
            reasons.append(
                f"drawdown {drawdown_pct:.1f}% >= {self.max_drawdown_pct * 100:.0f}%")
        return {
            "allow_new_entries": not reasons,
            "tripped": bool(reasons),
            "reasons": reasons,
            "daily_pnl_pct": round(daily_pnl_pct, 2),
            "drawdown_pct": round(drawdown_pct, 2),
        }
