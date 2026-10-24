"""Johansen procedure via VECM (FRD Section 8.2), for baskets of 2+ assets.

Used for:
  (a) every bivariate pair within an asset class, run specifically so Engle-Granger and
      Johansen can be directly compared on the exact same case (FRD: "on overlapping
      bivariate cases, run both... and report both verdicts"), and
  (b) the configured 3+-asset baskets (the FRD's actual Johansen requirement).

Two-step workflow, matching real-world practice:
  1. coint_johansen() gives the trace statistic and its critical values, used ONLY to pick the
     cointegration rank (via the trace test at the 95% critical value).
  2. If rank >= 1, a VECM is fit at that rank to get the cointegrating vectors (beta) and
     adjustment speeds/loadings (alpha) -- coint_johansen's own eigenvectors are a valid but
     differently-normalized basis; fitting the VECM directly is what actually gives "cointegrating
     vector(s) (basket weights) and adjustment speeds" as the FRD asks for.

Lag order is selected via AIC on the underlying VAR (statsmodels select_order); the
deterministic term is a fixed, explicit choice (restricted constant -- "ci" in VECM's own
notation, det_order=0 in Johansen's), recorded on every result row since it affects the trace
statistic's critical values.

Two things observed when validating this against real FX/equity history (not bugs -- verified
by independently re-running coint_johansen outside this module on the same data and getting
identical numbers):
  - Full-rank results (cointegration_rank == n_assets) occur occasionally (~5% of windows for
    the 3-asset FX triangle basket in testing) -- this is a known small-sample trace-test size
    distortion, more likely with short (~90-bar) windows and highly correlated series, not a
    sign the series aren't really I(1). Left as raw output; a results consumer should treat it
    as a degenerate/low-confidence case rather than "3 independent cointegrating relations".
  - half_life_days_primary is None in roughly half of rank>=1 cases in testing -- the trace
    test confirming rank>=1 at 95% does not guarantee the fitted AR(1) coefficient on that
    specific spread lands in the mean-reverting (0,1) range in a ~90-observation sample. This
    is exactly the gap Phase 3's health/half-life gating (FRD Section 8.5) exists to close:
    statistical significance alone does not imply a clean, tradeable spread.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from statsmodels.tsa.vector_ar.vecm import VECM, coint_johansen, select_order

from pipeline.cointegration.half_life import estimate_half_life

JOHANSEN_DET_ORDER = 0          # restricted constant, for the trace-test/rank step
VECM_DETERMINISTIC = "ci"       # restricted constant, for the VECM fit step -- same choice,
                                 # expressed in VECM's own string convention
MAX_LAG_SEARCH = 8
TRACE_CRIT_COLUMN = 1            # cvt columns are [90%, 95%, 99%]


@dataclass(frozen=True)
class JohansenResult:
    symbols: list[str]
    lag_order: int
    deterministic_term: str
    trace_stat_rank0: float
    trace_crit_90_rank0: float
    trace_crit_95_rank0: float
    trace_crit_99_rank0: float
    cointegration_rank: int
    cointegrating_vectors: list[list[float]]
    adjustment_speeds: list[list[float]]
    half_life_days_primary: float | None


def _select_lag_order(data: np.ndarray) -> int:
    n_obs = data.shape[0]
    maxlags = max(1, min(MAX_LAG_SEARCH, n_obs // 4 - 1))
    try:
        result = select_order(data, maxlags=maxlags, deterministic=VECM_DETERMINISTIC)
        chosen = int(result.aic)
        return max(1, chosen)
    except Exception:
        return 1


def run_johansen(symbols: list[str], data: np.ndarray) -> JohansenResult:
    """data: shape (n_obs, n_assets), columns aligned to `symbols`, in time order."""
    lag_order = _select_lag_order(data)
    k_ar_diff = max(0, lag_order - 1)

    johansen_test = coint_johansen(data, JOHANSEN_DET_ORDER, k_ar_diff)
    trace_stats = johansen_test.lr1
    trace_crit = johansen_test.cvt[:, TRACE_CRIT_COLUMN]

    rank = 0
    for stat, crit95 in zip(trace_stats, trace_crit):
        if stat > crit95:
            rank += 1
        else:
            break

    cointegrating_vectors: list[list[float]] = []
    adjustment_speeds: list[list[float]] = []
    half_life_primary = None

    if rank >= 1:
        vecm_fit = VECM(
            data, k_ar_diff=k_ar_diff, coint_rank=rank, deterministic=VECM_DETERMINISTIC
        ).fit()
        cointegrating_vectors = vecm_fit.beta.T.tolist()   # (rank, n_assets)
        adjustment_speeds = vecm_fit.alpha.tolist()         # (n_assets, rank)

        primary_vector = np.array(cointegrating_vectors[0])
        spread = data @ primary_vector
        half_life_primary = estimate_half_life(spread)

    return JohansenResult(
        symbols=symbols,
        lag_order=lag_order,
        deterministic_term=VECM_DETERMINISTIC,
        trace_stat_rank0=float(trace_stats[0]),
        trace_crit_90_rank0=float(johansen_test.cvt[0, 0]),
        trace_crit_95_rank0=float(trace_crit[0]),
        trace_crit_99_rank0=float(johansen_test.cvt[0, 2]),
        cointegration_rank=rank,
        cointegrating_vectors=cointegrating_vectors,
        adjustment_speeds=adjustment_speeds,
        half_life_days_primary=half_life_primary,
    )
