"""LTCM-derived leverage cap (FRD Section 8.7c): "leverage caps set with reference to the
worst plausible historical divergence of the spread... not just historical volatility."

This is the direct code expression of the LTCM lesson (FRD Section 7): LTCM sized its
convergence trades off typical historical volatility and was wiped out when the 1998 Russia
default produced a divergence far outside that typical range. Vol-targeting (sizing.py) uses
the spread's STD (the typical case); this uses its single WORST observed day-to-day move in
the in-sample window (the tail case) and caps position size so even that worst case, repeated,
cannot lose more than `max_loss_dollars`. The final position size is the MIN of the two caps,
never just the vol-targeted one.
"""
from __future__ import annotations

import numpy as np


def worst_case_move(in_sample_spread) -> float:
    """Largest single-period absolute change observed in the in-sample spread -- the
    worst plausible divergence actually seen, not a theoretical bound.
    """
    diffs = np.diff(np.asarray(in_sample_spread, dtype=float))
    if diffs.size == 0:
        return 0.0
    return float(np.max(np.abs(diffs)))


def leverage_capped_units(max_loss_dollars: float, worst_case_move_value: float) -> float:
    """Returns infinity (no cap) when the worst-case move is zero/degenerate -- there is
    nothing to size against; the vol-target and liquidity caps still apply elsewhere.
    """
    if worst_case_move_value <= 0:
        return float("inf")
    return max_loss_dollars / worst_case_move_value
