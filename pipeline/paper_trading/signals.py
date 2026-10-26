"""Live paper-signal step (FRD Section 8.8): applies the EXACT SAME decision/execution logic
as the Phase 4 backtest (pipeline.backtest.engine.evaluate_relationship_day) to TODAY's bar
only, with position state loaded from and saved back to the database so it persists across
cycles -- unlike the backtest's in-memory-only open_positions dict, which starts flat every run.

Idempotent by construction: if this asset class's paper_equity_curve already has a row for
`latest_date`, the cycle has already processed that day and this is a no-op -- a scheduler
firing more than once before new daily data arrives (entirely expected) must never double-count
P&L or double-close a position.

Crypto is deliberately never passed to this function -- see pipeline/paper_trading/cycle.py.
"""
from __future__ import annotations

from datetime import timedelta

from pipeline.backtest.engine import OpenPosition, _build_all_fits, evaluate_relationship_day
from pipeline.backtest.repository import BacktestRepository
from pipeline.config import BacktestConfig
from pipeline.logging_setup import get_logger
from pipeline.risk.drawdown import DrawdownTracker

logger = get_logger(__name__)

FIT_LOOKBACK_DAYS = 400  # enough history for build_relationship_timeseries to resolve the
                          # CURRENT governing window correctly; cheap since it is bounded


def _load_drawdown_state(repo: BacktestRepository, asset_class: str, cfg: BacktestConfig) -> DrawdownTracker:
    tracker = DrawdownTracker(cfg.starting_equity, cfg.portfolio_max_drawdown_pct)
    latest = repo.get_latest_paper_equity(asset_class)
    if latest:
        tracker.equity = latest["equity"]
        tracker.peak_equity = latest["peak_equity"]
        tracker.current_drawdown_pct = latest["drawdown_pct"]
        tracker.halted = latest["halted"]  # reloaded as-is -- never auto-resets on its own
    return tracker


def _position_from_row(row: dict) -> OpenPosition:
    return OpenPosition(
        direction=row["direction"], entry_date=row["entry_date"], entry_z=row["entry_z"],
        entry_spread_value=row["entry_spread_value"], position_units=row["position_units"],
        sizing_detail=row["sizing_detail"], last_spread=row["last_spread"],
    )


def run_paper_signals_for_asset_class(repo: BacktestRepository, asset_class: str, interval: str, cfg: BacktestConfig) -> dict:
    latest_date = repo.get_latest_bar_date(asset_class, interval)
    if latest_date is None:
        return {"status": "skipped", "reason": "no bars available yet"}

    existing = repo.get_latest_paper_equity(asset_class)
    if existing and existing["date"] >= latest_date.date():
        return {"status": "skipped", "reason": f"already processed through {existing['date']}"}

    pair_keys = repo.list_pair_relationship_keys(asset_class, interval)
    basket_keys = repo.list_basket_relationship_keys(asset_class, interval)
    start = latest_date - timedelta(days=FIT_LOOKBACK_DAYS)

    fits, prices_cache, volumes_cache = _build_all_fits(
        repo, asset_class, interval, pair_keys, basket_keys, start, latest_date, cfg.z_lookback_bars
    )

    drawdown = _load_drawdown_state(repo, asset_class, cfg)
    max_loss_dollars = cfg.starting_equity * cfg.max_loss_per_position_pct / 100.0
    daily_pnl = 0.0
    relationships_evaluated = 0
    trades_closed = 0
    entries_opened = 0

    for key, series in fits.items():
        if not series or series[-1].date != latest_date:
            continue  # no fit governs today for this relationship right now
        fit = series[-1]
        relationships_evaluated += 1

        position_row = repo.get_open_position(asset_class, key)
        position = _position_from_row(position_row) if position_row else None

        evaluation = evaluate_relationship_day(
            key, fit, position, asset_class, cfg, prices_cache[key], volumes_cache[key],
            drawdown.halted, max_loss_dollars,
        )
        daily_pnl += evaluation.pnl_delta

        if evaluation.closed_trade:
            repo.insert_paper_trade(asset_class, evaluation.closed_trade)
            repo.delete_open_position(asset_class, key)
            trades_closed += 1
        elif evaluation.updated_position is not None:
            pos = evaluation.updated_position
            if position is None:
                entries_opened += 1
            repo.save_open_position(
                asset_class, key,
                {
                    "direction": pos.direction, "entry_date": pos.entry_date, "entry_z": pos.entry_z,
                    "entry_spread_value": pos.entry_spread_value, "position_units": pos.position_units,
                    "sizing_detail": pos.sizing_detail, "last_mark_date": latest_date.date(),
                    "last_spread": pos.last_spread,
                },
            )

    drawdown.update(daily_pnl)
    repo.insert_paper_equity_point(
        asset_class,
        {
            "date": latest_date.date(), "equity": drawdown.equity, "peak_equity": drawdown.peak_equity,
            "daily_pnl": daily_pnl, "drawdown_pct": drawdown.current_drawdown_pct, "halted": drawdown.halted,
        },
    )

    return {
        "status": "success", "date": str(latest_date.date()), "relationships_evaluated": relationships_evaluated,
        "entries_opened": entries_opened, "trades_closed": trades_closed, "daily_pnl": daily_pnl,
        "equity": drawdown.equity, "halted": drawdown.halted,
    }
