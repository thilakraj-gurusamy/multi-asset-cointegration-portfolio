from pipeline.risk.liquidity import equity_liquidity_capped_units, fx_liquidity_capped_units


def test_equity_liquidity_cap_scales_with_adv():
    # avg dollar volume = 100 shares * $10 = $1000/day; 1% ADV fraction = $10 allowed/day;
    # unit_notional_per_share = $2 per unit -> cap = 10/2 = 5 units.
    cap = equity_liquidity_capped_units([100.0] * 5, [10.0] * 5, adv_fraction=0.01, unit_notional_per_share=2.0)
    assert abs(cap - 5.0) < 1e-9


def test_equity_liquidity_cap_uncapped_when_no_volume_data():
    assert equity_liquidity_capped_units([], [], adv_fraction=0.01, unit_notional_per_share=2.0) == float("inf")


def test_fx_liquidity_cap_is_fixed_notional_divided_by_unit_exposure():
    cap = fx_liquidity_capped_units(max_notional_per_position=2_000_000.0, unit_notional=1.1)
    assert abs(cap - (2_000_000.0 / 1.1)) < 1e-6


def test_fx_liquidity_cap_uncapped_when_unit_notional_zero():
    assert fx_liquidity_capped_units(2_000_000.0, 0.0) == float("inf")
