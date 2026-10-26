"""Walk-forward portfolio backtest (FRD Section 8.8): rolling in-sample fit -> out-of-sample
test -> roll forward, for the FULL signal + health-gating + risk pipeline together. Never a
single full-history fit evaluated in-sample.

Two-stage design: `pipeline/backtest/fitting.py` resolves each relationship's walk-forward fit
into a per-date series (pure, no position state); THIS module steps through the calendar once,
date-major, across ALL relationships simultaneously, so a single portfolio-level equity curve
and drawdown halt (FRD 8.7d) can be computed -- a per-relationship-independent backtest could
not express "halt new entries everywhere because the PORTFOLIO drew down."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from pipeline.backtest.costs import compute_round_trip_leg_cost
from pipeline.backtest.fitting import DailyFit, build_relationship_timeseries
from pipeline.backtest.repository import BacktestRepository
from pipeline.config import BacktestConfig
from pipeline.logging_setup import get_logger
from pipeline.risk.drawdown import DrawdownTracker
from pipeline.risk.leverage import leverage_capped_units
from pipeline.risk.liquidity import equity_liquidity_capped_units, fx_liquidity_capped_units
from pipeline.risk.sizing import vol_target_units
from pipeline.signals.rules import ENTER_LONG, ENTER_SHORT, EXIT_HEALTH_HALTED, EXIT_Z, decide_action

logger = get_logger(__name__)

LIQUIDITY_LOOKBACK_BARS = 20


@dataclass
class OpenPosition:
    direction: str  # "long" | "short"
    entry_date: datetime
    entry_z: float | None
    entry_spread_value: float
    position_units: float
    sizing_detail: dict
    last_spread: float


@dataclass
class BacktestResult:
    equity_curve: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    halted: bool = False
    final_equity: float = 0.0


@dataclass
class DayEvaluation:
    action: str
    pnl_delta: float
    updated_position: OpenPosition | None
    closed_trade: dict | None
    signal_record: dict


def evaluate_relationship_day(
    key: str,
    fit: DailyFit,
    position: OpenPosition | None,
    asset_class: str,
    cfg: BacktestConfig,
    prices_by_symbol: dict,
    volumes_by_symbol: dict,
    portfolio_halted: bool,
    max_loss_dollars: float,
) -> DayEvaluation:
    """One relationship, one day: decide the action, mark any open position to market, execute
    an entry/exit with costs if warranted. Pulled out of simulate_portfolio() specifically so
    the live paper-trading loop (pipeline/paper_trading/cycle.py) can call the IDENTICAL
    decision+execution logic one day at a time against DB-persisted position state, instead of
    duplicating it -- the backtest and the live loop must never be able to silently diverge in
    what counts as an entry, an exit, or a correctly-sized position.
    """
    position_direction = position.direction if position else None
    action = decide_action(position_direction, fit.z, fit.health_status, cfg.z_entry, cfg.z_exit, portfolio_halted)

    signal_record = {
        "relationship_key": key, "date": fit.date, "window_start": fit.window_start, "window_end": fit.window_end,
        "z_score": fit.z, "health_status": fit.health_status, "weights": fit.weights,
        "z_entry": cfg.z_entry, "z_exit": cfg.z_exit, "action": action,
    }

    pnl_delta = 0.0
    updated_position = position
    closed_trade = None

    if position is not None:
        direction_sign = 1.0 if position.direction == "long" else -1.0
        pnl_delta += direction_sign * position.position_units * (fit.spread - position.last_spread)
        position.last_spread = fit.spread

        if action in (EXIT_Z, EXIT_HEALTH_HALTED):
            exit_notional = abs(position.position_units * fit.spread)
            costs = compute_round_trip_leg_cost(exit_notional, cfg.transaction_cost_bps, cfg.slippage_bps)
            pnl_delta -= costs.total
            gross_pnl = direction_sign * position.position_units * (fit.spread - position.entry_spread_value)
            closed_trade = {
                "relationship_key": key, "direction": position.direction, "entry_date": position.entry_date,
                "entry_z": position.entry_z, "entry_spread_value": position.entry_spread_value,
                "position_units": position.position_units, "sizing_detail": position.sizing_detail,
                "exit_date": fit.date, "exit_z": fit.z, "exit_spread_value": fit.spread,
                "exit_reason": "z_exit" if action == EXIT_Z else "health_halted_stop",
                "gross_pnl": gross_pnl, "transaction_cost": costs.transaction_cost,
                "slippage_cost": costs.slippage_cost, "net_pnl": gross_pnl - costs.total,
            }
            updated_position = None

    elif action in (ENTER_LONG, ENTER_SHORT):
        vol_units = vol_target_units(cfg.target_daily_vol_per_position, fit.spread_change_std)
        lev_units = leverage_capped_units(max_loss_dollars, fit.spread_worst_case_move)
        liq_units = _compute_liquidity_cap(asset_class, fit.legs, fit.weights, fit.date, prices_by_symbol, volumes_by_symbol, cfg)
        units = min(vol_units, lev_units, liq_units)
        if units > 0 and np.isfinite(units):
            entry_notional = abs(units * fit.spread)
            costs = compute_round_trip_leg_cost(entry_notional, cfg.transaction_cost_bps, cfg.slippage_bps)
            pnl_delta -= costs.total
            updated_position = OpenPosition(
                direction="long" if action == ENTER_LONG else "short", entry_date=fit.date, entry_z=fit.z,
                entry_spread_value=fit.spread, position_units=units,
                sizing_detail={
                    "vol_target_units": vol_units, "leverage_cap_units": lev_units, "liquidity_cap_units": liq_units,
                },
                last_spread=fit.spread,
            )

    return DayEvaluation(
        action=action, pnl_delta=pnl_delta, updated_position=updated_position,
        closed_trade=closed_trade, signal_record=signal_record,
    )


def _compute_liquidity_cap(
    asset_class: str, legs: list[str], weights: list[float], date, prices_by_symbol: dict, volumes_by_symbol: dict, cfg: BacktestConfig
) -> float:
    caps = []
    for leg, w in zip(legs, weights):
        price_today = prices_by_symbol[leg].get(date)
        if price_today is None or w == 0:
            continue
        unit_notional = abs(w) * price_today

        if asset_class == "equity":
            dates_before = sorted(d for d in volumes_by_symbol[leg] if d <= date)[-LIQUIDITY_LOOKBACK_BARS:]
            recent_volumes = [volumes_by_symbol[leg][d] for d in dates_before if volumes_by_symbol[leg][d] is not None]
            recent_prices = [prices_by_symbol[leg][d] for d in dates_before if d in prices_by_symbol[leg]]
            cap = equity_liquidity_capped_units(recent_volumes, recent_prices, cfg.liquidity.equity_adv_fraction, unit_notional)
        else:
            cap = fx_liquidity_capped_units(cfg.liquidity.fx_max_notional_per_position, unit_notional)
        caps.append(cap)

    return min(caps) if caps else float("inf")


def _build_all_fits(
    repo: BacktestRepository, asset_class: str, interval: str, pair_keys: list[str], basket_keys: list[str],
    start: datetime, end: datetime, z_lookback_bars: int,
) -> tuple[dict[str, list[DailyFit]], dict[str, dict], dict[str, dict]]:
    """Returns (fits_by_relationship, prices_by_symbol_by_relationship, volumes_by_symbol_by_relationship)."""
    fits: dict[str, list[DailyFit]] = {}
    prices_cache: dict[str, dict] = {}
    volumes_cache: dict[str, dict] = {}

    for key in pair_keys:
        windows = repo.get_pair_windows(asset_class, interval, key, start, end)
        if not windows:
            continue
        legs = windows[0]["legs"]
        fetch_start = min(w["window_start"] for w in windows)
        prices_by_symbol = {}
        volumes_by_symbol = {}
        for s in legs:
            rows = repo.get_price_series(s, asset_class, interval, fetch_start, end)
            prices_by_symbol[s] = {r["time"]: r["close"] for r in rows}
            volumes_by_symbol[s] = {r["time"]: r["volume"] for r in rows}
        health = repo.get_health_by_window_end(asset_class, interval, key)
        relationship_fits = build_relationship_timeseries(windows, health, prices_by_symbol, z_lookback_bars, end)
        if relationship_fits:
            fits[key] = relationship_fits
            prices_cache[key] = prices_by_symbol
            volumes_cache[key] = volumes_by_symbol

    for key in basket_keys:
        windows = repo.get_basket_windows(asset_class, interval, key, start, end)
        usable = [w for w in windows if w.get("weights")]
        if not usable:
            continue
        legs = usable[0]["legs"]
        fetch_start = min(w["window_start"] for w in windows)
        prices_by_symbol = {}
        volumes_by_symbol = {}
        for s in legs:
            rows = repo.get_price_series(s, asset_class, interval, fetch_start, end)
            prices_by_symbol[s] = {r["time"]: r["close"] for r in rows}
            volumes_by_symbol[s] = {r["time"]: r["volume"] for r in rows}
        health = repo.get_health_by_window_end(asset_class, interval, key)
        relationship_fits = build_relationship_timeseries(windows, health, prices_by_symbol, z_lookback_bars, end)
        if relationship_fits:
            fits[key] = relationship_fits
            prices_cache[key] = prices_by_symbol
            volumes_cache[key] = volumes_by_symbol

    return fits, prices_cache, volumes_cache


def simulate_portfolio(
    fits: dict[str, list[DailyFit]],
    prices_cache: dict[str, dict],
    volumes_cache: dict[str, dict],
    asset_class: str,
    cfg: BacktestConfig,
) -> BacktestResult:
    """The date-major position/P&L/drawdown simulation, shared by the walk-forward
    health-gated backtest and the naive static-EG baseline (FRD Section 12) -- both produce
    `fits` the same shape (just via different fitting logic upstream), and from here on the
    risk/cost/drawdown machinery is identical, which is what makes the Sharpe comparison
    between them meaningful (same engine, different inputs) rather than two different engines.
    """
    fits_by_date: dict[str, dict] = {key: {f.date: f for f in series} for key, series in fits.items()}
    all_sim_dates = sorted(set().union(*(d.keys() for d in fits_by_date.values()))) if fits_by_date else []

    drawdown = DrawdownTracker(cfg.starting_equity, cfg.portfolio_max_drawdown_pct)
    open_positions: dict[str, OpenPosition] = {}
    result = BacktestResult()

    max_loss_dollars = cfg.starting_equity * cfg.max_loss_per_position_pct / 100.0

    for d in all_sim_dates:
        daily_pnl = 0.0

        for key, date_map in fits_by_date.items():
            fit = date_map.get(d)
            if fit is None:
                continue

            position = open_positions.get(key)
            evaluation = evaluate_relationship_day(
                key, fit, position, asset_class, cfg, prices_cache[key], volumes_cache[key],
                drawdown.halted, max_loss_dollars,
            )

            result.signals.append(evaluation.signal_record)
            daily_pnl += evaluation.pnl_delta
            if evaluation.closed_trade:
                result.trades.append(evaluation.closed_trade)
            if evaluation.updated_position is not None:
                open_positions[key] = evaluation.updated_position
            elif key in open_positions:
                del open_positions[key]

        drawdown.update(daily_pnl)
        result.equity_curve.append(
            {"date": d, "equity": drawdown.equity, "daily_pnl": daily_pnl, "drawdown_pct": drawdown.current_drawdown_pct, "halted": drawdown.halted}
        )

    end_of_backtest_costs = 0.0
    for key, position in list(open_positions.items()):
        direction_sign = 1.0 if position.direction == "long" else -1.0
        gross_pnl = direction_sign * position.position_units * (position.last_spread - position.entry_spread_value)
        exit_notional = abs(position.position_units * position.last_spread)
        costs = compute_round_trip_leg_cost(exit_notional, cfg.transaction_cost_bps, cfg.slippage_bps)
        end_of_backtest_costs += costs.total
        result.trades.append(
            {
                "relationship_key": key, "direction": position.direction, "entry_date": position.entry_date,
                "entry_z": position.entry_z, "entry_spread_value": position.entry_spread_value,
                "position_units": position.position_units, "sizing_detail": position.sizing_detail,
                "exit_date": all_sim_dates[-1] if all_sim_dates else position.entry_date, "exit_z": None,
                "exit_spread_value": position.last_spread, "exit_reason": "end_of_backtest",
                "gross_pnl": gross_pnl, "transaction_cost": costs.transaction_cost,
                "slippage_cost": costs.slippage_cost, "net_pnl": gross_pnl - costs.total,
            }
        )

    result.halted = drawdown.halted
    # Positions still open at the end are marked-to-market in the equity curve already (their
    # daily P&L was accumulated day by day); only the final closing cost -- not yet charged
    # anywhere -- needs to be deducted here so final_equity matches what the trade log reports.
    result.final_equity = drawdown.equity - end_of_backtest_costs
    return result


def run_walk_forward_backtest(
    repo: BacktestRepository,
    asset_class: str,
    interval: str,
    pair_keys: list[str],
    basket_keys: list[str],
    start: datetime,
    end: datetime,
    cfg: BacktestConfig,
) -> BacktestResult:
    fits, prices_cache, volumes_cache = _build_all_fits(
        repo, asset_class, interval, pair_keys, basket_keys, start, end, cfg.z_lookback_bars
    )
    return simulate_portfolio(fits, prices_cache, volumes_cache, asset_class, cfg)
