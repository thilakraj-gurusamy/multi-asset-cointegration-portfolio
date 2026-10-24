"""The two Section 12 benchmarks the walk-forward strategy is judged against:

1. **Buy-and-hold** on the same universe -- an equally-weighted, never-rebalanced basket of
   every symbol in the asset class, held across the same backtest dates.
2. **Naive static Engle-Granger baseline, no health gating** -- fit ONE hedge ratio per pair
   on its earliest available Phase 2 window and trade that SAME fixed fit for the entire
   remaining backtest with health status hardcoded to "healthy" (i.e. the gate is never
   consulted), through the identical position/risk/cost engine as the walk-forward strategy.
   This comparison is the actual evidence the health-monitoring layer adds value (Section 12):
   same sizing, same costs, same entry/exit thresholds -- the only difference is a single
   stale fit with no gating versus a continuously-refit, health-gated one.

Scoped to PAIRS only, not baskets: "Engle-Granger baseline" is pairwise by construction (EG has
no 3+-asset form -- that is what Johansen is for), so there is no naive-EG equivalent for a
basket to build without inventing a different methodology than the one named in the spec.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from pipeline.backtest.engine import BacktestResult, simulate_portfolio
from pipeline.backtest.fitting import DailyFit
from pipeline.backtest.repository import BacktestRepository
from pipeline.config import BacktestConfig
from pipeline.risk.leverage import worst_case_move
from pipeline.signals.spread import compute_spread
from pipeline.signals.zscore import fit_zscore_stats, z_score


def build_naive_static_timeseries(
    first_window: dict, prices_by_symbol: dict[str, dict], z_lookback_bars: int
) -> list[DailyFit]:
    legs, weights = first_window["legs"], first_window["weights"]
    window_start, window_end = first_window["window_start"], first_window["window_end"]
    all_dates = sorted(set.intersection(*(set(prices_by_symbol[s].keys()) for s in legs)))

    in_sample_dates = [d for d in all_dates if window_start <= d <= window_end]
    if len(in_sample_dates) < max(2, z_lookback_bars):
        return []

    in_sample_spread = compute_spread(
        [np.array([prices_by_symbol[s][d] for d in in_sample_dates]) for s in legs], weights
    )
    zscore_stats = fit_zscore_stats(in_sample_spread, z_lookback_bars)
    spread_diffs = np.diff(in_sample_spread)
    spread_change_std = float(np.std(spread_diffs, ddof=0)) if spread_diffs.size else 0.0
    worst_move = worst_case_move(in_sample_spread)

    results = []
    for d in all_dates:
        if d <= window_end:
            continue  # the fitting period itself is never traded -- same convention as walk-forward
        spread_value = float(np.dot([prices_by_symbol[s][d] for s in legs], weights))
        z = z_score(spread_value, zscore_stats)
        results.append(
            DailyFit(
                date=d, spread=spread_value, z=z, health_status="healthy",  # gate forced open -- "no health gating"
                weights=list(weights), legs=list(legs), window_start=window_start, window_end=window_end,
                spread_change_std=spread_change_std, spread_worst_case_move=worst_move,
            )
        )
    return results


def run_naive_static_baseline(
    repo: BacktestRepository, asset_class: str, interval: str, pair_keys: list[str],
    start: datetime, end: datetime, cfg: BacktestConfig,
) -> BacktestResult:
    fits: dict[str, list[DailyFit]] = {}
    prices_cache: dict[str, dict] = {}
    volumes_cache: dict[str, dict] = {}

    for key in pair_keys:
        windows = repo.get_pair_windows(asset_class, interval, key, start, end)
        if not windows:
            continue
        first_window = windows[0]
        legs = first_window["legs"]
        rows_by_symbol = {s: repo.get_price_series(s, asset_class, interval, first_window["window_start"], end) for s in legs}
        prices_by_symbol = {s: {r["time"]: r["close"] for r in rows} for s, rows in rows_by_symbol.items()}
        volumes_by_symbol = {s: {r["time"]: r["volume"] for r in rows} for s, rows in rows_by_symbol.items()}

        series = build_naive_static_timeseries(first_window, prices_by_symbol, cfg.z_lookback_bars)
        if series:
            fits[key] = series
            prices_cache[key] = prices_by_symbol
            volumes_cache[key] = volumes_by_symbol

    return simulate_portfolio(fits, prices_cache, volumes_cache, asset_class, cfg)


def compute_buy_and_hold_returns(
    repo: BacktestRepository, asset_class: str, interval: str, symbols: list[str], start: datetime, end: datetime
) -> list[float]:
    prices = {}
    for s in symbols:
        rows = repo.get_price_series(s, asset_class, interval, start, end)
        prices[s] = {r["time"]: r["close"] for r in rows}

    common_dates = sorted(set.intersection(*(set(p.keys()) for p in prices.values())))
    if len(common_dates) < 2:
        return []

    n = len(symbols)
    initial_prices = {s: prices[s][common_dates[0]] for s in symbols}
    shares = {s: (1.0 / n) / initial_prices[s] for s in symbols}  # $1 notional, 1/n per symbol, never rebalanced

    portfolio_values = np.array([sum(shares[s] * prices[s][d] for s in symbols) for d in common_dates])
    return list(np.diff(portfolio_values) / portfolio_values[:-1])
