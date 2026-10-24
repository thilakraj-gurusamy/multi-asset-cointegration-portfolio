"""Hedge-ratio / cointegrating-vector drift between successive rolling windows -- the metric
Phase 2 deliberately did NOT compute (it only stores each window's own value).

A single formula handles both shapes: a scalar hedge ratio (pairs, from Engle-Granger) is just
the 1-dimensional case of a vector (baskets, from Johansen's cointegrating vector), so both use
the same relative-norm-change definition.
"""
from __future__ import annotations

import numpy as np


def compute_drift_pct(previous: float | list[float], current: float | list[float]) -> float | None:
    """Returns None when `previous` has zero norm (drift % is undefined against a zero
    baseline), rather than raising or returning a misleading infinity.
    """
    prev = np.atleast_1d(np.asarray(previous, dtype=float))
    curr = np.atleast_1d(np.asarray(current, dtype=float))

    prev_norm = np.linalg.norm(prev)
    if prev_norm == 0:
        return None

    return float(np.linalg.norm(curr - prev) / prev_norm * 100.0)
