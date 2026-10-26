"""Core Phase 1 orchestration: ingest -> validate -> persist raw + derived -> log quality events.

One failing asset (feed down / malformed payload / rate limit) must not abort the whole run --
it is logged as a data_quality_event and the loop continues to the next asset (FRD Section 8.4:
"must be logged and surfaced, not silently skipped"). An unexpected exception outside that
per-asset handling still marks the whole run 'failed' and re-raises.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pipeline import alerts
from pipeline.derived.stats import WINDOW, compute_derived_stats
from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.logging_setup import get_logger
from pipeline.quality.checks import GapEvent, detect_gaps, validate_bar
from pipeline.repository import Repository
from pipeline.sources.base import DataSource

logger = get_logger(__name__)


def run_ingestion(
    repo: Repository,
    data_source: DataSource,
    asset_class: str,
    interval_name: str,
    provider_interval: str,
    universe_entries: list[dict],
    run_type: str,
    expected_interval_minutes: float,
    gap_tolerance_minutes: float,
    backfill_start: datetime | None = None,
    backfill_end: datetime | None = None,
    alert_webhook_url: str | None = None,
) -> int:
    run_id = repo.start_run(asset_class, interval_name, data_source.name, run_type)
    total_rows = 0
    had_failure = False

    try:
        for entry in universe_entries:
            symbol = entry["symbol"]
            sector = entry.get("sector")
            asset_id = repo.upsert_asset(symbol, asset_class, sector, data_source.name, symbol)

            prior_watermark = None
            try:
                if run_type == "backfill":
                    if backfill_start is None or backfill_end is None:
                        raise ValueError("backfill_start/backfill_end are required for a backfill run")
                    bars = data_source.fetch_historical(symbol, provider_interval, backfill_start, backfill_end)
                else:
                    prior_watermark = repo.get_watermark(asset_id, interval_name)
                    watermark = prior_watermark
                    if watermark is None:
                        watermark = datetime.now(timezone.utc) - timedelta(minutes=expected_interval_minutes * 5)
                    bars = data_source.fetch_incremental(symbol, provider_interval, watermark)
            except RateLimitExceededError as exc:
                had_failure = True
                logger.warning("Rate limit hit for %s/%s: %s", symbol, interval_name, exc)
                repo.log_quality_event(
                    run_id, asset_id, "rate_limit", "warning", {"symbol": symbol, "error": str(exc)}
                )
                alerts.send_alert(alert_webhook_url, "rate_limit", f"Rate limit hit for {symbol}", {"error": str(exc)})
                continue
            except FeedDownError as exc:
                had_failure = True
                logger.error("Feed down for %s/%s: %s", symbol, interval_name, exc)
                repo.log_quality_event(
                    run_id, asset_id, "feed_downtime", "error", {"symbol": symbol, "error": str(exc)}
                )
                alerts.send_alert(alert_webhook_url, "feed_downtime", f"Feed down for {symbol}", {"error": str(exc)})
                continue
            except MalformedPayloadError as exc:
                had_failure = True
                logger.error("Malformed payload for %s/%s: %s", symbol, interval_name, exc)
                repo.log_quality_event(
                    run_id, asset_id, "malformed_payload", "error", {"symbol": symbol, "error": str(exc)}
                )
                alerts.send_alert(
                    alert_webhook_url, "malformed_payload", f"Malformed payload for {symbol}", {"error": str(exc)}
                )
                continue

            clean_bars = []
            for bar in bars:
                issues = validate_bar(bar)
                if issues:
                    had_failure = True
                    repo.log_quality_event(
                        run_id,
                        asset_id,
                        "malformed_payload",
                        "warning",
                        {"symbol": symbol, "issues": issues, "bar_time": str(bar.time)},
                    )
                    continue
                clean_bars.append(bar)

            if not clean_bars:
                continue

            # Defensive dedup by timestamp (observed once live against Twelve Data's FX feed --
            # a single fetch_incremental call returned two bars sharing a timestamp, which
            # crashed derived-stats' batch upsert with Postgres' "ON CONFLICT DO UPDATE command
            # cannot affect row a second time", since two NEW rows in one statement can't both
            # resolve against the same conflict target. Root cause not pinned down with
            # certainty -- it did not reproduce on a follow-up direct check of the same pairs,
            # consistent with a transient provider-side artifact around the currently-forming
            # candle -- but guarding against it here is correct regardless of cause. Keeps the
            # LAST occurrence of a duplicated timestamp (the more recently reported value).
            deduped_bars = list({bar.time: bar for bar in clean_bars}.values())
            if len(deduped_bars) < len(clean_bars):
                had_failure = True
                repo.log_quality_event(
                    run_id, asset_id, "malformed_payload", "warning",
                    {"symbol": symbol, "issue": "duplicate timestamp(s) in one fetch", "before": len(clean_bars), "after": len(deduped_bars)},
                )
            clean_bars = deduped_bars

            gaps = detect_gaps(clean_bars, expected_interval_minutes, gap_tolerance_minutes, symbol, interval_name)

            # detect_gaps only sees gaps WITHIN this cycle's new bars -- it cannot see a gap
            # between the previously-stored watermark and the first new bar (e.g. the pipeline
            # was stale/down for a long stretch and the next pull jumps forward). Checked
            # separately here since the watermark has no OHLC to build a Bar from.
            if prior_watermark is not None:
                boundary_gap_minutes = (clean_bars[0].time - prior_watermark).total_seconds() / 60
                if boundary_gap_minutes > gap_tolerance_minutes:
                    gaps = [
                        GapEvent(
                            asset_symbol=symbol,
                            interval=interval_name,
                            gap_start=prior_watermark,
                            gap_end=clean_bars[0].time,
                            gap_minutes=boundary_gap_minutes,
                        )
                    ] + gaps

            for gap in gaps:
                repo.log_quality_event(
                    run_id,
                    asset_id,
                    "data_gap",
                    "warning",
                    {
                        "symbol": symbol,
                        "gap_start": str(gap.gap_start),
                        "gap_end": str(gap.gap_end),
                        "gap_minutes": gap.gap_minutes,
                    },
                )

            inserted = repo.insert_bars(asset_id, interval_name, clean_bars, data_source.name)
            total_rows += inserted
            repo.set_watermark(asset_id, interval_name, clean_bars[-1].time)

            lookback = repo.get_recent_closes(asset_id, interval_name, before=clean_bars[0].time, limit=WINDOW)
            derived_df = compute_derived_stats(lookback + clean_bars)
            new_times = {b.time for b in clean_bars}
            new_rows = []
            for _, row in derived_df.iterrows():
                row_time = row["time"]
                row_time = row_time.to_pydatetime() if hasattr(row_time, "to_pydatetime") else row_time
                if row_time in new_times:
                    new_rows.append(
                        {
                            "time": row_time,
                            "log_return": None if row["log_return"] is None or row["log_return"] != row["log_return"] else row["log_return"],
                            "rolling_mean_20": None if row["rolling_mean_20"] != row["rolling_mean_20"] else row["rolling_mean_20"],
                            "rolling_std_20": None if row["rolling_std_20"] != row["rolling_std_20"] else row["rolling_std_20"],
                        }
                    )
            repo.insert_derived_stats(asset_id, interval_name, new_rows)

        repo.finish_run(run_id, "partial" if had_failure else "success", total_rows)
    except Exception as exc:  # unexpected failure outside the per-asset handling above
        repo.finish_run(run_id, "failed", total_rows, str(exc))
        alerts.send_alert(alert_webhook_url, "other", f"Ingestion run {run_id} failed", {"error": str(exc)})
        raise

    return total_rows
