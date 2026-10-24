from datetime import datetime, timedelta, timezone

import numpy as np

from pipeline.backtest.fitting import build_relationship_timeseries

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _d(i):
    return BASE + timedelta(days=i)


def _prices():
    # A simple, deterministic series so the fitted mean/std and out-of-sample z can be
    # hand-checked exactly.
    days = range(0, 20)
    a = {_d(i): 10.0 + i * 0.1 for i in days}
    b = {_d(i): 5.0 for i in days}  # flat -- keeps the spread arithmetic simple
    return {"A": a, "B": b}


def test_fixed_fit_applied_across_the_whole_out_of_sample_segment():
    prices = _prices()
    windows = [
        {"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]},
        {"window_start": _d(5), "window_end": _d(14), "legs": ["A", "B"], "weights": [1.0, 0.0]},
    ]
    health = {_d(9): "healthy", _d(14): "warning"}

    fits = build_relationship_timeseries(windows, health, prices, z_lookback_bars=3, backtest_end=_d(19))

    # Segment 1 = days 10..14 (window1's out-of-sample, up to window2's window_end).
    seg1 = [f for f in fits if _d(10) <= f.date <= _d(14)]
    assert len(seg1) == 5
    assert all(f.health_status == "healthy" for f in seg1)  # window1's health, not window2's
    # weights=[1,0] -> spread == price of A directly; lookback=3 over in-sample days 7,8,9
    expected_mean = np.mean([10.0 + i * 0.1 for i in (7, 8, 9)])
    assert abs(seg1[0].z - (10.0 + 10 * 0.1 - expected_mean) / np.std([10.0 + i * 0.1 for i in (7, 8, 9)])) < 1e-9

    # Segment 2 = days 15..19 (window2's out-of-sample, up to backtest_end).
    seg2 = [f for f in fits if _d(15) <= f.date <= _d(19)]
    assert len(seg2) == 5
    assert all(f.health_status == "warning" for f in seg2)


def test_window_with_no_usable_weights_produces_a_gap_not_a_carry_forward():
    prices = _prices()
    windows = [
        {"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]},
        {"window_start": _d(5), "window_end": _d(14), "legs": ["A", "B"], "weights": None},  # e.g. Johansen rank 0
        {"window_start": _d(10), "window_end": _d(19), "legs": ["A", "B"], "weights": [1.0, -1.0]},
    ]
    health = {_d(9): "healthy", _d(19): "healthy"}

    fits = build_relationship_timeseries(windows, health, prices, z_lookback_bars=3, backtest_end=_d(19))

    dates_covered = {f.date for f in fits}
    gap_dates = {_d(i) for i in range(15, 20)}  # window2's would-be segment, had it been usable
    assert gap_dates.isdisjoint(dates_covered)
    # window1 still contributes its own segment (days 10-14, bounded by window2's window_end)
    assert all(_d(i) in dates_covered for i in range(10, 15))


def test_in_sample_stats_never_see_out_of_sample_prices():
    # Construct prices where the in-sample window is flat (std=0) but a later out-of-sample
    # value is wildly different -- if the fit leaked out-of-sample data, std would not be 0.
    days = range(0, 15)
    a = {_d(i): 100.0 for i in days}
    a[_d(12)] = 9999.0  # out-of-sample outlier
    b = {_d(i): 0.0 for i in days}
    prices = {"A": a, "B": b}

    windows = [{"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]}]
    fits = build_relationship_timeseries(windows, {}, prices, z_lookback_bars=3, backtest_end=_d(14))

    assert fits  # should have produced the out-of-sample segment
    assert fits[0].spread_change_std == 0.0  # in-sample was flat; the outlier must not have leaked in
