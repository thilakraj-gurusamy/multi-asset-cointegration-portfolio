import pytest

from pipeline.signals.rules import (
    ENTER_LONG,
    ENTER_SHORT,
    EXIT_HEALTH_HALTED,
    EXIT_Z,
    HOLD,
    NO_ACTION,
    SUPPRESSED_HALTED,
    SUPPRESSED_WARNING,
    decide_action,
)

Z_ENTRY, Z_EXIT = 2.0, 0.5


def test_enters_long_when_z_very_negative_and_healthy():
    assert decide_action(None, -2.5, "healthy", Z_ENTRY, Z_EXIT) == ENTER_LONG


def test_enters_short_when_z_very_positive_and_healthy():
    assert decide_action(None, 2.5, "healthy", Z_ENTRY, Z_EXIT) == ENTER_SHORT


def test_no_entry_when_z_inside_entry_band_even_if_healthy():
    assert decide_action(None, 1.0, "healthy", Z_ENTRY, Z_EXIT) == NO_ACTION


@pytest.mark.parametrize("status,expected", [("warning", SUPPRESSED_WARNING), ("halted", SUPPRESSED_HALTED)])
def test_entry_signal_suppressed_when_not_healthy(status, expected):
    assert decide_action(None, 2.5, status, Z_ENTRY, Z_EXIT) == expected
    assert decide_action(None, -2.5, status, Z_ENTRY, Z_EXIT) == expected


def test_no_action_when_z_is_none_and_flat():
    assert decide_action(None, None, "healthy", Z_ENTRY, Z_EXIT) == NO_ACTION


def test_portfolio_halted_blocks_new_entry_even_when_healthy():
    assert decide_action(None, 2.5, "healthy", Z_ENTRY, Z_EXIT, portfolio_halted=True) == NO_ACTION


def test_open_position_holds_while_z_outside_exit_band_and_healthy():
    assert decide_action("long", 1.5, "healthy", Z_ENTRY, Z_EXIT) == HOLD


def test_open_position_exits_on_z_reverting_to_mean():
    assert decide_action("long", 0.3, "healthy", Z_ENTRY, Z_EXIT) == EXIT_Z
    assert decide_action("short", -0.3, "warning", Z_ENTRY, Z_EXIT) == EXIT_Z  # z-exit still applies even if warning


def test_open_position_exits_on_health_halted_regardless_of_z():
    # Even deep in profit (z far from exit band), a halted relationship must close.
    assert decide_action("long", 3.0, "halted", Z_ENTRY, Z_EXIT) == EXIT_HEALTH_HALTED


def test_open_position_with_none_z_still_holds_unless_halted():
    assert decide_action("short", None, "warning", Z_ENTRY, Z_EXIT) == HOLD
    assert decide_action("short", None, "halted", Z_ENTRY, Z_EXIT) == EXIT_HEALTH_HALTED
