"""Storage interface.

Defined as an ABC so ingest_runner can be unit-tested against an in-memory fake
(tests/fakes.py) without a live PostgreSQL/TimescaleDB instance -- the only concrete
implementation shipped here is PostgresRepository, which backs the real pipeline.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import psycopg2
import psycopg2.extras

from pipeline.sources.base import Bar


class Repository(ABC):
    @abstractmethod
    def upsert_asset(self, symbol: str, asset_class: str, sector: Optional[str], source: str, source_ticker: str) -> int:
        ...

    @abstractmethod
    def get_watermark(self, asset_id: int, interval: str) -> Optional[datetime]:
        ...

    @abstractmethod
    def set_watermark(self, asset_id: int, interval: str, ts: datetime) -> None:
        ...

    @abstractmethod
    def insert_bars(self, asset_id: int, interval: str, bars: list[Bar], source: str) -> int:
        ...

    @abstractmethod
    def get_recent_closes(self, asset_id: int, interval: str, before: datetime, limit: int) -> list[Bar]:
        ...

    @abstractmethod
    def insert_derived_stats(self, asset_id: int, interval: str, rows) -> int:
        ...

    @abstractmethod
    def start_run(self, asset_class: str, interval: str, source: str, run_type: str) -> int:
        ...

    @abstractmethod
    def finish_run(self, run_id: int, status: str, rows_ingested: int, error_message: Optional[str] = None) -> None:
        ...

    @abstractmethod
    def log_quality_event(
        self, run_id: Optional[int], asset_id: Optional[int], event_type: str, severity: str, details: dict
    ) -> None:
        ...


class PostgresRepository(Repository):
    def __init__(self, database_url: str):
        self._conn = psycopg2.connect(database_url)
        self._conn.autocommit = True

    def close(self) -> None:
        self._conn.close()

    def upsert_asset(self, symbol: str, asset_class: str, sector: Optional[str], source: str, source_ticker: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO assets (symbol, asset_class, sector, source, source_ticker)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (symbol, asset_class)
                DO UPDATE SET sector = EXCLUDED.sector, source = EXCLUDED.source, source_ticker = EXCLUDED.source_ticker
                RETURNING asset_id
                """,
                (symbol, asset_class, sector, source, source_ticker),
            )
            return cur.fetchone()[0]

    def get_watermark(self, asset_id: int, interval: str) -> Optional[datetime]:
        with self._conn.cursor() as cur:
            cur.execute(
                'SELECT last_ingested_time FROM ingestion_watermarks WHERE asset_id = %s AND "interval" = %s',
                (asset_id, interval),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def set_watermark(self, asset_id: int, interval: str, ts: datetime) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_watermarks (asset_id, "interval", last_ingested_time)
                VALUES (%s, %s, %s)
                ON CONFLICT (asset_id, "interval")
                DO UPDATE SET last_ingested_time = EXCLUDED.last_ingested_time
                """,
                (asset_id, interval, ts),
            )

    def insert_bars(self, asset_id: int, interval: str, bars: list[Bar], source: str) -> int:
        # NOTE: execute_values pages large inserts (default page_size=100) into multiple INSERT
        # statements; cur.rowcount after that only reflects the LAST page, silently undercounting
        # any batch over 100 rows. RETURNING + fetch=True aggregates the real count across all
        # pages -- this was caught via a live Alpaca backfill reporting 50 inserted when 1,050
        # rows actually landed (10 symbols x 105 rows, each batch split 100+5).
        if not bars:
            return 0
        rows = [(b.time, asset_id, interval, b.open, b.high, b.low, b.close, b.volume, source) for b in bars]
        with self._conn.cursor() as cur:
            inserted = psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO bars ("time", asset_id, "interval", open, high, low, close, volume, source)
                VALUES %s
                ON CONFLICT (asset_id, "interval", "time") DO NOTHING
                RETURNING 1
                """,
                rows,
                fetch=True,
            )
            return len(inserted)

    def get_recent_closes(self, asset_id: int, interval: str, before: datetime, limit: int) -> list[Bar]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT "time", open, high, low, close, volume FROM bars
                WHERE asset_id = %s AND "interval" = %s AND "time" < %s
                ORDER BY "time" DESC
                LIMIT %s
                """,
                (asset_id, interval, before, limit),
            )
            rows = cur.fetchall()
        return [Bar(time=r[0], open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in reversed(rows)]

    def insert_derived_stats(self, asset_id: int, interval: str, rows) -> int:
        records = [
            (r["time"], asset_id, interval, r["log_return"], r["rolling_mean_20"], r["rolling_std_20"])
            for r in rows
        ]
        if not records:
            return 0
        with self._conn.cursor() as cur:
            updated = psycopg2.extras.execute_values(
                cur,
                """
                INSERT INTO derived_bar_stats ("time", asset_id, "interval", log_return, rolling_mean_20, rolling_std_20)
                VALUES %s
                ON CONFLICT (asset_id, "interval", "time")
                DO UPDATE SET log_return = EXCLUDED.log_return,
                              rolling_mean_20 = EXCLUDED.rolling_mean_20,
                              rolling_std_20 = EXCLUDED.rolling_std_20
                RETURNING 1
                """,
                records,
                fetch=True,
            )
            return len(updated)

    def start_run(self, asset_class: str, interval: str, source: str, run_type: str) -> int:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_runs (asset_class, "interval", source, run_type, status)
                VALUES (%s, %s, %s, %s, 'running')
                RETURNING run_id
                """,
                (asset_class, interval, source, run_type),
            )
            return cur.fetchone()[0]

    def finish_run(self, run_id: int, status: str, rows_ingested: int, error_message: Optional[str] = None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingestion_runs
                SET status = %s, rows_ingested = %s, error_message = %s, finished_at = now()
                WHERE run_id = %s
                """,
                (status, rows_ingested, error_message, run_id),
            )

    def log_quality_event(
        self, run_id: Optional[int], asset_id: Optional[int], event_type: str, severity: str, details: dict
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO data_quality_events (run_id, asset_id, event_type, severity, details)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (run_id, asset_id, event_type, severity, json.dumps(details, default=str)),
            )
