"""Entry/exit decision rules (FRD Section 8.6): a pure function of (current position state,
z-score, health status) -> an action. No I/O, no state -- easy to exhaustively unit test, and
the walk-forward engine is just this function called once per relationship per day.

Gating rule (explicit from the Phase 4 spec): a NEW entry is allowed ONLY when health status is
'healthy'. 'warning' and 'halted' both block new entries -- they are distinguished in the
returned action only so the audit log can tell "a z-score entry signal fired but was suppressed
by warning" apart from "...by halted", not because warning gets any special treatment.

An open position's health-breakdown stop takes priority over an ordinary z-score exit: a
relationship going 'halted' must close the position regardless of where z currently sits.
"""
from __future__ import annotations

ENTER_LONG = "enter_long"           # spread unusually low -> bet it reverts up
ENTER_SHORT = "enter_short"          # spread unusually high -> bet it reverts down
EXIT_Z = "exit_z"
EXIT_HEALTH_HALTED = "exit_health_halted"
HOLD = "hold"
NO_ACTION = "no_action"
SUPPRESSED_WARNING = "suppressed_warning"
SUPPRESSED_HALTED = "suppressed_halted"


def decide_action(
    position_direction: str | None,  # None | "long" | "short"
    z: float | None,
    health_status: str,
    z_entry: float,
    z_exit: float,
    portfolio_halted: bool = False,
) -> str:
    if position_direction is not None:
        if health_status == "halted":
            return EXIT_HEALTH_HALTED
        if z is not None and abs(z) < z_exit:
            return EXIT_Z
        return HOLD

    if z is None:
        return NO_ACTION

    would_enter = z > z_entry or z < -z_entry
    if not would_enter:
        return NO_ACTION

    if health_status != "healthy":
        return SUPPRESSED_WARNING if health_status == "warning" else SUPPRESSED_HALTED

    if portfolio_halted:
        return NO_ACTION  # portfolio-level drawdown breach -- new entries blocked system-wide

    return ENTER_SHORT if z > z_entry else ENTER_LONG
