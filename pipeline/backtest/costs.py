"""Transaction costs and slippage (FRD Section 8.8): deducted directly from backtest P&L at
every entry and every exit, not mentioned as an assumption and left out of the arithmetic.

Kept as two separate bps figures rather than one combined fee -- Section 9's cost-transparency
principle extends to the backtest itself: a reviewer should be able to see how much of the
P&L drag came from modeled transaction cost versus modeled slippage, not just a blended number.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostBreakdown:
    transaction_cost: float
    slippage_cost: float

    @property
    def total(self) -> float:
        return self.transaction_cost + self.slippage_cost


def compute_round_trip_leg_cost(notional: float, transaction_cost_bps: float, slippage_bps: float) -> CostBreakdown:
    """notional: dollar value of ONE leg of ONE side (entry or exit) of the trade -- call this
    once for entry and once for exit; the walk-forward engine sums both calls per trade.
    """
    notional = abs(notional)
    return CostBreakdown(
        transaction_cost=notional * transaction_cost_bps / 10_000.0,
        slippage_cost=notional * slippage_bps / 10_000.0,
    )
