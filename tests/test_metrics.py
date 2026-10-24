import numpy as np

from pipeline.backtest.metrics import compute_metrics


def test_empty_returns_zeroed_metrics():
    m = compute_metrics([])
    assert m.total_return_pct == 0.0
    assert m.annualized_sharpe == 0.0
    assert m.num_observations == 0


def test_constant_positive_return_has_zero_sharpe_not_undefined():
    # zero volatility -> Sharpe would divide by zero; must come back as 0.0, not NaN/inf.
    m = compute_metrics([0.001] * 100)
    assert m.annualized_sharpe == 0.0
    assert m.total_return_pct > 0


def test_total_return_matches_manual_compounding():
    returns = [0.01, -0.02, 0.03]
    m = compute_metrics(returns)
    expected = (np.prod([1.01, 0.98, 1.03]) - 1) * 100
    assert abs(m.total_return_pct - expected) < 1e-9


def test_max_drawdown_detects_a_known_dip():
    # equity path: 1 -> 1.10 -> 0.88 (a 20% drawdown from the 1.10 peak) -> 0.95
    returns = [0.10, -0.20, (0.95 / 0.88) - 1]
    m = compute_metrics(returns)
    assert abs(m.max_drawdown_pct - 20.0) < 1e-6
