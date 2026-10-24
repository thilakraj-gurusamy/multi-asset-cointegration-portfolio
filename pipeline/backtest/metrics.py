"""Performance metrics (FRD Section 12): Sharpe ratio computed the same way for the
walk-forward strategy, the naive static baseline, and buy-and-hold, so the comparison is
apples-to-apples.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS_PER_YEAR = 252
_MIN_STD_FOR_SHARPE = 1e-9  # guards against float noise on a near-constant series producing
                             # a near-zero-but-nonzero std, which would otherwise blow Sharpe
                             # up to an absurd magnitude instead of reading as "no volatility"


@dataclass(frozen=True)
class PerformanceMetrics:
    total_return_pct: float
    annualized_sharpe: float
    max_drawdown_pct: float
    num_observations: int


def compute_metrics(daily_returns) -> PerformanceMetrics:
    returns = np.asarray(daily_returns, dtype=float)
    if returns.size == 0:
        return PerformanceMetrics(0.0, 0.0, 0.0, 0)

    total_return_pct = float((np.prod(1 + returns) - 1) * 100.0)

    std = np.std(returns, ddof=0)
    sharpe = float(np.mean(returns) / std * np.sqrt(TRADING_DAYS_PER_YEAR)) if std > _MIN_STD_FOR_SHARPE else 0.0

    equity_curve = np.cumprod(1 + returns)
    running_peak = np.maximum.accumulate(equity_curve)
    drawdowns = (running_peak - equity_curve) / running_peak
    max_drawdown_pct = float(np.max(drawdowns) * 100.0) if drawdowns.size else 0.0

    return PerformanceMetrics(
        total_return_pct=total_return_pct,
        annualized_sharpe=sharpe,
        max_drawdown_pct=max_drawdown_pct,
        num_observations=int(returns.size),
    )
