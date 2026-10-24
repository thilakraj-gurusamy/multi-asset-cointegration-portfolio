"""Portfolio-level drawdown limit (FRD Section 8.7d): breach halts NEW signal generation
system-wide, not just for the one relationship that caused it. Once halted, this tracker
never un-halts itself -- the FRD specifies "requiring manual review to resume", which has no
meaning inside a single backtest replay, so staying halted for the remainder of that run is
the honest behavior (a live system would need an operator action; `reset()` exists for that
case but the walk-forward backtest never calls it).
"""
from __future__ import annotations


class DrawdownTracker:
    def __init__(self, starting_equity: float, max_drawdown_pct: float):
        self.equity = starting_equity
        self.peak_equity = starting_equity
        self.max_drawdown_pct = max_drawdown_pct
        self.halted = False
        self.current_drawdown_pct = 0.0

    def update(self, daily_pnl: float) -> None:
        self.equity += daily_pnl
        self.peak_equity = max(self.peak_equity, self.equity)
        self.current_drawdown_pct = (
            (self.peak_equity - self.equity) / self.peak_equity * 100.0 if self.peak_equity > 0 else 0.0
        )
        if self.current_drawdown_pct > self.max_drawdown_pct:
            self.halted = True

    def reset(self) -> None:
        """Explicit operator action -- never called automatically."""
        self.halted = False
