"""CLI: python -m pipeline.health.run --asset-class fx --start 2022-01-01 --end 2024-06-01

Consumes Phase 2's already-computed rolling-window output for the given range; does not
re-run Phase 2 itself.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from pipeline.config import load_settings
from pipeline.health.monitor import run_health_monitor
from pipeline.health.repository import HealthRepository
from pipeline.logging_setup import configure_logging


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run relationship-health monitoring (Phase 3) over an already-computed Phase 2 range.")
    parser.add_argument("--asset-class", choices=["fx", "equity"], required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, UTC")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, UTC")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    repo = HealthRepository(settings.database_url)
    try:
        summary = run_health_monitor(
            repo=repo, asset_class=args.asset_class, interval="1day",
            start=_parse_date(args.start), end=_parse_date(args.end),
            alert_webhook_url=settings.alert_webhook_url,
        )
        print(
            f"Relationships processed: {summary.relationships_processed}\n"
            f"Windows processed: {summary.windows_processed}\n"
            f"Status transitions logged: {summary.transitions_logged}\n"
            f"Transitions to halted: {summary.halted_transitions}\n"
            f"Failed relationships (health-check errors): {summary.failed_relationships}"
        )
    finally:
        repo.close()


if __name__ == "__main__":
    main()
