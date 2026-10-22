import numpy as np

from pipeline.cointegration.half_life import estimate_half_life


def test_known_ar1_lambda_recovers_theoretical_half_life():
    rng = np.random.default_rng(1)
    lam = 0.95
    n = 2000
    spread = np.zeros(n)
    for t in range(1, n):
        spread[t] = lam * spread[t - 1] + rng.normal(0, 0.1)

    half_life = estimate_half_life(spread)
    theoretical = -np.log(2) / np.log(lam)
    assert half_life is not None
    assert abs(half_life - theoretical) / theoretical < 0.15  # within 15% at this sample size


def test_random_walk_has_no_meaningful_half_life():
    # A true random walk has lambda = 1 (no mean reversion), but finite-sample OLS on a
    # near-unit-root series is biased *below* 1 (the well-known Dickey-Fuller bias), so
    # estimate_half_life can return a very large finite number instead of None here -- that's
    # mathematically correct given the (0, 1) contract, not a bug. The property that actually
    # matters: it's never a *short*, practically-meaningful half-life.
    rng = np.random.default_rng(2)
    spread = np.cumsum(rng.normal(0, 1, 500))
    half_life = estimate_half_life(spread)
    # Well beyond the FRD's own 5-60 day "sane" half-life band (Section 8.5) -- i.e. not
    # practically mean-reverting, even if not literally None.
    assert half_life is None or half_life > 150


def test_too_short_series_returns_none():
    assert estimate_half_life([1.0, 2.0]) is None


def test_explosive_series_returns_none():
    spread = np.array([1.0 * (1.5**i) for i in range(20)])
    assert estimate_half_life(spread) is None
