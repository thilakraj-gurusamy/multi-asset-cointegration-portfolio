from pipeline.backtest.costs import compute_round_trip_leg_cost


def test_cost_components_computed_separately():
    costs = compute_round_trip_leg_cost(notional=100_000.0, transaction_cost_bps=2.0, slippage_bps=1.0)
    assert abs(costs.transaction_cost - 20.0) < 1e-9
    assert abs(costs.slippage_cost - 10.0) < 1e-9
    assert abs(costs.total - 30.0) < 1e-9


def test_cost_uses_absolute_notional():
    costs = compute_round_trip_leg_cost(notional=-100_000.0, transaction_cost_bps=2.0, slippage_bps=1.0)
    assert costs.total > 0
