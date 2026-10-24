from pipeline.risk.drawdown import DrawdownTracker


def test_no_halt_while_within_drawdown_limit():
    tracker = DrawdownTracker(starting_equity=1000.0, max_drawdown_pct=20.0)
    tracker.update(-100.0)  # -10%
    assert not tracker.halted
    assert abs(tracker.current_drawdown_pct - 10.0) < 1e-9


def test_halts_once_drawdown_exceeds_limit():
    tracker = DrawdownTracker(starting_equity=1000.0, max_drawdown_pct=20.0)
    tracker.update(-250.0)  # -25%
    assert tracker.halted


def test_halt_persists_even_after_recovery_without_explicit_reset():
    tracker = DrawdownTracker(starting_equity=1000.0, max_drawdown_pct=20.0)
    tracker.update(-250.0)
    assert tracker.halted
    tracker.update(500.0)  # recovers well past the original peak
    assert tracker.halted  # still halted -- "manual review to resume", not automatic


def test_reset_is_the_only_way_to_unhalt():
    tracker = DrawdownTracker(starting_equity=1000.0, max_drawdown_pct=20.0)
    tracker.update(-250.0)
    tracker.reset()
    assert not tracker.halted


def test_peak_tracks_new_highs():
    tracker = DrawdownTracker(starting_equity=1000.0, max_drawdown_pct=50.0)
    tracker.update(500.0)  # equity now 1500, new peak
    tracker.update(-600.0)  # equity now 900, drawdown from peak 1500 = 40%
    assert abs(tracker.current_drawdown_pct - 40.0) < 1e-9
    assert not tracker.halted
