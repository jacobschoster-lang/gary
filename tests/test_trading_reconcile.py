from __future__ import annotations

from gary.trading.reconcile import (
    blocking_reasons,
    diff_positions,
    is_reconciled,
)


def test_identical_lists_reconciled():
    expected = [{"symbol": "AAPL", "quantity": 10.0}, {"symbol": "NVDA", "quantity": -5.0}]
    actual = [{"symbol": "NVDA", "quantity": -5.0}, {"symbol": "AAPL", "quantity": 10.0}]

    assert is_reconciled(expected, actual) is True
    assert blocking_reasons(expected, actual) == []

    diff = diff_positions(expected, actual)
    assert diff["matched"] == ["AAPL", "NVDA"]
    assert diff["missing"] == []
    assert diff["extra"] == []
    assert diff["quantity_mismatch"] == []


def test_quantity_mismatch_beyond_tolerance():
    expected = [{"symbol": "NVDA", "quantity": 10.0}]
    actual = [{"symbol": "NVDA", "quantity": 8.0}]

    diff = diff_positions(expected, actual)
    assert diff["quantity_mismatch"] == [
        {"symbol": "NVDA", "expected_qty": 10.0, "actual_qty": 8.0}
    ]
    assert diff["matched"] == []
    assert is_reconciled(expected, actual) is False
    assert blocking_reasons(expected, actual) == ["NVDA: expected 10.0, broker 8.0"]


def test_expected_missing_at_broker():
    expected = [{"symbol": "AAPL", "quantity": 10.0}]
    actual: list[dict] = []

    diff = diff_positions(expected, actual)
    assert diff["missing"] == [{"symbol": "AAPL", "expected_qty": 10.0}]
    assert diff["extra"] == []
    assert is_reconciled(expected, actual) is False
    assert blocking_reasons(expected, actual) == ["missing at broker: AAPL (10.0)"]


def test_near_zero_at_broker_counts_as_missing():
    expected = [{"symbol": "AAPL", "quantity": 10.0}]
    actual = [{"symbol": "AAPL", "quantity": 1e-9}]

    diff = diff_positions(expected, actual)
    assert diff["missing"] == [{"symbol": "AAPL", "expected_qty": 10.0}]
    assert diff["matched"] == []
    assert is_reconciled(expected, actual) is False


def test_broker_extra_position():
    expected: list[dict] = []
    actual = [{"symbol": "TSLA", "quantity": 5.0}]

    diff = diff_positions(expected, actual)
    assert diff["extra"] == [{"symbol": "TSLA", "actual_qty": 5.0}]
    assert diff["missing"] == []
    assert is_reconciled(expected, actual) is False
    assert blocking_reasons(expected, actual) == ["unexpected at broker: TSLA (5.0)"]


def test_within_tolerance_counts_as_matched():
    expected = [{"symbol": "AAPL", "quantity": 10.0}]
    actual = [{"symbol": "AAPL", "quantity": 10.0 + 5e-7}]

    diff = diff_positions(expected, actual)
    assert diff["matched"] == ["AAPL"]
    assert diff["quantity_mismatch"] == []
    assert is_reconciled(expected, actual) is True
    assert blocking_reasons(expected, actual) == []


def test_duplicate_symbols_are_summed():
    expected = [
        {"symbol": "AAPL", "quantity": 4.0},
        {"symbol": "AAPL", "quantity": 6.0},
    ]
    actual = [{"symbol": "AAPL", "quantity": 10.0}]

    diff = diff_positions(expected, actual)
    assert diff["matched"] == ["AAPL"]
    assert is_reconciled(expected, actual) is True

    # Duplicates that sum to a mismatch are still caught.
    actual_bad = [
        {"symbol": "AAPL", "quantity": 3.0},
        {"symbol": "AAPL", "quantity": 3.0},
    ]
    diff_bad = diff_positions(expected, actual_bad)
    assert diff_bad["quantity_mismatch"] == [
        {"symbol": "AAPL", "expected_qty": 10.0, "actual_qty": 6.0}
    ]
    assert is_reconciled(expected, actual_bad) is False


def test_empty_vs_empty_is_reconciled():
    assert is_reconciled([], []) is True
    assert blocking_reasons([], []) == []
    assert diff_positions([], []) == {
        "matched": [],
        "missing": [],
        "extra": [],
        "quantity_mismatch": [],
    }


def test_positions_that_net_to_zero_are_absent():
    expected = [
        {"symbol": "AAPL", "quantity": 5.0},
        {"symbol": "AAPL", "quantity": -5.0},
    ]
    actual: list[dict] = []

    assert is_reconciled(expected, actual) is True
    assert diff_positions(expected, actual)["missing"] == []
