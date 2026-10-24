from pipeline.health.pseudo_pvalue import johansen_pseudo_p_value

CRIT_90, CRIT_95, CRIT_99 = 10.0, 15.0, 20.0


def test_pseudo_p_value_at_anchor_points_matches_known_alpha():
    assert abs(johansen_pseudo_p_value(CRIT_90, CRIT_90, CRIT_95, CRIT_99) - 0.10) < 1e-9
    assert abs(johansen_pseudo_p_value(CRIT_95, CRIT_90, CRIT_95, CRIT_99) - 0.05) < 1e-9
    assert abs(johansen_pseudo_p_value(CRIT_99, CRIT_90, CRIT_95, CRIT_99) - 0.01) < 1e-9


def test_pseudo_p_value_is_monotonically_decreasing_in_trace_stat():
    values = [johansen_pseudo_p_value(x, CRIT_90, CRIT_95, CRIT_99) for x in [0, 5, 10, 12, 15, 18, 20, 30, 100]]
    assert all(earlier >= later for earlier, later in zip(values, values[1:]))


def test_pseudo_p_value_clamped_to_bounds():
    assert johansen_pseudo_p_value(-1000, CRIT_90, CRIT_95, CRIT_99) <= 0.999
    assert johansen_pseudo_p_value(1000, CRIT_90, CRIT_95, CRIT_99) >= 0.0001


def test_pseudo_p_value_well_below_90pct_crit_reads_as_not_significant():
    p = johansen_pseudo_p_value(0.0, CRIT_90, CRIT_95, CRIT_99)
    assert p > 0.10
