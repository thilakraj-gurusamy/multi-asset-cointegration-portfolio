import numpy as np

from pipeline.risk.leverage import leverage_capped_units, worst_case_move


def test_worst_case_move_is_the_largest_single_day_jump_not_the_std():
    # A quiet series with ONE huge jump -- std would understate this, worst_case_move catches it.
    spread = np.array([1.0, 1.01, 1.02, 1.01, 50.0, 1.0])
    worst = worst_case_move(spread)
    assert worst == max(abs(50.0 - 1.01), abs(1.0 - 50.0))


def test_worst_case_move_zero_for_flat_series():
    assert worst_case_move([5.0, 5.0, 5.0]) == 0.0


def test_leverage_capped_units_smaller_than_vol_target_in_a_fat_tailed_series():
    # LTCM point: the typical move (std) understates the tail; the leverage cap must bind
    # tighter than a vol-target computed off std alone would.
    from pipeline.risk.sizing import vol_target_units

    spread = np.array([1.0, 1.01, 1.02, 1.01, 50.0, 1.0])
    std = np.std(np.diff(spread))
    vol_units = vol_target_units(1000.0, std)
    worst = worst_case_move(spread)
    lev_units = leverage_capped_units(max_loss_dollars=1000.0, worst_case_move_value=worst)
    assert lev_units < vol_units


def test_leverage_capped_units_uncapped_when_worst_case_zero():
    assert leverage_capped_units(1000.0, 0.0) == float("inf")
