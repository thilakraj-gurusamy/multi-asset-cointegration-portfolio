from datetime import datetime, timedelta, timezone

from pipeline.quality.checks import detect_gaps, validate_bar
from pipeline.sources.base import Bar


def _bar(hour: int, o=1.0, h=1.1, l=0.9, c=1.0, v=None) -> Bar:
    return Bar(time=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour), open=o, high=h, low=l, close=c, volume=v)


def test_validate_bar_accepts_well_formed_bar():
    assert validate_bar(_bar(0)) == []


def test_validate_bar_flags_high_below_low():
    bar = _bar(0, o=1.0, h=0.5, l=0.9, c=0.8)
    issues = validate_bar(bar)
    assert any("high" in i and "low" in i for i in issues)


def test_validate_bar_flags_negative_volume():
    bar = _bar(0, v=-100)
    issues = validate_bar(bar)
    assert any("volume" in i for i in issues)


def test_validate_bar_flags_non_positive_price():
    bar = _bar(0, o=0.0)
    issues = validate_bar(bar)
    assert any("open" in i for i in issues)


def test_validate_bar_flags_close_outside_range():
    bar = _bar(0, o=1.0, h=1.1, l=0.9, c=5.0)
    issues = validate_bar(bar)
    assert any("close" in i for i in issues)


def test_detect_gaps_no_gap_within_tolerance():
    bars = [_bar(0), _bar(1), _bar(2)]
    gaps = detect_gaps(bars, expected_interval_minutes=60, gap_tolerance_minutes=90, asset_symbol="EUR/USD", interval="1hour")
    assert gaps == []


def test_detect_gaps_flags_gap_beyond_tolerance():
    bars = [_bar(0), _bar(10)]  # 10-hour jump
    gaps = detect_gaps(bars, expected_interval_minutes=60, gap_tolerance_minutes=90, asset_symbol="EUR/USD", interval="1hour")
    assert len(gaps) == 1
    assert gaps[0].gap_minutes == 600
    assert gaps[0].asset_symbol == "EUR/USD"
