"""In-memory Repository + DataSource fakes so ingest_runner can be unit-tested without a
live PostgreSQL/TimescaleDB instance.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pipeline.repository import Repository
from pipeline.sources.base import Bar, DataSource


class InMemoryRepository(Repository):
    def __init__(self):
        self.assets: dict[tuple[str, str], int] = {}
        self._next_asset_id = 1
        self.bars: dict[tuple[int, str], list[Bar]] = {}
        self.watermarks: dict[tuple[int, str], datetime] = {}
        self.derived_rows: dict[tuple[int, str], list[dict]] = {}
        self.runs: dict[int, dict] = {}
        self._next_run_id = 1
        self.quality_events: list[dict] = []

    def upsert_asset(self, symbol, asset_class, sector, source, source_ticker) -> int:
        key = (symbol, asset_class)
        if key not in self.assets:
            self.assets[key] = self._next_asset_id
            self._next_asset_id += 1
        return self.assets[key]

    def get_watermark(self, asset_id, interval) -> Optional[datetime]:
        return self.watermarks.get((asset_id, interval))

    def set_watermark(self, asset_id, interval, ts) -> None:
        self.watermarks[(asset_id, interval)] = ts

    def insert_bars(self, asset_id, interval, bars, source) -> int:
        key = (asset_id, interval)
        existing = self.bars.setdefault(key, [])
        existing_times = {b.time for b in existing}
        inserted = 0
        for bar in bars:
            if bar.time not in existing_times:
                existing.append(bar)
                existing_times.add(bar.time)
                inserted += 1
        existing.sort(key=lambda b: b.time)
        return inserted

    def get_recent_closes(self, asset_id, interval, before, limit) -> list[Bar]:
        key = (asset_id, interval)
        existing = [b for b in self.bars.get(key, []) if b.time < before]
        existing.sort(key=lambda b: b.time)
        return existing[-limit:]

    def insert_derived_stats(self, asset_id, interval, rows) -> int:
        key = (asset_id, interval)
        self.derived_rows.setdefault(key, []).extend(rows)
        return len(rows)

    def start_run(self, asset_class, interval, source, run_type) -> int:
        run_id = self._next_run_id
        self._next_run_id += 1
        self.runs[run_id] = {
            "asset_class": asset_class,
            "interval": interval,
            "source": source,
            "run_type": run_type,
            "status": "running",
            "rows_ingested": 0,
            "error_message": None,
        }
        return run_id

    def finish_run(self, run_id, status, rows_ingested, error_message=None) -> None:
        self.runs[run_id].update(status=status, rows_ingested=rows_ingested, error_message=error_message)

    def log_quality_event(self, run_id, asset_id, event_type, severity, details) -> None:
        self.quality_events.append(
            {"run_id": run_id, "asset_id": asset_id, "event_type": event_type, "severity": severity, "details": details}
        )


class FakeDataSource(DataSource):
    """Returns pre-programmed bars/exceptions per symbol, in call order."""

    name = "fake"

    def __init__(self, historical: dict[str, list[Bar]] | None = None, incremental: dict[str, list] | None = None):
        self._historical = historical or {}
        self._incremental = incremental or {}

    def fetch_historical(self, ticker, interval, start, end) -> list[Bar]:
        result = self._historical.get(ticker, [])
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_incremental(self, ticker, interval, since) -> list[Bar]:
        result = self._incremental.get(ticker, [])
        if isinstance(result, Exception):
            raise result
        return result
