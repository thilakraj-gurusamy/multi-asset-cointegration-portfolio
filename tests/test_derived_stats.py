import math
from datetime import datetime, timedelta, timezone

from pipeline.derived.stats import WINDOW, compute_derived_stats
from pipeline.sources.base import Bar


def _series(n: int, start_close: float = 100.0, step: float = 1.0) -> list[Bar]:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(time=base + timedelta(hours=i), open=start_close + i * step, high=start_close + i * step + 0.5,
            low=start_close + i * step - 0.5, close=start_close + i * step, volume=1000.0)
        for i in range(n)
    ]


def test_empty_input_returns_empty_frame():
    df = compute_derived_stats([])
    assert df.empty


def test_log_return_matches_manual_calc():
    bars = _series(3, start_close=100.0, step=10.0)  # closes: 100, 110, 120
    df = compute_derived_stats(bars)
    assert math.isnan(df.iloc[0]["log_return"]) or df.iloc[0]["log_return"] is None
    assert df.iloc[1]["log_return"] == math.log(110 / 100)
    assert df.iloc[2]["log_return"] == math.log(120 / 110)


def test_rolling_mean_and_std_require_full_window():
    bars = _series(WINDOW - 1)
    df = compute_derived_stats(bars)
    assert df["rolling_mean_20"].isna().all()


def test_rolling_mean_populated_once_window_is_full():
    bars = _series(WINDOW + 5, start_close=100.0, step=1.0)
    df = compute_derived_stats(bars)
    last_row = df.iloc[-1]
    expected_mean = sum(b.close for b in bars[-WINDOW:]) / WINDOW
    assert last_row["rolling_mean_20"] == expected_mean
