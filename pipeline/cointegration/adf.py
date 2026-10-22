"""ADF stationarity pre-test (FRD Section 8.2): every series must be confirmed I(1) --
non-stationary in levels, stationary in first differences -- before it is allowed into any
cointegration test. A series failing this is excluded and logged, never force-fit.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from statsmodels.tsa.stattools import adfuller

# Conventional cutoff for reading the ADF test's own p-value. This is how an ADF result is
# interpreted, full stop -- it is NOT a Phase 3 health-gating threshold (that system uses its
# own, separately-calibrated bands on top of these raw results).
ADF_SIGNIFICANCE = 0.05


@dataclass(frozen=True)
class AdfResult:
    series_type: str  # "levels" | "first_diff"
    test_statistic: float
    p_value: float
    n_obs: int
    lags_used: int
    is_stationary: bool


@dataclass(frozen=True)
class I1CheckResult:
    levels: AdfResult
    first_diff: AdfResult
    is_i1: bool


def run_adf(series, series_type: str) -> AdfResult:
    stat, p_value, lags_used, n_obs, _crit_values, _icbest = adfuller(series, autolag="AIC")
    return AdfResult(
        series_type=series_type,
        test_statistic=float(stat),
        p_value=float(p_value),
        n_obs=int(n_obs),
        lags_used=int(lags_used),
        is_stationary=bool(p_value < ADF_SIGNIFICANCE),
    )


def check_i1(closes) -> I1CheckResult:
    """closes: price levels for one series over the window, in time order."""
    closes = np.asarray(closes, dtype=float)
    levels = run_adf(closes, "levels")
    first_diff = run_adf(np.diff(closes), "first_diff")
    is_i1 = (not levels.is_stationary) and first_diff.is_stationary
    return I1CheckResult(levels=levels, first_diff=first_diff, is_i1=is_i1)
