import pytest

from pipeline.health.thresholds import (
    classify_half_life,
    classify_hedge_ratio_drift,
    classify_p_value,
    overall_status,
)


@pytest.mark.parametrize(
    "p_value,expected",
    [(0.01, "healthy"), (0.0499, "healthy"), (0.05, "warning"), (0.08, "warning"), (0.10, "warning"), (0.11, "halted"), (0.9, "halted")],
)
def test_classify_p_value(p_value, expected):
    assert classify_p_value(p_value) == expected


def test_classify_hedge_ratio_drift_none_when_no_prior_window():
    assert classify_hedge_ratio_drift(None) is None


@pytest.mark.parametrize(
    "drift_pct,expected",
    [(0, "healthy"), (9.9, "healthy"), (10.0, "warning"), (25.0, "warning"), (25.1, "halted"), (-30, "halted")],
)
def test_classify_hedge_ratio_drift(drift_pct, expected):
    assert classify_hedge_ratio_drift(drift_pct) == expected


def test_classify_half_life_none_is_halted():
    assert classify_half_life(None) == "halted"


@pytest.mark.parametrize(
    "half_life,expected",
    [
        (5.0, "healthy"), (60.0, "healthy"), (30, "healthy"),
        (4.9, "warning"), (0.5, "warning"), (61, "warning"), (120, "warning"),
        (120.1, "halted"), (500, "halted"),
    ],
)
def test_classify_half_life(half_life, expected):
    assert classify_half_life(half_life) == expected


def test_overall_status_is_worst_of_present_statuses():
    assert overall_status("healthy", "healthy", "healthy") == "healthy"
    assert overall_status("healthy", "warning", "healthy") == "warning"
    assert overall_status("healthy", "warning", "halted") == "halted"
    assert overall_status("healthy", None, "warning") == "warning"  # None ignored


def test_overall_status_requires_at_least_one_status():
    with pytest.raises(ValueError):
        overall_status(None, None)
