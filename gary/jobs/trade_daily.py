"""Daily forward paper-trading job.

Advances the *persisted* paper account one step using the latest prices and
records an equity snapshot, so the bot accrues a real forward track record over
time (distinct from a from-scratch backtest). Designed to be invoked by a
scheduler (e.g. GitHub Actions), like ``gary.jobs.daily_post``.

It is **paper-only and safe by default**: it never sends real orders. Going live
requires the env-gated Robinhood Crypto seam (``TRADING_LIVE=1`` +
``ROBINHOOD_API_KEY``/``ROBINHOOD_PRIVATE_KEY``); this job reports whether that
is configured but does not route orders there.

CLI:
    python -m gary.jobs.trade_daily [--days N to (re)optimize first] [--out out/]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gary.trading import RobinhoodCryptoBroker, TradingBot, TradingStore


def run_once(store: TradingStore | None = None, use_live: bool = True) -> dict[str, Any]:
    """Step the persisted paper account forward once and record equity."""
    store = store or TradingStore()
    config, broker = store.load()
    bot = TradingBot(config=config, broker=broker, use_live=use_live)
    result = bot.step_live()
    store.save(config, bot.broker)
    history = store.record_equity(result["date"], result["equity"])
    live = RobinhoodCryptoBroker.from_env()
    return {
        "date": result["date"],
        "equity": result["equity"],
        "actions": result["actions"],
        "account": result["account"],
        "equity_history_points": len(history),
        "mode": "paper",
        "live_broker_configured": live is not None,
        "live_trading_enabled": bool(live and live.live_enabled),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Daily forward paper-trading step")
    parser.add_argument("--out", default="out", help="directory for the run manifest")
    parser.add_argument("--offline", action="store_true", help="use offline synthetic prices")
    args = parser.parse_args(argv)

    summary = run_once(use_live=not args.offline)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    manifest = out_dir / f"trade_{stamp}.json"
    manifest.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"[trade_daily] {summary['date']} equity=${summary['equity']:,.2f} "
          f"actions={len(summary['actions'])} mode={summary['mode']} "
          f"live_configured={summary['live_broker_configured']}")
    print(f"[trade_daily] manifest -> {manifest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
