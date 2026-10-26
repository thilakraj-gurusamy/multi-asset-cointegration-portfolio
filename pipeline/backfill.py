"""CLI: python -m pipeline.backfill --asset-class fx --interval 1hour --start 2024-01-01 --end 2024-06-01"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from pipeline.config import load_settings
from pipeline.factory import build_repository, build_source_for_asset_class
from pipeline.jobs import run_backfill
from pipeline.logging_setup import configure_logging


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill historical bars for one asset class/interval.")
    parser.add_argument("--asset-class", choices=["fx", "equity", "crypto"], required=True)
    parser.add_argument("--interval", choices=["1hour", "1day"], required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, UTC")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, UTC")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    repo = build_repository(settings)
    data_source = build_source_for_asset_class(settings, args.asset_class)
    try:
        rows = run_backfill(
            settings, repo, data_source, args.asset_class, args.interval,
            _parse_date(args.start), _parse_date(args.end),
        )
        print(f"Backfill complete: {rows} rows inserted.")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
