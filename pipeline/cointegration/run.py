"""CLI: python -m pipeline.cointegration.run --asset-class fx --start 2023-01-01 --end 2024-06-01"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from pipeline.cointegration.engine import run_rolling_cointegration
from pipeline.cointegration.repository import CointegrationRepository
from pipeline.config import load_settings
from pipeline.logging_setup import configure_logging


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the rolling-window cointegration engine (Phase 2).")
    parser.add_argument("--asset-class", choices=["fx", "equity", "crypto"], required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, UTC")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, UTC")
    args = parser.parse_args()

    settings = load_settings()
    configure_logging(settings.log_level)

    if args.asset_class == "fx":
        symbols = settings.fx.pairs
        coint_cfg = settings.cointegration.fx
    elif args.asset_class == "equity":
        symbols = [e["symbol"] for e in settings.equities.universe]
        coint_cfg = settings.cointegration.equities
    else:
        symbols = settings.crypto.pairs
        coint_cfg = settings.cointegration.crypto

    if coint_cfg.symbols is not None:
        symbols = coint_cfg.symbols

    repo = CointegrationRepository(settings.database_url)
    try:
        summary = run_rolling_cointegration(
            repo=repo,
            asset_class=args.asset_class,
            symbols=symbols,
            baskets=coint_cfg.baskets,
            window_bars=coint_cfg.window_bars,
            step_bars=coint_cfg.step_bars,
            start=_parse_date(args.start),
            end=_parse_date(args.end),
        )
        print(
            f"Windows processed: {summary.windows_processed}\n"
            f"ADF exclusions: {summary.adf_exclusions}\n"
            f"Engle-Granger pairs tested: {summary.engle_granger_pairs_tested}\n"
            f"Johansen tests run: {summary.johansen_tests_run}\n"
            f"EG/Johansen disagreements: {summary.disagreements_found}"
        )
    finally:
        repo.close()


if __name__ == "__main__":
    main()
