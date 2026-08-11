"""Unit tests for the Black-Scholes options-pricing functions."""

from __future__ import annotations

import math

from gary.trading.options import (
    bs_delta,
    bs_greeks,
    bs_price,
    implied_vol,
    intrinsic,
)


def test_intrinsic_call_and_put():
    assert intrinsic("call", 110.0, 100.0) == 10.0
    assert intrinsic("call", 90.0, 100.0) == 0.0
    assert intrinsic("put", 90.0, 100.0) == 10.0
    assert intrinsic("put", 110.0, 100.0) == 0.0


def test_intrinsic_never_negative():
    assert intrinsic("call", 50.0, 100.0) >= 0.0
    assert intrinsic("put", 150.0, 100.0) >= 0.0


def test_bs_price_atm_call_positive_and_below_spot():
    price = bs_price("call", 100.0, 100.0, 1.0, 0.0, 0.2)
    assert price > 0.0
    assert price < 100.0


def test_bs_price_t_zero_returns_intrinsic():
    assert bs_price("call", 120.0, 100.0, 0.0, 0.05, 0.2) == intrinsic("call", 120.0, 100.0)
    assert bs_price("put", 80.0, 100.0, 0.0, 0.05, 0.2) == intrinsic("put", 80.0, 100.0)


def test_bs_price_sigma_zero_returns_intrinsic():
    assert bs_price("call", 120.0, 100.0, 1.0, 0.05, 0.0) == intrinsic("call", 120.0, 100.0)
    assert bs_price("put", 80.0, 100.0, 1.0, 0.05, 0.0) == intrinsic("put", 80.0, 100.0)


def test_bs_price_nonsensical_inputs_return_zero():
    assert bs_price("call", -5.0, 100.0, 1.0, 0.05, 0.2) == 0.0
    assert bs_price("call", 100.0, -5.0, 1.0, 0.05, 0.2) == 0.0


def test_put_call_parity():
    S, K, t, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.2
    call = bs_price("call", S, K, t, r, sigma)
    put = bs_price("put", S, K, t, r, sigma)
    assert abs((call - put) - (S - K * math.exp(-r * t))) < 1e-6


def test_bs_delta_ranges():
    call_delta = bs_delta("call", 100.0, 100.0, 1.0, 0.0, 0.2)
    put_delta = bs_delta("put", 100.0, 100.0, 1.0, 0.0, 0.2)
    assert 0.0 < call_delta < 1.0
    assert -1.0 < put_delta < 0.0


def test_bs_delta_deep_itm_and_otm_call():
    deep_itm = bs_delta("call", 1000.0, 100.0, 1.0, 0.0, 0.2)
    deep_otm = bs_delta("call", 1.0, 100.0, 1.0, 0.0, 0.2)
    assert deep_itm > 0.99
    assert deep_otm < 0.01


def test_bs_delta_boundary_no_time_value():
    assert bs_delta("call", 120.0, 100.0, 0.0, 0.0, 0.2) == 1.0
    assert bs_delta("call", 80.0, 100.0, 0.0, 0.0, 0.2) == 0.0
    assert bs_delta("put", 80.0, 100.0, 0.0, 0.0, 0.2) == -1.0
    assert bs_delta("put", 120.0, 100.0, 0.0, 0.0, 0.2) == 0.0


def test_bs_greeks_keys_and_signs():
    greeks = bs_greeks("call", 100.0, 100.0, 1.0, 0.0, 0.2)
    assert set(greeks.keys()) == {"delta", "gamma", "vega", "theta"}
    assert greeks["gamma"] > 0.0
    assert greeks["vega"] > 0.0
    assert 0.0 < greeks["delta"] < 1.0


def test_bs_greeks_degenerate_returns_zeros():
    greeks = bs_greeks("call", 100.0, 100.0, 0.0, 0.05, 0.2)
    assert greeks["gamma"] == 0.0
    assert greeks["vega"] == 0.0
    assert greeks["theta"] == 0.0
    assert greeks["delta"] == bs_delta("call", 100.0, 100.0, 0.0, 0.05, 0.2)


def test_implied_vol_round_trips_call():
    S, K, t, r, sigma = 100.0, 105.0, 0.5, 0.03, 0.3
    price = bs_price("call", S, K, t, r, sigma)
    recovered = implied_vol("call", price, S, K, t, r)
    assert abs(recovered - sigma) < 1e-3


def test_implied_vol_round_trips_put():
    S, K, t, r, sigma = 100.0, 95.0, 0.75, 0.02, 0.3
    price = bs_price("put", S, K, t, r, sigma)
    recovered = implied_vol("put", price, S, K, t, r)
    assert abs(recovered - sigma) < 1e-3


def test_implied_vol_price_at_or_below_intrinsic_returns_zero():
    intrinsic_val = intrinsic("call", 120.0, 100.0)
    assert implied_vol("call", intrinsic_val, 120.0, 100.0, 1.0, 0.05) == 0.0
    assert implied_vol("call", intrinsic_val - 1.0, 120.0, 100.0, 1.0, 0.05) == 0.0
