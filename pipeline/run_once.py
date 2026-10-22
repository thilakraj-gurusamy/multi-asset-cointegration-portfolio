"""CLI: python -m pipeline.run_once --asset-class fx --interval 1hour

Runs exactly one incremental ingest -> validate cycle and exits. Intended for cron (the FRD's
other explicitly-acceptable MVP scheduling option alongside a simple Python loop -- see
scheduler.py for the loop variant).
"""
from __future__ import annotations

import argparse

from pipeline.config import load_settings
from pipeline.factory import build_equity_source, build_fx_source, build_repository
from pipeline.jobs import run_incremental_cycle
from pipeline.logging_setup import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a single incremental ingestion cycle.")
    parser.add_argument("--asset-class", choices=["fx", "equity"], required=True)
    parser.add_argument("--interval", choices=["1hour", "1day"], required=True)
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    repo = build_repository(settings)
    data_source = build_fx_source(settings) if args.asset_class == "fx" else build_equity_source(settings)
    try:
        rows = run_incremental_cycle(settings, repo, data_source, args.asset_class, args.interval)
        print(f"Incremental cycle complete: {rows} rows inserted.")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
