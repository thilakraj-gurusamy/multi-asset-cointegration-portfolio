"""Storage for Phase 2 outputs. Deliberately separate from pipeline.repository.Repository
(Phase 1) rather than extending it -- this phase only reads Phase 1's `assets`/`bars` tables
and writes its own new tables (db/schema_phase2.sql); it never needs Phase 1's ingestion-side
methods (watermarks, ingestion_runs, data_quality_events).
"""
from __future__ import annotations

import json
from datetime import datetime

import psycopg2
import psycopg2.extras

from pipeline.cointegration.adf import AdfResult
from pipeline.cointegration.engle_granger import EngleGrangerResult
from pipeline.cointegration.johansen import JohansenResult


class CointegrationRepository:
    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = True

    def close(self) -> None:
        self._conn.close()

    def get_asset_id(self, symbol: str, asset_class: str) -> int | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT asset_id FROM assets WHERE symbol = %s AND asset_class = %s",
                (symbol, asset_class),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def get_closes(self, asset_id: int, interval: str, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT "time", close FROM bars
                WHERE asset_id = %s AND "interval" = %s AND "time" >= %s AND "time" <= %s
                ORDER BY "time" ASC
                """,
                (asset_id, interval, start, end),
            )
            return cur.fetchall()

    def insert_adf_result(
        self, asset_id: int, interval: str, window_start: datetime, window_end: datetime, result: AdfResult
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO adf_results
                    (asset_id, "interval", window_start, window_end, series_type,
                     test_statistic, p_value, n_obs, lags_used, is_stationary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_id, "interval", window_start, window_end, series_type)
                DO UPDATE SET test_statistic = EXCLUDED.test_statistic, p_value = EXCLUDED.p_value,
                              n_obs = EXCLUDED.n_obs, lags_used = EXCLUDED.lags_used,
                              is_stationary = EXCLUDED.is_stationary
                """,
                (
                    asset_id, interval, window_start, window_end, result.series_type,
                    result.test_statistic, result.p_value, result.n_obs, result.lags_used,
                    result.is_stationary,
                ),
            )

    def insert_engle_granger_result(
        self,
        asset_class: str,
        interval: str,
        window_start: datetime,
        window_end: datetime,
        regressand_asset_id: int,
        regressor_asset_id: int,
        result: EngleGrangerResult,
    ) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO engle_granger_results
                    (asset_class, "interval", window_start, window_end,
                     regressand_asset_id, regressor_asset_id,
                     test_statistic, p_value, hedge_ratio, half_life_days, is_significant_5pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, "interval", window_start, window_end, regressand_asset_id, regressor_asset_id)
                DO UPDATE SET test_statistic = EXCLUDED.test_statistic, p_value = EXCLUDED.p_value,
                              hedge_ratio = EXCLUDED.hedge_ratio, half_life_days = EXCLUDED.half_life_days,
                              is_significant_5pct = EXCLUDED.is_significant_5pct
                RETURNING result_id
                """,
                (
                    asset_class, interval, window_start, window_end,
                    regressand_asset_id, regressor_asset_id,
                    result.test_statistic, result.p_value, result.hedge_ratio,
                    result.half_life_days, result.is_significant_5pct,
                ),
            )
            return cur.fetchone()[0]

    def insert_johansen_result(
        self,
        asset_class: str,
        interval: str,
        window_start: datetime,
        window_end: datetime,
        asset_ids: list[int],
        result: JohansenResult,
    ) -> int:
        basket_key = ",".join(sorted(result.symbols))
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO johansen_results
                    (asset_class, "interval", window_start, window_end, basket_key, asset_ids,
                     n_assets, lag_order, deterministic_term, trace_stat_rank0, trace_crit_95_rank0,
                     cointegration_rank, cointegrating_vectors, adjustment_speeds, half_life_days_primary)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, "interval", window_start, window_end, basket_key)
                DO UPDATE SET lag_order = EXCLUDED.lag_order, deterministic_term = EXCLUDED.deterministic_term,
                              trace_stat_rank0 = EXCLUDED.trace_stat_rank0,
                              trace_crit_95_rank0 = EXCLUDED.trace_crit_95_rank0,
                              cointegration_rank = EXCLUDED.cointegration_rank,
                              cointegrating_vectors = EXCLUDED.cointegrating_vectors,
                              adjustment_speeds = EXCLUDED.adjustment_speeds,
                              half_life_days_primary = EXCLUDED.half_life_days_primary
                RETURNING result_id
                """,
                (
                    asset_class, interval, window_start, window_end, basket_key, asset_ids,
                    len(asset_ids), result.lag_order, result.deterministic_term,
                    result.trace_stat_rank0, result.trace_crit_95_rank0, result.cointegration_rank,
                    json.dumps(result.cointegrating_vectors), json.dumps(result.adjustment_speeds),
                    result.half_life_days_primary,
                ),
            )
            return cur.fetchone()[0]

    def insert_method_disagreement(
        self,
        asset_class: str,
        interval: str,
        window_start: datetime,
        window_end: datetime,
        asset_id_a: int,
        asset_id_b: int,
        engle_granger_result_id: int,
        johansen_result_id: int,
        eg_significant_5pct: bool,
        johansen_rank_at_least_1: bool,
    ) -> None:
        disagree = eg_significant_5pct != johansen_rank_at_least_1
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO method_disagreements
                    (asset_class, "interval", window_start, window_end, asset_id_a, asset_id_b,
                     engle_granger_result_id, johansen_result_id,
                     eg_significant_at_5pct, johansen_rank_at_least_1, disagree)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, "interval", window_start, window_end, asset_id_a, asset_id_b)
                DO UPDATE SET engle_granger_result_id = EXCLUDED.engle_granger_result_id,
                              johansen_result_id = EXCLUDED.johansen_result_id,
                              eg_significant_at_5pct = EXCLUDED.eg_significant_at_5pct,
                              johansen_rank_at_least_1 = EXCLUDED.johansen_rank_at_least_1,
                              disagree = EXCLUDED.disagree
                """,
                (
                    asset_class, interval, window_start, window_end, asset_id_a, asset_id_b,
                    engle_granger_result_id, johansen_result_id,
                    eg_significant_5pct, johansen_rank_at_least_1, disagree,
                ),
            )
