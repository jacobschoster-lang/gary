"""Robust parameter-selection pure functions for the walk-forward optimizer.

A grid-search optimizer evaluates many candidate configs, measuring each one
across several walk-forward TRAIN folds. Picking the single highest-return
candidate overfits: it rewards luck and multiple-testing bias. These helpers
instead reward candidates that are *stable* across folds and haircut the
winner's Sharpe for the fact that we tried many configs.

Everything here is pure: no I/O, no network, standard library only. Inputs are
handled defensively -- empty or degenerate inputs return ``0.0`` (or a sensible
default) rather than raising or dividing by zero.
"""

from __future__ import annotations

import math
import statistics


def robustness_score(returns: list[float], risk_aversion: float = 1.0) -> float:
    """Reward consistent returns: ``mean(returns) - risk_aversion * pstdev(returns)``.

    Uses the population standard deviation. ``0.0`` if ``returns`` is empty; a
    single value has zero dispersion so its score equals that value.
    """
    if not returns:
        return 0.0
    if len(returns) == 1:
        return float(returns[0])
    return statistics.fmean(returns) - risk_aversion * statistics.pstdev(returns)


def deflated_sharpe(observed_sharpe: float, n_trials: int, n_obs: int) -> float:
    """Haircut an observed (annualized) Sharpe for multiple-testing selection bias.

    Subtracts an estimate of the Sharpe you would expect as the MAX across
    ``n_trials`` independent random strategies given ``n_obs`` observations,
    using the standard approximation for the expected maximum of ``n_trials``
    standard normals, ``E[max] ~= sqrt(2*ln(n_trials))``, scaled by the
    per-observation Sharpe standard error ``1/sqrt(n_obs)``::

        expected_max = sqrt(2*ln(max(n_trials, 2))) / sqrt(max(n_obs, 1))
        return observed_sharpe - expected_max

    Returns ``observed_sharpe`` unchanged if ``n_trials <= 1``. Never raises.
    """
    if n_trials <= 1:
        return observed_sharpe
    expected_max = math.sqrt(2.0 * math.log(max(n_trials, 2))) / math.sqrt(max(n_obs, 1))
    return observed_sharpe - expected_max


def _mean(returns: list[float]) -> float:
    """Mean return, ``0.0`` for an empty list (tie-break helper)."""
    return statistics.fmean(returns) if returns else 0.0


def select_most_robust(
    candidates: list[dict],
    returns_key: str = "train_returns",
    risk_aversion: float = 1.0,
) -> dict | None:
    """Return the candidate with the highest robustness score.

    Scores each candidate's per-fold returns list at ``candidate[returns_key]``
    via :func:`robustness_score`, and returns a shallow copy of the winner with
    a ``'robustness'`` float attached. Ties are broken by higher mean return.
    Returns ``None`` if ``candidates`` is empty.
    """
    if not candidates:
        return None
    ranked = rank_by_robustness(candidates, returns_key, risk_aversion)
    return ranked[0]


def rank_by_robustness(
    candidates: list[dict],
    returns_key: str = "train_returns",
    risk_aversion: float = 1.0,
) -> list[dict]:
    """Rank candidates by robustness, most robust first.

    Returns shallow copies of every candidate, each with a ``'robustness'``
    key, sorted descending by robustness score. Ties are broken by higher mean
    return. Empty input yields ``[]``.
    """
    scored: list[dict] = []
    for candidate in candidates:
        fold_returns = list(candidate.get(returns_key) or [])
        copy = dict(candidate)
        copy["robustness"] = robustness_score(fold_returns, risk_aversion)
        scored.append(copy)
    scored.sort(
        key=lambda c: (c["robustness"], _mean(list(c.get(returns_key) or []))),
        reverse=True,
    )
    return scored
