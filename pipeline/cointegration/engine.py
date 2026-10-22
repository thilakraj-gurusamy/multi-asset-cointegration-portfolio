"""Rolling-window orchestration for the cointegration engine (FRD Section 8.2).

Operates on DAILY bars ("1day") only, read from the Phase 1 store -- see the "cointegration:"
section in config/universe.yaml for why this phase is scoped to daily resolution. All series
within an asset class are aligned to the dates common to every symbol before any window is cut,
since both Engle-Granger and Johansen need synchronized observations across series.

Deliberately produces RAW per-window numbers only (p-values, hedge ratios/cointegrating
vectors, half-lives) -- no health-status classification, no drift-over-time tracking, no
gating. That is Phase 3 (FRD Section 8.5), consuming the rows this module writes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from pipeline.cointegration.adf import check_i1
from pipeline.cointegration.engle_granger import run_engle_granger_both_directions
from pipeline.cointegration.johansen import run_johansen
from pipeline.cointegration.repository import CointegrationRepository
from pipeline.logging_setup import get_logger

logger = get_logger(__name__)

INTERVAL = "1day"


@dataclass
class EngineRunSummary:
    windows_processed: int = 0
    adf_exclusions: int = 0
    engle_granger_pairs_tested: int = 0
    johansen_tests_run: int = 0
    disagreements_found: int = 0


def _load_aligned_series(
    repo: CointegrationRepository, symbols: list[str], asset_class: str, start: datetime, end: datetime
):
    asset_ids: dict[str, int] = {}
    per_symbol_closes: dict[str, dict[datetime, float]] = {}

    for symbol in symbols:
        asset_id = repo.get_asset_id(symbol, asset_class)
        if asset_id is None:
            raise ValueError(f"No asset_id found for {symbol!r} ({asset_class}) -- has Phase 1 ingested it?")
        asset_ids[symbol] = asset_id
        rows = repo.get_closes(asset_id, INTERVAL, start, end)
        per_symbol_closes[symbol] = {t: c for t, c in rows}

    common_dates = set.intersection(*(set(d.keys()) for d in per_symbol_closes.values()))
    return sorted(common_dates), asset_ids, per_symbol_closes


def _window_slices(n_dates: int, window_bars: int, step_bars: int):
    start_idx = 0
    while start_idx + window_bars <= n_dates:
        yield start_idx, start_idx + window_bars
        start_idx += step_bars


def run_rolling_cointegration(
    repo: CointegrationRepository,
    asset_class: str,
    symbols: list[str],
    baskets: list[list[str]],
    window_bars: int,
    step_bars: int,
    start: datetime,
    end: datetime,
) -> EngineRunSummary:
    summary = EngineRunSummary()

    all_symbols = sorted(set(symbols) | {s for basket in baskets for s in basket})
    dates, asset_ids, closes = _load_aligned_series(repo, all_symbols, asset_class, start, end)

    if len(dates) < window_bars:
        logger.warning(
            "Only %s aligned daily bars for %s in [%s, %s]; need at least %s for one window -- nothing to do.",
            len(dates), asset_class, start, end, window_bars,
        )
        return summary

    for w_start_idx, w_end_idx in _window_slices(len(dates), window_bars, step_bars):
        window_dates = dates[w_start_idx:w_end_idx]
        window_start, window_end = window_dates[0], window_dates[-1]
        summary.windows_processed += 1

        passed_symbols = []
        for symbol in symbols:
            series = [closes[symbol][d] for d in window_dates]
            i1_check = check_i1(series)
            repo.insert_adf_result(asset_ids[symbol], INTERVAL, window_start, window_end, i1_check.levels)
            repo.insert_adf_result(asset_ids[symbol], INTERVAL, window_start, window_end, i1_check.first_diff)
            if i1_check.is_i1:
                passed_symbols.append(symbol)
            else:
                summary.adf_exclusions += 1
                logger.info(
                    "ADF pre-test excluded %s from window %s..%s (not confirmed I(1))",
                    symbol, window_start.date(), window_end.date(),
                )

        for i in range(len(passed_symbols)):
            for j in range(i + 1, len(passed_symbols)):
                symbol_a, symbol_b = passed_symbols[i], passed_symbols[j]
                series_a = np.array([closes[symbol_a][d] for d in window_dates])
                series_b = np.array([closes[symbol_b][d] for d in window_dates])

                forward, reverse = run_engle_granger_both_directions(symbol_a, series_a, symbol_b, series_b)
                eg_result_id = repo.insert_engle_granger_result(
                    asset_class, INTERVAL, window_start, window_end,
                    asset_ids[symbol_a], asset_ids[symbol_b], forward,
                )
                repo.insert_engle_granger_result(
                    asset_class, INTERVAL, window_start, window_end,
                    asset_ids[symbol_b], asset_ids[symbol_a], reverse,
                )
                summary.engle_granger_pairs_tested += 1

                pair_data = np.column_stack([series_a, series_b])
                johansen_result = run_johansen([symbol_a, symbol_b], pair_data)
                johansen_result_id = repo.insert_johansen_result(
                    asset_class, INTERVAL, window_start, window_end,
                    [asset_ids[symbol_a], asset_ids[symbol_b]], johansen_result,
                )
                summary.johansen_tests_run += 1

                johansen_rank_ge_1 = johansen_result.cointegration_rank >= 1
                repo.insert_method_disagreement(
                    asset_class, INTERVAL, window_start, window_end,
                    asset_ids[symbol_a], asset_ids[symbol_b],
                    eg_result_id, johansen_result_id,
                    forward.is_significant_5pct, johansen_rank_ge_1,
                )
                if forward.is_significant_5pct != johansen_rank_ge_1:
                    summary.disagreements_found += 1

        for basket in baskets:
            if not all(s in passed_symbols for s in basket):
                logger.info(
                    "Skipping basket %s for window %s..%s -- not all members passed the ADF pre-test.",
                    basket, window_start.date(), window_end.date(),
                )
                continue
            basket_data = np.column_stack([[closes[s][d] for d in window_dates] for s in basket])
            johansen_result = run_johansen(list(basket), basket_data)
            repo.insert_johansen_result(
                asset_class, INTERVAL, window_start, window_end,
                [asset_ids[s] for s in basket], johansen_result,
            )
            summary.johansen_tests_run += 1

    return summary
