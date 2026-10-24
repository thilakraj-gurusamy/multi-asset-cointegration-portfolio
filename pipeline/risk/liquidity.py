"""Liquidity-aware position sizing (FRD Section 8.7e).

Equities have real volume in the Phase 1 store, so they get a genuine ADV-based cap. FX does
not (documented Phase 1 limitation -- no consolidated FX volume data on the free tier), so a
fixed max-notional-per-position stands in as the liquidity proxy. This is stated plainly, not
presented as equivalent rigor, matching the project's existing substitution-disclosure pattern.
"""
from __future__ import annotations

import numpy as np


def equity_liquidity_capped_units(
    recent_volumes: list[float], recent_prices: list[float], adv_fraction: float, unit_notional_per_share: float = 1.0
) -> float:
    """unit_notional_per_share lets a basket's per-unit dollar exposure for THIS leg be
    accounted for; for a simple single-share-equivalent unit this is just 1 share.
    """
    volumes = np.asarray(recent_volumes, dtype=float)
    prices = np.asarray(recent_prices, dtype=float)
    if volumes.size == 0:
        return float("inf")
    avg_dollar_volume = float(np.mean(volumes * prices))
    if avg_dollar_volume <= 0 or unit_notional_per_share <= 0:
        return float("inf")
    return (adv_fraction * avg_dollar_volume) / unit_notional_per_share


def fx_liquidity_capped_units(max_notional_per_position: float, unit_notional: float) -> float:
    if unit_notional <= 0:
        return float("inf")
    return max_notional_per_position / unit_notional
