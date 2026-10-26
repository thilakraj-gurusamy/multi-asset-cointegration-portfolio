"""Loop-based scheduler for the paper-trading cycle -- same shape as pipeline/scheduler.py
(Phase 1's near-real-time ingestion loop), which keeps running as its own separate process;
this one drives Phase 2 -> 3 -> 4 forward on top of whatever that loop has ingested.

Runs every CYCLE_INTERVAL_SECONDS. Each tick is cheap/idempotent when there is nothing new to
do (see pipeline/paper_trading/signals.py's same-day guard), so a short interval does not waste
meaningful work -- it just means new daily data gets picked up promptly once it appears.
"""
from __future__ import annotations

import signal
import time

from pipeline.config import load_settings
from pipeline.logging_setup import configure_logging, get_logger
from pipeline.paper_trading.cycle import run_cycle_with_logging

logger = get_logger(__name__)

CYCLE_INTERVAL_SECONDS = 3600  # hourly -- Phase 2/3/4 only act on daily bars, so there is
                                 # nothing to gain from checking more often than this


def run_forever() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    stop = {"flag": False}

    def _handle_sigterm(signum, frame):
        logger.info("Received signal %s, shutting down after current cycle.", signum)
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_sigterm)
    signal.signal(signal.SIGTERM, _handle_sigterm)

    logger.info("Paper-trading scheduler starting (cycle every %ss).", CYCLE_INTERVAL_SECONDS)

    while not stop["flag"]:
        try:
            result = run_cycle_with_logging(settings)
            logger.info("Paper-trading cycle complete: %s", result["status"])
        except Exception:
            logger.exception("Paper-trading cycle raised unexpectedly -- scheduler continues.")

        for _ in range(CYCLE_INTERVAL_SECONDS):
            if stop["flag"]:
                break
            time.sleep(1)


if __name__ == "__main__":
    run_forever()
