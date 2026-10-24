"""Rolling z-score normalization (FRD Section 8.6).

The lookback used to compute the mean/std is taken from the END of the in-sample fitting
window and then held FIXED for the entire out-of-sample segment that follows -- recomputing it
against out-of-sample data would be look-ahead bias. This is why `fit_zscore_stats` and
`z_score` are separate: the walk-forward engine calls `fit_zscore_stats` once per window using
only in-sample data, then reuses the same (mean, std) for every out-of-sample bar until the
next refit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ZScoreStats:
    mean: float
    std: float


def fit_zscore_stats(in_sample_spread: np.ndarray, lookback_bars: int) -> ZScoreStats:
    tail = np.asarray(in_sample_spread, dtype=float)[-lookback_bars:]
    return ZScoreStats(mean=float(np.mean(tail)), std=float(np.std(tail, ddof=0)))


def z_score(spread_value: float, stats: ZScoreStats) -> float | None:
    """None when std is (numerically) zero -- a z-score against a flat spread is undefined,
    not infinite/misleading.
    """
    if stats.std == 0 or not np.isfinite(stats.std):
        return None
    return (spread_value - stats.mean) / stats.std
