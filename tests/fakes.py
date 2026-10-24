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


class FakeCointegrationRepository:
    """In-memory stand-in for pipeline.cointegration.repository.CointegrationRepository --
    lets engine orchestration (ADF exclusion, basket skipping, disagreement flagging, window
    counting) be unit-tested without a live Postgres instance.
    """

    def __init__(self, asset_ids: dict[tuple[str, str], int], closes: dict[str, dict]):
        self._asset_ids = asset_ids
        self._closes = closes  # {symbol: {datetime: float}}
        self.adf_results = []
        self.engle_granger_results = []
        self.johansen_results = []
        self.method_disagreements = []
        self._next_result_id = 1

    def get_asset_id(self, symbol, asset_class):
        return self._asset_ids.get((symbol, asset_class))

    def get_closes(self, asset_id, interval, start, end):
        for symbol, sym_asset_id in [(s, a) for (s, _), a in self._asset_ids.items()]:
            if sym_asset_id == asset_id:
                rows = [(t, c) for t, c in self._closes[symbol].items() if start <= t <= end]
                return sorted(rows)
        return []

    def insert_adf_result(self, asset_id, interval, window_start, window_end, result):
        self.adf_results.append(
            {"asset_id": asset_id, "window_start": window_start, "window_end": window_end, "result": result}
        )

    def insert_engle_granger_result(self, asset_class, interval, window_start, window_end, regressand_asset_id, regressor_asset_id, result):
        result_id = self._next_result_id
        self._next_result_id += 1
        self.engle_granger_results.append(
            {
                "result_id": result_id, "window_start": window_start, "window_end": window_end,
                "regressand_asset_id": regressand_asset_id, "regressor_asset_id": regressor_asset_id,
                "result": result,
            }
        )
        return result_id

    def insert_johansen_result(self, asset_class, interval, window_start, window_end, asset_ids, result):
        result_id = self._next_result_id
        self._next_result_id += 1
        self.johansen_results.append(
            {
                "result_id": result_id, "window_start": window_start, "window_end": window_end,
                "asset_ids": asset_ids, "result": result,
            }
        )
        return result_id

    def insert_method_disagreement(
        self, asset_class, interval, window_start, window_end, asset_id_a, asset_id_b,
        engle_granger_result_id, johansen_result_id, eg_significant_5pct, johansen_rank_at_least_1,
    ):
        self.method_disagreements.append(
            {
                "window_start": window_start, "window_end": window_end,
                "asset_id_a": asset_id_a, "asset_id_b": asset_id_b,
                "eg_significant_5pct": eg_significant_5pct,
                "johansen_rank_at_least_1": johansen_rank_at_least_1,
                "disagree": eg_significant_5pct != johansen_rank_at_least_1,
            }
        )


class FakeHealthRepository:
    """In-memory stand-in for pipeline.health.repository.HealthRepository."""

    def __init__(self, pair_windows: dict[str, list[dict]] = None, basket_windows: dict[str, list[dict]] = None):
        self._pair_windows = pair_windows or {}
        self._basket_windows = basket_windows or {}
        self.relationship_health: list[dict] = []
        self.transitions: list[dict] = []
        self.review_flags: list[dict] = []

    def get_canonical_pair_windows(self, asset_class, interval, start, end):
        rows = []
        for key, windows in self._pair_windows.items():
            for w in windows:
                row = dict(w)
                row["relationship_key"] = key
                rows.append(row)
        return rows

    def get_basket_windows(self, asset_class, interval, start, end):
        rows = []
        for key, windows in self._basket_windows.items():
            for w in windows:
                row = dict(w)
                row["relationship_key"] = key
                rows.append(row)
        return rows

    def insert_relationship_health(self, asset_class, interval, record):
        self.relationship_health.append(dict(record))

    def insert_transition(self, asset_class, interval, record):
        self.transitions.append(dict(record))

    def flag_position_for_review(self, asset_class, interval, relationship_key, window_end, reason):
        self.review_flags.append(
            {"relationship_key": relationship_key, "window_end": window_end, "reason": reason}
        )

    def is_suspended(self, asset_class, interval, relationship_key):
        matching = [r for r in self.relationship_health if r["relationship_key"] == relationship_key]
        if not matching:
            return False
        latest = max(matching, key=lambda r: r["window_end"])
        return latest["overall_status"] == "halted"


class FakeBacktestRepository:
    """In-memory stand-in for pipeline.backtest.repository.BacktestRepository."""

    def __init__(
        self,
        pair_windows: dict[str, list[dict]] = None,
        basket_windows: dict[str, list[dict]] = None,
        health: dict[str, dict] = None,
        prices: dict[str, list[dict]] = None,
    ):
        self._pair_windows = pair_windows or {}
        self._basket_windows = basket_windows or {}
        self._health = health or {}
        self._prices = prices or {}
        self.signals: list[dict] = []
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []
        self.runs: dict[int, dict] = {}
        self._next_run_id = 1

    def list_pair_relationship_keys(self, asset_class, interval):
        return list(self._pair_windows.keys())

    def list_basket_relationship_keys(self, asset_class, interval):
        return list(self._basket_windows.keys())

    def get_pair_windows(self, asset_class, interval, relationship_key, start, end):
        return [w for w in self._pair_windows.get(relationship_key, []) if start <= w["window_end"] <= end]

    def get_basket_windows(self, asset_class, interval, relationship_key, start, end):
        return [w for w in self._basket_windows.get(relationship_key, []) if start <= w["window_end"] <= end]

    def get_health_by_window_end(self, asset_class, interval, relationship_key):
        return dict(self._health.get(relationship_key, {}))

    def get_price_series(self, symbol, asset_class, interval, start, end):
        return [row for row in self._prices.get(symbol, []) if start <= row["time"] <= end]

    def create_backtest_run(self, asset_class, strategy_variant, start, end, params, starting_equity):
        run_id = self._next_run_id
        self._next_run_id += 1
        self.runs[run_id] = {"asset_class": asset_class, "strategy_variant": strategy_variant}
        return run_id

    def finalize_backtest_run(self, run_id, final_equity, total_return_pct, sharpe, max_drawdown_pct, num_trades, halted):
        self.runs[run_id].update(
            final_equity=final_equity, total_return_pct=total_return_pct, sharpe=sharpe,
            max_drawdown_pct=max_drawdown_pct, num_trades=num_trades, halted=halted,
        )

    def insert_signal(self, run_id, asset_class, record):
        self.signals.append(dict(record))

    def insert_trade(self, run_id, asset_class, record):
        self.trades.append(dict(record))

    def insert_equity_curve_point(self, run_id, record):
        self.equity_curve.append(dict(record))

    def close(self):
        pass


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
