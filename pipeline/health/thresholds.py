"""Health-status classification thresholds (FRD Section 8.5).

These are the FRD's own stated INITIAL DEFAULTS, explicitly "to be calibrated during
backtesting, not treated as fixed truths" -- nothing here should be read as a validated,
final parameter. They are kept in one place specifically so recalibration later is a one-file
change, not a hunt through the codebase.
"""
from __future__ import annotations

HealthStatus = str  # "healthy" | "warning" | "halted"

_SEVERITY = {"healthy": 0, "warning": 1, "halted": 2}

# p-value (real, from Engle-Granger; or a documented proxy for Johansen baskets -- see
# pipeline/health/pseudo_pvalue.py)
P_VALUE_HEALTHY_MAX = 0.05
P_VALUE_WARNING_MAX = 0.10

# hedge-ratio / cointegrating-vector drift between successive rolling windows, as a percentage
HEDGE_RATIO_DRIFT_HEALTHY_MAX_PCT = 10.0
HEDGE_RATIO_DRIFT_WARNING_MAX_PCT = 25.0

# half-life, in days (AR(1)-based: half_life = -ln(2)/ln(lambda))
HALF_LIFE_HEALTHY_MIN_DAYS = 5.0
HALF_LIFE_HEALTHY_MAX_DAYS = 60.0
HALF_LIFE_WARNING_MAX_DAYS = 120.0


def classify_p_value(p_value: float) -> HealthStatus:
    if p_value < P_VALUE_HEALTHY_MAX:
        return "healthy"
    if p_value <= P_VALUE_WARNING_MAX:
        return "warning"
    return "halted"


def classify_hedge_ratio_drift(drift_pct: float | None) -> HealthStatus | None:
    """None when there is no previous window to diff against (the relationship's first
    observed window) -- there is nothing to classify yet, not a failure.
    """
    if drift_pct is None:
        return None
    abs_drift = abs(drift_pct)
    if abs_drift < HEDGE_RATIO_DRIFT_HEALTHY_MAX_PCT:
        return "healthy"
    if abs_drift <= HEDGE_RATIO_DRIFT_WARNING_MAX_PCT:
        return "warning"
    return "halted"


def classify_half_life(half_life_days: float | None) -> HealthStatus:
    """None (not mean-reverting at all -- the AR(1) coefficient was outside (0,1), see
    pipeline/cointegration/half_life.py) is classified 'halted': it is not covered by any of
    the FRD's numeric bands and is plainly the most severe case, not an unclassifiable one.

    The FRD's own band wording is read literally here: "healthy 5-60 days, warning 60-120 days
    (or < 5 days), halted outside that range" -- i.e. anything below 5 days falls under the
    warning band (as explicitly stated by the parenthetical), and halted is reserved for
    exceeding the combined healthy+warning envelope (> 120 days) or being undefined.
    """
    if half_life_days is None:
        return "halted"
    if HALF_LIFE_HEALTHY_MIN_DAYS <= half_life_days <= HALF_LIFE_HEALTHY_MAX_DAYS:
        return "healthy"
    if half_life_days > HALF_LIFE_HEALTHY_MAX_DAYS and half_life_days <= HALF_LIFE_WARNING_MAX_DAYS:
        return "warning"
    if half_life_days < HALF_LIFE_HEALTHY_MIN_DAYS:
        return "warning"
    return "halted"


def overall_status(*statuses: HealthStatus | None) -> HealthStatus:
    """Worst-of-the-available-statuses. A None entry (e.g. no drift yet on a relationship's
    first window) is simply excluded, not treated as a failure.
    """
    present = [s for s in statuses if s is not None]
    if not present:
        raise ValueError("overall_status() requires at least one non-None status")
    return max(present, key=lambda s: _SEVERITY[s])
