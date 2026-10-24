import numpy as np

from pipeline.signals.zscore import fit_zscore_stats, z_score


def test_fit_zscore_stats_uses_only_the_tail_lookback():
    spread = np.array([100.0, 100.0, 1.0, 2.0, 3.0])  # first two should be ignored with lookback=3
    stats = fit_zscore_stats(spread, lookback_bars=3)
    assert stats.mean == 2.0
    assert abs(stats.std - np.std([1.0, 2.0, 3.0])) < 1e-9


def test_z_score_known_value():
    from pipeline.signals.zscore import ZScoreStats
    stats = ZScoreStats(mean=10.0, std=2.0)
    assert z_score(14.0, stats) == 2.0
    assert z_score(6.0, stats) == -2.0


def test_z_score_none_when_std_is_zero():
    from pipeline.signals.zscore import ZScoreStats
    stats = ZScoreStats(mean=10.0, std=0.0)
    assert z_score(12.0, stats) is None
