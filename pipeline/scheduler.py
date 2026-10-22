"""Minimal Python scheduler loop -- the FRD explicitly allows "cron, or a simple Python
scheduler loop" as the Phase 1 MVP orchestration (Section 10). This runs ingest -> validate
end to end for every (asset_class, interval) job on its own configured cadence, in one process.

For a cron-based deployment instead, see README: it documents the equivalent crontab lines
calling `python -m pipeline.run_once` per job -- no extra code is needed for that path.
"""
from __future__ import annotations

import signal
import time
from dataclasses import dataclass

from pipeline.config import Settings, load_settings
from pipeline.factory import build_equity_source, build_fx_source, build_repository
from pipeline.jobs import run_incremental_cycle
from pipeline.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)

POLL_SECONDS = 5


@dataclass
class ScheduledJob:
    asset_class: str
    interval_name: str
    cadence_minutes: float
    last_run_monotonic: float = 0.0


def _build_jobs(settings: Settings) -> list[ScheduledJob]:
    jobs = []
    for interval_name, cfg in settings.fx.intervals.items():
        jobs.append(ScheduledJob("fx", interval_name, cfg.cadence_minutes))
    for interval_name, cfg in settings.equities.intervals.items():
        jobs.append(ScheduledJob("equity", interval_name, cfg.cadence_minutes))
    return jobs


def run_forever() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    repo = build_repository(settings)
    jobs = _build_jobs(settings)

    # Built once and reused for the life of this process -- each source wraps a rate-limited
    # client whose daily-request-budget counter (pipeline/util/rate_limiter.py) only protects
    # the free-tier quota if the same instance persists across the day's cycles. Rebuilding a
    # fresh client per cycle would silently reset that counter every time.
    sources = {"fx": build_fx_source(settings), "equity": build_equity_source(settings)}

    logger.info("Scheduler starting with %s jobs: %s", len(jobs), [(j.asset_class, j.interval_name) for j in jobs])

    stop = {"flag": False}

    def _handle_sigterm(signum, frame):
        logger.info("Received signal %s, shutting down after current cycle.", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        while not stop["flag"]:
            now = time.monotonic()
            for job in jobs:
                if now - job.last_run_monotonic >= job.cadence_minutes * 60:
                    try:
                        run_incremental_cycle(
                            settings, repo, sources[job.asset_class], job.asset_class, job.interval_name
                        )
                    except Exception:
                        logger.exception(
                            "Unhandled error running job asset_class=%s interval=%s -- scheduler continues.",
                            job.asset_class,
                            job.interval_name,
                        )
                    job.last_run_monotonic = time.monotonic()
            time.sleep(POLL_SECONDS)
    finally:
        repo.close()


if __name__ == "__main__":
    run_forever()
