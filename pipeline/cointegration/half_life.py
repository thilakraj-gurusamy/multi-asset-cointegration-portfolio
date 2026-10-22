"""AR(1)-based half-life of mean reversion for a spread series (FRD Section 8.2 / 8.5
wording): half-life = -ln(2)/ln(lambda), where lambda is the AR(1) coefficient fit to
spread_t = c + lambda * spread_{t-1} + e_t.
"""
from __future__ import annotations

import numpy as np


def estimate_half_life(spread) -> float | None:
    """Returns None when the fitted AR(1) coefficient is outside (0, 1) -- i.e. the spread is
    not mean-reverting (explosive, unit-root, or oscillating), so no finite half-life exists.
    """
    spread = np.asarray(spread, dtype=float)
    if len(spread) < 3:
        return None

    y = spread[1:]
    x = spread[:-1]
    design = np.column_stack([np.ones_like(x), x])
    coeffs, *_ = np.linalg.lstsq(design, y, rcond=None)
    lam = coeffs[1]

    if not np.isfinite(lam) or lam <= 0 or lam >= 1:
        return None

    return float(-np.log(2) / np.log(lam))
