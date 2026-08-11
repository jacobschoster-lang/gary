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
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gary.trading import (
    RobinhoodCryptoBroker,
    RobinhoodMcpBroker,
    TradingBot,
    TradingStore,
    alerts,
    reconcile,
)
from gary.trading.guardrails import Guardrails
from gary.trading.options_backtest import OptionsPaperTrader, OptionsStore


def _broker_positions(mcp: RobinhoodMcpBroker) -> list[dict]:
    """Best-effort coercion of the MCP get_positions result to [{symbol,quantity}]."""
    raw = mcp.get_positions()
    rows = raw if isinstance(raw, list) else (raw or {}).get("positions", [])
    out = []
    for p in rows or []:
        if isinstance(p, dict) and p.get("symbol") is not None:
            out.append({"symbol": str(p["symbol"]), "quantity": float(p.get("quantity", 0) or 0)})
    return out


def run_once(
    store: TradingStore | None = None,
    options_store: OptionsStore | None = None,
    use_live: bool = True,
    guardrails: Guardrails | None = None,
    mcp: RobinhoodMcpBroker | None = None,
    alert_transport: Callable | None = None,
    env: dict | None = None,
) -> dict[str, Any]:
    """Step the persisted paper accounts (equities/crypto + options) forward once,
    gated by guardrails + (when a live broker is configured) position reconciliation,
    and push an alert summary."""
    store = store or TradingStore()
    config, broker = store.load()

    # Guardrails: compare the CURRENT marked equity to the day-start (prior close)
    # and the all-time high-water mark so the loss/drawdown breakers actually trip.
    guard = guardrails if guardrails is not None else Guardrails.from_env(env)
    hist = store.equity_history()
    day_start_equity = hist[-1]["equity"] if hist else config.starting_cash
    pre = TradingBot(config=config, broker=broker, use_live=use_live).status()
    current_equity = pre["end_equity"]
    high_water = max([h["equity"] for h in hist] + [config.starting_cash, current_equity])
    g = guard.evaluate(current_equity, day_start_equity, high_water)
    allow_new = g["allow_new_entries"]

    # Reconcile against the live broker if configured (state-drift safety).
    mcp = mcp if mcp is not None else RobinhoodMcpBroker.from_env(env)
    reconciliation = None
    if mcp is not None:
        expected = [{"symbol": s, "quantity": p.quantity} for s, p in broker.positions.items()]
        try:
            actual = _broker_positions(mcp)
            reconciled = reconcile.is_reconciled(expected, actual)
            reconciliation = {"reconciled": reconciled,
                              "reasons": reconcile.blocking_reasons(expected, actual)}
        except Exception as exc:  # any MCP failure -> don't open new risk
            reconciliation = {"reconciled": False, "error": str(exc)}
            reconciled = False
        if not reconciled:
            allow_new = False

    result = TradingBot(config=config, broker=broker, use_live=use_live).step_live(
        allow_new_entries=allow_new)
    store.save(config, broker)
    history = store.record_equity(result["date"], result["equity"])

    options_store = options_store or OptionsStore()
    ocfg, ostate = options_store.load()
    ostep = OptionsPaperTrader(config=ocfg, use_live=use_live).step(
        ostate, on=result["date"], allow_new_entries=allow_new)
    options_store.save(ocfg, ostate)

    live = RobinhoodCryptoBroker.from_env(env)
    summary = {
        "date": result["date"],
        "equity": result["equity"],
        "actions": result["actions"],
        "account": result["account"],
        "equity_history_points": len(history),
        "options": {
            "symbol": ostep["symbol"], "strategy": ostep["strategy"],
            "action": ostep["action"], "equity": ostep["equity"],
            "position": ostep["position"],
            "equity_history_points": ostep["equity_history_points"],
        },
        "guardrails": g,
        "reconciliation": reconciliation,
        "new_entries_allowed": allow_new,
        "mode": "paper",
        "live_broker_configured": (live is not None) or (mcp is not None),
        "live_trading_enabled": bool((live and live.live_enabled) or (mcp and mcp.live_enabled)),
    }
    summary["alert_sent"] = alerts.send_alert(
        alerts.format_daily_summary(summary), transport=alert_transport, env=env)
    return summary


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

    opt = summary["options"]
    print(f"[trade_daily] {summary['date']} equity=${summary['equity']:,.2f} "
          f"actions={len(summary['actions'])} mode={summary['mode']} "
          f"live_configured={summary['live_broker_configured']}")
    print(f"[trade_daily] options[{opt['symbol']}/{opt['strategy']}] {opt['action']} "
          f"equity=${opt['equity']:,.2f}")
    print(f"[trade_daily] manifest -> {manifest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
