"""Spread construction (FRD Section 8.6): from the Johansen cointegrating vector for a basket,
or the Engle-Granger hedge ratio for a simple pair.

A pair's hedge ratio is just the 2-leg special case of a basket's cointegrating vector --
weights=[1.0, -hedge_ratio] against legs=[regressand_symbol, regressor_symbol] -- so both
shapes reduce to the same weighted-dot-product spread.
"""
from __future__ import annotations

import numpy as np


def pair_weights(hedge_ratio: float) -> list[float]:
    return [1.0, -float(hedge_ratio)]


def compute_spread(prices_by_leg: list[np.ndarray], weights: list[float]) -> np.ndarray:
    """prices_by_leg[i] and weights[i] both correspond to the i-th leg, in the same order."""
    if len(prices_by_leg) != len(weights):
        raise ValueError(f"{len(prices_by_leg)} price series but {len(weights)} weights")
    price_matrix = np.column_stack(prices_by_leg)
    return price_matrix @ np.asarray(weights, dtype=float)
