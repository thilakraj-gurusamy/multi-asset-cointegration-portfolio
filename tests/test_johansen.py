import numpy as np

from pipeline.cointegration.johansen import run_johansen


def test_bivariate_cointegrated_pair_has_rank_at_least_1():
    rng = np.random.default_rng(5)
    n = 300
    common = np.cumsum(rng.normal(0, 1, n))
    series_a = common + rng.normal(0, 0.3, n)
    series_b = 2 * common + rng.normal(0, 0.3, n)

    result = run_johansen(["A", "B"], np.column_stack([series_a, series_b]))

    assert result.cointegration_rank >= 1
    assert len(result.cointegrating_vectors) == result.cointegration_rank
    assert len(result.cointegrating_vectors[0]) == 2
    assert result.half_life_days_primary is not None
    assert result.deterministic_term == "ci"


def test_independent_random_walks_have_rank_zero():
    rng = np.random.default_rng(13)
    n = 300
    series_a = np.cumsum(rng.normal(0, 1, n))
    series_b = np.cumsum(rng.normal(0, 1, n))

    result = run_johansen(["A", "B"], np.column_stack([series_a, series_b]))

    assert result.cointegration_rank == 0
    assert result.cointegrating_vectors == []
    assert result.adjustment_speeds == []
    assert result.half_life_days_primary is None


def test_three_asset_basket_with_common_trend_finds_cointegration():
    rng = np.random.default_rng(9)
    n = 300
    common = np.cumsum(rng.normal(0, 1, n))
    series_a = common + rng.normal(0, 0.2, n)
    series_b = 1.5 * common + rng.normal(0, 0.2, n)
    series_c = 0.5 * common + rng.normal(0, 0.2, n)

    result = run_johansen(["A", "B", "C"], np.column_stack([series_a, series_b, series_c]))

    assert result.cointegration_rank >= 1
    assert result.lag_order >= 1
