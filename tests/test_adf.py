import numpy as np

from pipeline.cointegration.adf import check_i1, run_adf


def test_stationary_white_noise_is_stationary():
    rng = np.random.default_rng(42)
    series = rng.normal(0, 1, 300)
    result = run_adf(series, "levels")
    assert result.is_stationary


def test_random_walk_levels_are_not_stationary():
    rng = np.random.default_rng(42)
    series = np.cumsum(rng.normal(0, 1, 300))
    result = run_adf(series, "levels")
    assert not result.is_stationary


def test_random_walk_is_confirmed_i1():
    rng = np.random.default_rng(7)
    series = np.cumsum(rng.normal(0, 1, 300))
    result = check_i1(series)
    assert result.is_i1
    assert not result.levels.is_stationary
    assert result.first_diff.is_stationary


def test_stationary_series_is_not_i1():
    rng = np.random.default_rng(7)
    series = rng.normal(0, 1, 300)
    result = check_i1(series)
    assert not result.is_i1
