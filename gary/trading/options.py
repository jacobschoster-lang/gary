"""Black-Scholes options-pricing pure functions for the trading bot.

European option prices, delta, the standard greeks (gamma/vega/theta) and an
implied-volatility solver, all in closed form via the standard Black-Scholes
model. Everything here is pure: no I/O, no network, standard library only
(``math`` plus ``statistics.NormalDist`` for the normal CDF/PDF).

Inputs are handled defensively -- degenerate inputs (non-positive time,
volatility, spot or strike) fall back to intrinsic value or zeros rather than
raising or dividing by zero, so callers can feed partial data without guarding
every call.

Conventions: times ``t`` are in YEARS; rates ``r`` and volatilities ``sigma``
are annualized decimals (e.g. ``r=0.04``, ``sigma=0.2``). ``kind`` is one of
``{'call', 'put'}`` (case-insensitive).
"""

from __future__ import annotations

import math
from statistics import NormalDist

_NORM = NormalDist()


def _is_call(kind: str) -> bool:
    """True for a call, False for a put (defaults to call for unknown input)."""
    return str(kind).strip().lower() != "put"


def _d1_d2(S: float, K: float, t: float, r: float, sigma: float) -> tuple[float, float]:
    """The Black-Scholes ``d1``/``d2`` terms. Callers guard degenerate inputs."""
    vol_sqrt_t = sigma * math.sqrt(t)
    d1 = (math.log(S / K) + (r + sigma * sigma / 2.0) * t) / vol_sqrt_t
    d2 = d1 - vol_sqrt_t
    return d1, d2


def intrinsic(kind: str, S: float, K: float) -> float:
    """Intrinsic value: ``max(S-K, 0)`` for a call, ``max(K-S, 0)`` for a put."""
    if _is_call(kind):
        return max(S - K, 0.0)
    return max(K - S, 0.0)


def bs_price(kind: str, S: float, K: float, t: float, r: float, sigma: float) -> float:
    """Black-Scholes price of a European option.

    Returns ``intrinsic(kind, S, K)`` when there is no time value (``t <= 0`` or
    ``sigma <= 0``). Returns ``0.0`` for nonsensical inputs like ``S <= 0`` or
    ``K <= 0``. Never raises.
    """
    if t <= 0 or sigma <= 0:
        return intrinsic(kind, S, K)
    if S <= 0 or K <= 0:
        return 0.0
    d1, d2 = _d1_d2(S, K, t, r, sigma)
    discount = math.exp(-r * t)
    if _is_call(kind):
        return S * _NORM.cdf(d1) - K * discount * _NORM.cdf(d2)
    return K * discount * _NORM.cdf(-d2) - S * _NORM.cdf(-d1)


def bs_delta(kind: str, S: float, K: float, t: float, r: float, sigma: float) -> float:
    """Option delta.

    Call delta is ``N(d1)`` in ``(0, 1)``; put delta is ``N(d1) - 1`` in
    ``(-1, 0)``. When there is no time value (``t <= 0`` or ``sigma <= 0``),
    return a boundary delta: ``1`` (ITM) or ``0`` (OTM) for a call, ``-1`` (ITM)
    or ``0`` (OTM) for a put. Never raises.
    """
    call = _is_call(kind)
    if t <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if call:
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1, _ = _d1_d2(S, K, t, r, sigma)
    nd1 = _NORM.cdf(d1)
    return nd1 if call else nd1 - 1.0


def bs_greeks(kind: str, S: float, K: float, t: float, r: float, sigma: float) -> dict:
    """Return ``{'delta', 'gamma', 'vega', 'theta'}`` as floats.

    ``gamma`` and ``vega`` are the standard Black-Scholes greeks; ``vega`` is per
    ``1.00`` change in ``sigma`` (not per 1%) and ``theta`` is per YEAR
    (annualized). ``delta`` comes from :func:`bs_delta`. Degenerate inputs yield
    zeros where a greek is undefined. Never raises.
    """
    delta = bs_delta(kind, S, K, t, r, sigma)
    if t <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": delta, "gamma": 0.0, "vega": 0.0, "theta": 0.0}

    d1, d2 = _d1_d2(S, K, t, r, sigma)
    sqrt_t = math.sqrt(t)
    pdf_d1 = _NORM.pdf(d1)
    discount = math.exp(-r * t)

    gamma = pdf_d1 / (S * sigma * sqrt_t)
    vega = S * pdf_d1 * sqrt_t
    common_theta = -(S * pdf_d1 * sigma) / (2.0 * sqrt_t)
    if _is_call(kind):
        theta = common_theta - r * K * discount * _NORM.cdf(d2)
    else:
        theta = common_theta + r * K * discount * _NORM.cdf(-d2)

    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta}


def implied_vol(
    kind: str,
    price: float,
    S: float,
    K: float,
    t: float,
    r: float,
    lo: float = 1e-4,
    hi: float = 5.0,
    tol: float = 1e-6,
    max_iter: int = 100,
) -> float:
    """Implied volatility via bisection on :func:`bs_price`.

    Returns ``0.0`` if ``price`` is at or below intrinsic value (no time value to
    solve for) or if the search cannot bracket/converge within ``[lo, hi]``.
    Never raises.
    """
    if t <= 0 or S <= 0 or K <= 0 or hi <= lo:
        return 0.0
    if price <= intrinsic(kind, S, K):
        return 0.0

    f_lo = bs_price(kind, S, K, t, r, lo) - price
    f_hi = bs_price(kind, S, K, t, r, hi) - price
    if f_lo == 0.0:
        return lo
    if f_hi == 0.0:
        return hi
    # Price is monotonically increasing in sigma; a valid target must sit in the bracket.
    if f_lo > 0 or f_hi < 0:
        return 0.0

    for _ in range(max_iter):
        mid = (lo + hi) / 2.0
        f_mid = bs_price(kind, S, K, t, r, mid) - price
        if abs(f_mid) < tol or (hi - lo) / 2.0 < tol:
            return mid
        if f_mid < 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
