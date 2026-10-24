from pipeline.risk.sizing import vol_target_units


def test_vol_target_units_scales_inversely_with_spread_volatility():
    calm = vol_target_units(1000.0, spread_change_std=0.5)
    choppy = vol_target_units(1000.0, spread_change_std=2.0)
    assert calm > choppy
    assert calm == 2000.0
    assert choppy == 500.0


def test_vol_target_units_zero_when_std_degenerate():
    assert vol_target_units(1000.0, spread_change_std=0.0) == 0.0
    assert vol_target_units(1000.0, spread_change_std=-1.0) == 0.0
