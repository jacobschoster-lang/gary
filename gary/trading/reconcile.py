"""Position-reconciliation pure functions for the trading bot.

Before a live trading step the bot must confirm that its own view of the open
positions matches what the broker actually reports (via an MCP ``get_positions``
call). Any mismatch means state has drifted and we must refuse to trade.

Everything here is pure: no I/O, no network, standard library only. Inputs are
handled defensively -- empty inputs are valid and nothing here raises, so
callers can feed partial or malformed data without guarding every call.

Positions are dicts with at least ``'symbol'`` (str) and ``'quantity'`` (float,
which may be negative for shorts). Duplicate symbols within one list are summed
before comparison, and a symbol whose absolute quantity is within ``qty_tol`` is
treated as absent.
"""

from __future__ import annotations


def _aggregate(positions: list[dict]) -> dict[str, float]:
    """Sum quantities by symbol, ignoring entries without a usable symbol."""
    totals: dict[str, float] = {}
    for pos in positions:
        symbol = pos.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        try:
            qty = float(pos.get("quantity", 0.0))
        except (TypeError, ValueError):
            qty = 0.0
        totals[symbol] = totals.get(symbol, 0.0) + qty
    return totals


def diff_positions(expected: list[dict], actual: list[dict], qty_tol: float = 1e-6) -> dict:
    """Compare two position lists keyed by ``'symbol'`` (summing duplicates).

    Returns a dict::

        {
            'matched': [symbol, ...],                  # both sides, qty within tol
            'missing': [{'symbol', 'expected_qty'}],   # expected but ~absent at broker
            'extra':   [{'symbol', 'actual_qty'}],     # at broker but not expected
            'quantity_mismatch': [{'symbol', 'expected_qty', 'actual_qty'}],
        }

    A symbol with ``abs(qty) <= qty_tol`` is treated as absent. Ordering is
    deterministic (every list is sorted by symbol).
    """
    exp = _aggregate(expected)
    act = _aggregate(actual)

    def present(totals: dict[str, float], symbol: str) -> bool:
        return abs(totals.get(symbol, 0.0)) > qty_tol

    matched: list[str] = []
    missing: list[dict] = []
    extra: list[dict] = []
    quantity_mismatch: list[dict] = []

    for symbol in sorted(set(exp) | set(act)):
        in_exp = present(exp, symbol)
        in_act = present(act, symbol)
        exp_qty = exp.get(symbol, 0.0)
        act_qty = act.get(symbol, 0.0)

        if in_exp and not in_act:
            missing.append({"symbol": symbol, "expected_qty": exp_qty})
        elif in_act and not in_exp:
            extra.append({"symbol": symbol, "actual_qty": act_qty})
        elif in_exp and in_act:
            if abs(exp_qty - act_qty) <= qty_tol:
                matched.append(symbol)
            else:
                quantity_mismatch.append(
                    {"symbol": symbol, "expected_qty": exp_qty, "actual_qty": act_qty}
                )
        # neither side present (both ~0): nothing to report.

    return {
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "quantity_mismatch": quantity_mismatch,
    }


def is_reconciled(expected: list[dict], actual: list[dict], qty_tol: float = 1e-6) -> bool:
    """``True`` iff the diff has no missing, extra, or quantity_mismatch entries."""
    diff = diff_positions(expected, actual, qty_tol)
    return not (diff["missing"] or diff["extra"] or diff["quantity_mismatch"])


def blocking_reasons(expected: list[dict], actual: list[dict], qty_tol: float = 1e-6) -> list[str]:
    """Human-readable strings for each discrepancy; empty if reconciled.

    Examples: ``'NVDA: expected 10.0, broker 8.0'``,
    ``'missing at broker: AAPL (10.0)'``, ``'unexpected at broker: TSLA (5.0)'``.
    """
    diff = diff_positions(expected, actual, qty_tol)
    reasons: list[str] = []
    for item in diff["quantity_mismatch"]:
        reasons.append(
            f"{item['symbol']}: expected {item['expected_qty']}, broker {item['actual_qty']}"
        )
    for item in diff["missing"]:
        reasons.append(f"missing at broker: {item['symbol']} ({item['expected_qty']})")
    for item in diff["extra"]:
        reasons.append(f"unexpected at broker: {item['symbol']} ({item['actual_qty']})")
    return reasons
