import numpy as np

from pipeline.cointegration.engle_granger import run_engle_granger, run_engle_granger_both_directions


def _cointegrated_pair(seed: int, n: int = 300):
    rng = np.random.default_rng(seed)
    common = np.cumsum(rng.normal(0, 1, n))
    series_a = common + rng.normal(0, 0.3, n)
    series_b = 2 * common + rng.normal(0, 0.3, n)
    return series_a, series_b


def _independent_walks(seed: int, n: int = 300):
    rng = np.random.default_rng(seed)
    series_a = np.cumsum(rng.normal(0, 1, n))
    series_b = np.cumsum(rng.normal(0, 1, n))
    return series_a, series_b


def test_cointegrated_pair_is_significant_and_recovers_hedge_ratio():
    series_a, series_b = _cointegrated_pair(seed=3)
    result = run_engle_granger(series_a, series_b, "A", "B")
    assert result.is_significant_5pct
    assert abs(result.hedge_ratio - 0.5) < 0.1
    assert result.half_life_days is not None


def test_independent_random_walks_are_not_significant():
    series_a, series_b = _independent_walks(seed=11)
    result = run_engle_granger(series_a, series_b, "A", "B")
    assert not result.is_significant_5pct


def test_both_directions_are_computed_and_labelled():
    series_a, series_b = _cointegrated_pair(seed=3)
    forward, reverse = run_engle_granger_both_directions("A", series_a, "B", series_b)
    assert forward.regressand_symbol == "A" and forward.regressor_symbol == "B"
    assert reverse.regressand_symbol == "B" and reverse.regressor_symbol == "A"
    # Both directions should agree on cointegration being present even though the test
    # statistic/hedge ratio differ -- that asymmetry is exactly what the FRD flags.
    assert forward.is_significant_5pct
    assert reverse.is_significant_5pct
