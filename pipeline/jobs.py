"""Glue between Settings/universe config and ingest_runner.run_ingestion -- shared by the
backfill CLI, the single-cycle CLI (for cron), and the loop-based scheduler.
"""
from __future__ import annotations

from datetime import datetime

from pipeline.config import EXPECTED_INTERVAL_MINUTES, Settings
from pipeline.ingest_runner import run_ingestion
from pipeline.logging_setup import get_logger
from pipeline.repository import Repository
from pipeline.sources.base import DataSource

logger = get_logger(__name__)

ASSET_CLASSES = ("fx", "equity", "crypto")


def _universe_and_intervals(settings: Settings, asset_class: str):
    if asset_class == "fx":
        universe_entries = [{"symbol": p} for p in settings.fx.pairs]
        intervals = settings.fx.intervals
    elif asset_class == "equity":
        universe_entries = settings.equities.universe
        intervals = settings.equities.intervals
    elif asset_class == "crypto":
        universe_entries = [{"symbol": p} for p in settings.crypto.pairs]
        intervals = settings.crypto.intervals
    else:
        raise ValueError(f"Unknown asset_class {asset_class!r}; expected one of {ASSET_CLASSES}")
    return universe_entries, intervals


def run_incremental_cycle(
    settings: Settings, repo: Repository, data_source: DataSource, asset_class: str, interval_name: str
) -> int:
    """`data_source` must be a long-lived instance reused across cycles within a process --
    its rate limiter's daily-budget counter (pipeline/util/rate_limiter.py) only means anything
    if the same instance persists across the day's calls. Under cron (a fresh process per
    invocation), that in-memory daily counter cannot persist across invocations either way; the
    budget-fit is then enforced by the configured cadence itself (see config/universe.yaml),
    not by this counter. See README "Known constraints".
    """
    universe_entries, intervals = _universe_and_intervals(settings, asset_class)
    interval_cfg = intervals[interval_name]

    logger.info("Starting incremental cycle: asset_class=%s interval=%s", asset_class, interval_name)
    rows = run_ingestion(
        repo=repo,
        data_source=data_source,
        asset_class=asset_class,
        interval_name=interval_name,
        provider_interval=interval_cfg.provider_code,
        universe_entries=universe_entries,
        run_type="incremental",
        expected_interval_minutes=EXPECTED_INTERVAL_MINUTES[interval_name],
        gap_tolerance_minutes=interval_cfg.gap_tolerance_minutes,
        alert_webhook_url=settings.alert_webhook_url,
    )
    logger.info("Finished incremental cycle: asset_class=%s interval=%s rows=%s", asset_class, interval_name, rows)
    return rows


def run_backfill(
    settings: Settings,
    repo: Repository,
    data_source: DataSource,
    asset_class: str,
    interval_name: str,
    start: datetime,
    end: datetime,
) -> int:
    universe_entries, intervals = _universe_and_intervals(settings, asset_class)
    interval_cfg = intervals[interval_name]

    logger.info(
        "Starting backfill: asset_class=%s interval=%s start=%s end=%s", asset_class, interval_name, start, end
    )
    rows = run_ingestion(
        repo=repo,
        data_source=data_source,
        asset_class=asset_class,
        interval_name=interval_name,
        provider_interval=interval_cfg.provider_code,
        universe_entries=universe_entries,
        run_type="backfill",
        expected_interval_minutes=EXPECTED_INTERVAL_MINUTES[interval_name],
        gap_tolerance_minutes=interval_cfg.gap_tolerance_minutes,
        backfill_start=start,
        backfill_end=end,
        alert_webhook_url=settings.alert_webhook_url,
    )
    logger.info("Finished backfill: asset_class=%s interval=%s rows=%s", asset_class, interval_name, rows)
    return rows
