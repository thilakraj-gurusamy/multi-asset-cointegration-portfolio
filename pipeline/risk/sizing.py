"""Vol-targeted position sizing (FRD Section 8.7a): position size is scaled INVERSELY to the
spread's recent volatility, never a fixed notional per trade. A position that trades a
jumpier spread gets fewer units so its P&L volatility contribution stays roughly constant
across relationships -- a calm FX pair and a choppy equity basket should contribute similar
risk, not similar unit counts.

`spread_change_std` is the standard deviation of the IN-SAMPLE spread's day-to-day change
(not its level) -- units of the spread position multiply directly against that to give
dollar P&L volatility, since one day's P&L for `units` of the spread is
units * (spread_t - spread_{t-1}).
"""
from __future__ import annotations


def vol_target_units(target_daily_vol_dollars: float, spread_change_std: float) -> float:
    """Returns 0.0 (not an error) when spread_change_std is zero/degenerate -- a position sized
    against a flat spread isn't meaningfully "targetable", so the safe answer is no position,
    not a divide-by-zero or an infinite size.
    """
    if spread_change_std <= 0:
        return 0.0
    return target_daily_vol_dollars / spread_change_std
