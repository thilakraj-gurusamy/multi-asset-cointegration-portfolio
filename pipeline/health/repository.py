"""Storage for Phase 3. Reads Phase 2's engle_granger_results / johansen_results tables
(read-only, through its own connection -- Phase 2's repository is untouched) and writes the
three new Phase 3 tables.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras


class HealthRepository:
    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = True

    def close(self) -> None:
        self._conn.close()

    def get_canonical_pair_windows(
        self, asset_class: str, interval: str, start: datetime, end: datetime
    ) -> list[dict]:
        """One row per window per pair, using the alphabetically-forward EG direction as the
        canonical choice -- deterministic regardless of which direction Phase 2's engine
        happened to compute first (FRD's own regressand-order-sensitivity point, applied here
        just to pick ONE stable direction for monitoring, not to resolve which is "correct").
        """
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT a1.symbol || ',' || a2.symbol AS relationship_key,
                       eg.window_start, eg.window_end, eg.p_value, eg.hedge_ratio, eg.half_life_days
                FROM engle_granger_results eg
                JOIN assets a1 ON a1.asset_id = eg.regressand_asset_id
                JOIN assets a2 ON a2.asset_id = eg.regressor_asset_id
                WHERE eg.asset_class = %s AND eg."interval" = %s
                  AND eg.window_end >= %s AND eg.window_end <= %s
                  AND a1.symbol < a2.symbol
                ORDER BY relationship_key, eg.window_end ASC
                """,
                (asset_class, interval, start, end),
            )
            cols = ["relationship_key", "window_start", "window_end", "p_value", "hedge_ratio", "half_life_days"]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_basket_windows(
        self, asset_class: str, interval: str, start: datetime, end: datetime
    ) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT basket_key, window_start, window_end,
                       trace_stat_rank0, trace_crit_90_rank0, trace_crit_95_rank0, trace_crit_99_rank0,
                       cointegration_rank, cointegrating_vectors, half_life_days_primary
                FROM johansen_results
                WHERE asset_class = %s AND "interval" = %s AND n_assets > 2
                  AND window_end >= %s AND window_end <= %s
                ORDER BY basket_key, window_end ASC
                """,
                (asset_class, interval, start, end),
            )
            cols = [
                "relationship_key", "window_start", "window_end", "trace_stat", "crit_90", "crit_95", "crit_99",
                "cointegration_rank", "cointegrating_vectors", "half_life_days",
            ]
            # psycopg2 deserializes JSONB columns into native Python objects automatically --
            # cointegrating_vectors already arrives as a list, not a JSON string, so there is
            # no json.loads() needed (an earlier version of this tried to, and crashed on real
            # data, which is exactly how this got caught).
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def insert_relationship_health(self, asset_class: str, interval: str, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO relationship_health
                    (asset_class, "interval", relationship_key, relationship_type, source_method,
                     window_start, window_end, p_value, p_value_is_proxy, hedge_ratio_or_vector,
                     hedge_ratio_drift_pct, half_life_days, p_value_status, hedge_ratio_drift_status,
                     half_life_status, overall_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, "interval", relationship_key, window_end)
                DO UPDATE SET p_value = EXCLUDED.p_value, hedge_ratio_drift_pct = EXCLUDED.hedge_ratio_drift_pct,
                              half_life_days = EXCLUDED.half_life_days,
                              p_value_status = EXCLUDED.p_value_status,
                              hedge_ratio_drift_status = EXCLUDED.hedge_ratio_drift_status,
                              half_life_status = EXCLUDED.half_life_status,
                              overall_status = EXCLUDED.overall_status
                """,
                (
                    asset_class, interval, record["relationship_key"], record["relationship_type"],
                    record["source_method"], record["window_start"], record["window_end"],
                    record["p_value"], record["p_value_is_proxy"],
                    json.dumps(record["hedge_ratio_or_vector"]), record["hedge_ratio_drift_pct"],
                    record["half_life_days"], record["p_value_status"], record["hedge_ratio_drift_status"],
                    record["half_life_status"], record["overall_status"],
                ),
            )

    def insert_transition(self, asset_class: str, interval: str, record: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO health_status_transitions
                    (asset_class, "interval", relationship_key, relationship_type, window_end,
                     previous_status, new_status, reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (asset_class, "interval", relationship_key, window_end) DO NOTHING
                """,
                (
                    asset_class, interval, record["relationship_key"], record["relationship_type"],
                    record["window_end"], record["previous_status"], record["new_status"],
                    json.dumps(record["reason"]),
                ),
            )

    def flag_position_for_review(self, asset_class: str, interval: str, relationship_key: str, window_end: datetime, reason: dict) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO position_review_flags (asset_class, "interval", relationship_key, window_end, position_id, reason)
                VALUES (%s, %s, %s, %s, NULL, %s)
                """,
                (asset_class, interval, relationship_key, window_end, json.dumps(reason)),
            )

    def is_suspended(self, asset_class: str, interval: str, relationship_key: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT overall_status FROM relationship_health
                WHERE asset_class = %s AND "interval" = %s AND relationship_key = %s
                ORDER BY window_end DESC LIMIT 1
                """,
                (asset_class, interval, relationship_key),
            )
            row = cur.fetchone()
            return bool(row and row[0] == "halted")
