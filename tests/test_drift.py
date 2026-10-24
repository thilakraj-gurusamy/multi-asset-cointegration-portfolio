from pipeline.health.drift import compute_drift_pct


def test_scalar_drift_percentage():
    assert abs(compute_drift_pct(0.5, 0.55) - 10.0) < 1e-9
    assert abs(compute_drift_pct(0.5, 0.45) - 10.0) < 1e-9
    assert compute_drift_pct(0.5, 0.5) == 0.0


def test_vector_drift_percentage():
    # previous=[1,0], current=[1, 0.1] -> ||diff||=0.1, ||prev||=1 -> 10%
    drift = compute_drift_pct([1.0, 0.0], [1.0, 0.1])
    assert abs(drift - 10.0) < 1e-9


def test_zero_baseline_returns_none():
    assert compute_drift_pct(0.0, 5.0) is None
    assert compute_drift_pct([0.0, 0.0], [1.0, 1.0]) is None
