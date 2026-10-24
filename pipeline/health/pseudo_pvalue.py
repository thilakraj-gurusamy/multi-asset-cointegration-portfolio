"""Johansen's trace test has no native continuous p-value the way Engle-Granger does --
statsmodels' coint_johansen only gives critical values at three fixed significance levels
(90%/95%/99%). To apply the SAME continuous p-value health thresholds (FRD Section 8.5) to
basket relationships as to pairs, this interpolates/extrapolates a p-value PROXY from the
trace statistic against those three (critical_value, alpha) anchor points.

This is explicitly an approximation, not a real p-value -- every caller must carry the
`p_value_is_proxy=True` flag alongside it (see pipeline/health/monitor.py) so nothing downstream
mistakes it for a genuine distributional p-value.
"""
from __future__ import annotations

_MIN_P = 0.0001
_MAX_P = 0.999


def johansen_pseudo_p_value(trace_stat: float, crit_90: float, crit_95: float, crit_99: float) -> float:
    anchors = sorted([(crit_90, 0.10), (crit_95, 0.05), (crit_99, 0.01)], key=lambda pair: pair[0])
    (x0, y0), (x1, y1), (x2, y2) = anchors

    if trace_stat <= x1:
        slope = (y1 - y0) / (x1 - x0)
        p = y0 + slope * (trace_stat - x0)
    else:
        slope = (y2 - y1) / (x2 - x1)
        p = y1 + slope * (trace_stat - x1)

    return min(max(p, _MIN_P), _MAX_P)
