"""The paper-trading execution loop (FRD Section 8.8): ingest -> validate -> health check ->
signal, end to end, against live/near-real-time data, with simulated fills only -- no
brokerage connection, no real order, under any configuration (see pipeline/signals/rules.py
and pipeline/backtest/engine.py, which this reuses unchanged; there is no code path here that
calls a broker API).

Cadence note (a deliberate, documented decision, same pattern as the Phase 1 Scope Decision):
this cycle's own job is DAILY -- Phase 2 (cointegration) and Phase 3 (health) only operate on
"1day" bars, so re-running them more often than once a day cannot produce new information.
Phase 1's near-real-time ingestion (every 15/60 minutes) is a SEPARATE, already-existing
process (pipeline/scheduler.py) that keeps running independently; this cycle re-runs the "1day"
incremental ingest for safety (in case the scheduler process is down) and then rolls Phase
2->3->4 forward once new daily data is actually present (idempotent either way -- see
pipeline/paper_trading/signals.py).

Crypto runs through ingest -> cointegration -> health, exactly like FX/equities, reusing the
same code unchanged -- but is never passed to the paper-signal step. That exclusion is
structural (the signals step only ever receives "fx"/"equity"), not a conditional that could be
flipped by a config value.

`run_cycle` takes its four repositories (and the ingestion-source factory) as parameters,
rather than constructing them internally, specifically so the orchestration/failure-isolation
logic below can be unit-tested against fakes and monkeypatched step functions without a live
database -- `run_cycle_with_logging` is the thin wrapper that builds the real ones.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

from pipeline import alerts
from pipeline.backtest.repository import BacktestRepository
from pipeline.cointegration.engine import run_rolling_cointegration
from pipeline.cointegration.repository import CointegrationRepository
from pipeline.config import Settings, load_settings
from pipeline.factory import build_source_for_asset_class
from pipeline.health.monitor import run_health_monitor
from pipeline.health.repository import HealthRepository
from pipeline.jobs import run_incremental_cycle
from pipeline.logging_setup import configure_logging, get_logger
from pipeline.paper_trading.signals import run_paper_signals_for_asset_class
from pipeline.repository import PostgresRepository

logger = get_logger(__name__)

INTERVAL = "1day"
ALL_ASSET_CLASSES = ("fx", "equity", "crypto")
PAPER_SIGNAL_ASSET_CLASSES = ("fx", "equity")  # crypto is structurally excluded here, not by a flag

COINTEGRATION_LOOKBACK_DAYS = 150  # just enough margin past window_bars (90) to roll forward
                                     # correctly; ON CONFLICT DO UPDATE makes re-running this
                                     # range safe regardless, but there is no reason to pay for
                                     # recomputing hundreds of already-settled historical windows
                                     # every single cycle when at most one NEW window (step_bars
                                     # apart) can appear between cycles -- confirmed live: a 400-
                                     # day lookback took ~4.9 minutes/cycle across 3 asset
                                     # classes; this bound keeps the cycle comfortably inside an
                                     # hourly cadence with a much smaller fraction spent on it


def _universe_for(settings: Settings, asset_class: str) -> tuple[list[str], list[list[str]], int, int]:
    if asset_class == "fx":
        return settings.fx.pairs, settings.cointegration.fx.baskets, settings.cointegration.fx.window_bars, settings.cointegration.fx.step_bars
    if asset_class == "equity":
        symbols = [e["symbol"] for e in settings.equities.universe]
        return symbols, settings.cointegration.equities.baskets, settings.cointegration.equities.window_bars, settings.cointegration.equities.step_bars
    coint_cfg = settings.cointegration.crypto
    symbols = coint_cfg.symbols if coint_cfg.symbols is not None else settings.crypto.pairs
    return symbols, coint_cfg.baskets, coint_cfg.window_bars, coint_cfg.step_bars


def run_cycle(
    settings: Settings,
    cycle_id: int,
    started_at: datetime,
    ingest_repo,
    coint_repo,
    health_repo,
    backtest_repo,
    build_source: Callable = build_source_for_asset_class,
) -> dict:
    steps: dict[str, dict] = {}

    for asset_class in ALL_ASSET_CLASSES:
        try:
            source = build_source(settings, asset_class)
            rows = run_incremental_cycle(settings, ingest_repo, source, asset_class, INTERVAL)
            steps[f"ingest_{asset_class}"] = {"status": "success", "rows": rows}
        except Exception as exc:
            logger.exception("Ingest step failed for %s", asset_class)
            steps[f"ingest_{asset_class}"] = {"status": "failed", "error": str(exc)}
            alerts.send_alert(
                settings.alert_webhook_url, "feed_downtime",
                f"Paper-trading cycle: ingest failed for {asset_class}", {"error": str(exc)},
            )

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=COINTEGRATION_LOOKBACK_DAYS)

    for asset_class in ALL_ASSET_CLASSES:
        try:
            symbols, baskets, window_bars, step_bars = _universe_for(settings, asset_class)
            summary = run_rolling_cointegration(
                repo=coint_repo, asset_class=asset_class, symbols=symbols, baskets=baskets,
                window_bars=window_bars, step_bars=step_bars, start=start, end=end,
            )
            steps[f"cointegration_{asset_class}"] = {"status": "success", "windows": summary.windows_processed}
        except Exception as exc:
            logger.exception("Cointegration step failed for %s", asset_class)
            steps[f"cointegration_{asset_class}"] = {"status": "failed", "error": str(exc)}
            alerts.send_alert(
                settings.alert_webhook_url, "other",
                f"Paper-trading cycle: cointegration step failed for {asset_class}", {"error": str(exc)},
            )

    for asset_class in ALL_ASSET_CLASSES:
        try:
            summary = run_health_monitor(
                repo=health_repo, asset_class=asset_class, interval=INTERVAL, start=start, end=end,
                alert_webhook_url=settings.alert_webhook_url,
            )
            steps[f"health_{asset_class}"] = {
                "status": "success", "transitions": summary.transitions_logged, "halted": summary.halted_transitions,
            }
        except Exception as exc:
            logger.exception("Health step failed for %s", asset_class)
            steps[f"health_{asset_class}"] = {"status": "failed", "error": str(exc)}
            alerts.send_alert(
                settings.alert_webhook_url, "other",
                f"Paper-trading cycle: health step failed for {asset_class}", {"error": str(exc)},
            )

    for asset_class in PAPER_SIGNAL_ASSET_CLASSES:
        try:
            result = run_paper_signals_for_asset_class(backtest_repo, asset_class, INTERVAL, settings.backtest)
            steps[f"paper_signals_{asset_class}"] = {"status": "success", **result}
        except Exception as exc:
            logger.exception("Paper-signal step failed for %s", asset_class)
            steps[f"paper_signals_{asset_class}"] = {"status": "failed", "error": str(exc)}
            alerts.send_alert(
                settings.alert_webhook_url, "other",
                f"Paper-trading cycle: paper-signal step failed for {asset_class}", {"error": str(exc)},
            )

    # "skipped" (the paper-signal idempotency guard's correct no-op when a day is already
    # processed) counts as a GOOD outcome for aggregation, same as "success" -- it means
    # nothing was wrong, there was just nothing new to do. Only "failed" steps should pull the
    # overall status down.
    statuses = [s["status"] for s in steps.values()]
    ok_statuses = {"success", "skipped"}
    if all(s in ok_statuses for s in statuses):
        overall_status = "success"
    elif any(s in ok_statuses for s in statuses):
        overall_status = "partial"
    else:
        overall_status = "failed"

    finished_at = datetime.now(timezone.utc)
    backtest_repo.finish_cycle_log(
        cycle_id=cycle_id, finished_at=finished_at, status=overall_status, steps=steps,
        error_message=None, duration_seconds=(finished_at - started_at).total_seconds(),
    )
    return {"status": overall_status, "steps": steps, "duration_seconds": (finished_at - started_at).total_seconds()}


def run_cycle_with_logging(settings: Settings) -> dict:
    """Builds the four real repositories and runs one cycle end to end."""
    started_at = datetime.now(timezone.utc)

    ingest_repo = PostgresRepository(settings.database_url)
    coint_repo = CointegrationRepository(settings.database_url)
    health_repo = HealthRepository(settings.database_url)
    backtest_repo = BacktestRepository(settings.database_url)

    try:
        cycle_id = backtest_repo.start_cycle_log(started_at)
        try:
            return run_cycle(settings, cycle_id, started_at, ingest_repo, coint_repo, health_repo, backtest_repo)
        except Exception as exc:
            finished_at = datetime.now(timezone.utc)
            backtest_repo.finish_cycle_log(
                cycle_id=cycle_id, finished_at=finished_at, status="failed", steps={},
                error_message=str(exc), duration_seconds=(finished_at - started_at).total_seconds(),
            )
            alerts.send_alert(settings.alert_webhook_url, "other", "Paper-trading cycle failed outright", {"error": str(exc)})
            raise
    finally:
        ingest_repo.close()
        coint_repo.close()
        health_repo.close()
        backtest_repo.close()


if __name__ == "__main__":
    _settings = load_settings()
    configure_logging(_settings.log_level)
    result = run_cycle_with_logging(_settings)
    print(result)
