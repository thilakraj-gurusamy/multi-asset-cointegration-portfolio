"""Resolves Phase 2's walk-forward windows + Phase 3's health status into a per-date time
series of (spread, z-score, health status, weights, in-sample risk stats) for ONE
relationship. The walk-forward discipline -- fit on in-sample data, apply the FIXED fit to
out-of-sample bars until the next refit, never peek ahead -- lives entirely here, separated
from the portfolio-level position/P&L simulation (engine.py) so each is testable in isolation.

A window with no usable fit (e.g. a basket window where Johansen's rank came back 0 -- see
pipeline/cointegration/johansen.py's documented full-rank/no-rank edge cases) produces a
genuine GAP: no DailyFit rows for that segment, not a carry-forward of the previous window's
stale fit. The next segment always starts at the NEXT window in the original sequence,
regardless of whether the current one was usable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from pipeline.risk.leverage import worst_case_move
from pipeline.signals.spread import compute_spread
from pipeline.signals.zscore import fit_zscore_stats, z_score


@dataclass(frozen=True)
class DailyFit:
    date: datetime
    spread: float
    z: float | None
    health_status: str | None
    weights: list[float]
    legs: list[str]
    window_start: datetime
    window_end: datetime
    spread_change_std: float   # in-sample day-to-day std -- feeds vol-targeting
    spread_worst_case_move: float  # in-sample worst single-day move -- feeds the leverage cap


def build_relationship_timeseries(
    windows: list[dict],
    health_by_window_end: dict,
    prices_by_symbol: dict[str, dict],
    z_lookback_bars: int,
    backtest_end: datetime,
) -> list[DailyFit]:
    if not windows:
        return []

    legs = windows[0]["legs"]
    all_dates = sorted(set.intersection(*(set(prices_by_symbol[s].keys()) for s in legs)))

    results: list[DailyFit] = []

    for i, window in enumerate(windows):
        weights = window.get("weights")
        if not weights:
            continue  # no usable fit this window -- a real gap, never carried forward

        window_start, window_end = window["window_start"], window["window_end"]
        segment_end = windows[i + 1]["window_end"] if i + 1 < len(windows) else backtest_end
        health_status = health_by_window_end.get(window_end)

        in_sample_dates = [d for d in all_dates if window_start <= d <= window_end]
        if len(in_sample_dates) < max(2, z_lookback_bars):
            continue

        in_sample_spread = compute_spread(
            [np.array([prices_by_symbol[s][d] for d in in_sample_dates]) for s in legs], weights
        )
        zscore_stats = fit_zscore_stats(in_sample_spread, z_lookback_bars)
        spread_diffs = np.diff(in_sample_spread)
        spread_change_std = float(np.std(spread_diffs, ddof=0)) if spread_diffs.size else 0.0
        worst_move = worst_case_move(in_sample_spread)

        out_of_sample_dates = [d for d in all_dates if window_end < d <= segment_end]
        for d in out_of_sample_dates:
            spread_value = float(np.dot([prices_by_symbol[s][d] for s in legs], weights))
            z = z_score(spread_value, zscore_stats)
            results.append(
                DailyFit(
                    date=d, spread=spread_value, z=z, health_status=health_status,
                    weights=list(weights), legs=list(legs), window_start=window_start, window_end=window_end,
                    spread_change_std=spread_change_std, spread_worst_case_move=worst_move,
                )
            )

    return results
