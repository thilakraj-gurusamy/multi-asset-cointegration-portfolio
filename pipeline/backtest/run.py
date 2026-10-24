"""CLI: python -m pipeline.backtest.run --asset-class fx --start 2022-04-01 --end 2024-06-01

Runs all three backtest variants (FRD Section 12) for the asset class and prints the
comparison: the walk-forward health-gated strategy, the naive static-EG baseline with no
gating, and equally-weighted buy-and-hold. Needs Phase 2 + Phase 3 already computed for the
requested range (this phase only consumes their output, same as Phase 3 consumed Phase 2's).

Daily returns for the two traded strategies are `daily_pnl / starting_equity` -- a constant
capital base, not a compounding one. This keeps the Sharpe comparison against buy-and-hold
(which IS naturally a compounding % return series) simple and avoids the strategies' own
leverage/sizing choices compounding into the return denominator; it is a deliberate
simplification, stated here rather than left implicit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from pipeline.backtest.benchmarks import compute_buy_and_hold_returns, run_naive_static_baseline
from pipeline.backtest.engine import BacktestResult, run_walk_forward_backtest
from pipeline.backtest.metrics import compute_metrics
from pipeline.backtest.repository import BacktestRepository
from pipeline.config import Settings, load_settings
from pipeline.logging_setup import configure_logging, get_logger

logger = get_logger(__name__)

INTERVAL = "1day"


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _persist_result(repo: BacktestRepository, asset_class: str, variant: str, start, end, cfg_params: dict, starting_equity: float, result: BacktestResult):
    run_id = repo.create_backtest_run(asset_class, variant, start.date(), end.date(), cfg_params, starting_equity)
    for s in result.signals:
        repo.insert_signal(run_id, asset_class, s)
    for t in result.trades:
        repo.insert_trade(run_id, asset_class, t)
    for e in result.equity_curve:
        repo.insert_equity_curve_point(run_id, {"date": e["date"].date() if hasattr(e["date"], "date") else e["date"], **{k: e[k] for k in ("equity", "daily_pnl", "drawdown_pct", "halted")}})

    returns = [e["daily_pnl"] / starting_equity for e in result.equity_curve]
    metrics = compute_metrics(returns)
    repo.finalize_backtest_run(run_id, result.final_equity, metrics.total_return_pct, metrics.annualized_sharpe, metrics.max_drawdown_pct, len(result.trades), result.halted)
    return run_id, metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Phase 4 walk-forward backtest + benchmarks.")
    parser.add_argument("--asset-class", choices=["fx", "equity"], required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD, UTC")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD, UTC")
    args = parser.parse_args()

    settings: Settings = load_settings()
    configure_logging(settings.log_level)
    cfg = settings.backtest
    start, end = _parse_date(args.start), _parse_date(args.end)

    cfg_params = {
        "z_lookback_bars": cfg.z_lookback_bars, "z_entry": cfg.z_entry, "z_exit": cfg.z_exit,
        "transaction_cost_bps": cfg.transaction_cost_bps, "slippage_bps": cfg.slippage_bps,
        "target_daily_vol_per_position": cfg.target_daily_vol_per_position,
        "max_loss_per_position_pct": cfg.max_loss_per_position_pct,
        "portfolio_max_drawdown_pct": cfg.portfolio_max_drawdown_pct,
    }

    repo = BacktestRepository(settings.database_url)
    try:
        pair_keys = repo.list_pair_relationship_keys(args.asset_class, INTERVAL)
        basket_keys = repo.list_basket_relationship_keys(args.asset_class, INTERVAL)
        logger.info("Backtesting %s pairs + %s baskets for %s", len(pair_keys), len(basket_keys), args.asset_class)

        wf_result = run_walk_forward_backtest(repo, args.asset_class, INTERVAL, pair_keys, basket_keys, start, end, cfg)
        _, wf_metrics = _persist_result(repo, args.asset_class, "walk_forward_health_gated", start, end, cfg_params, cfg.starting_equity, wf_result)

        naive_result = run_naive_static_baseline(repo, args.asset_class, INTERVAL, pair_keys, start, end, cfg)
        _, naive_metrics = _persist_result(repo, args.asset_class, "naive_static_eg", start, end, cfg_params, cfg.starting_equity, naive_result)

        if args.asset_class == "fx":
            universe_symbols = settings.fx.pairs
        else:
            universe_symbols = [e["symbol"] for e in settings.equities.universe]
        bh_returns = compute_buy_and_hold_returns(repo, args.asset_class, INTERVAL, universe_symbols, start, end)
        bh_metrics = compute_metrics(bh_returns)
        bh_run_id = repo.create_backtest_run(args.asset_class, "buy_and_hold", start.date(), end.date(), {"symbols": universe_symbols}, cfg.starting_equity)
        repo.finalize_backtest_run(bh_run_id, cfg.starting_equity * (1 + bh_metrics.total_return_pct / 100), bh_metrics.total_return_pct, bh_metrics.annualized_sharpe, bh_metrics.max_drawdown_pct, 0, False)

        print(f"\n{'Variant':<30}{'Return %':>12}{'Sharpe':>10}{'MaxDD %':>10}{'Trades':>8}")
        print(f"{'Walk-forward, health-gated':<30}{wf_metrics.total_return_pct:>12.2f}{wf_metrics.annualized_sharpe:>10.2f}{wf_metrics.max_drawdown_pct:>10.2f}{len(wf_result.trades):>8}")
        print(f"{'Naive static EG, no gating':<30}{naive_metrics.total_return_pct:>12.2f}{naive_metrics.annualized_sharpe:>10.2f}{naive_metrics.max_drawdown_pct:>10.2f}{len(naive_result.trades):>8}")
        print(f"{'Buy-and-hold':<30}{bh_metrics.total_return_pct:>12.2f}{bh_metrics.annualized_sharpe:>10.2f}{bh_metrics.max_drawdown_pct:>10.2f}{'--':>8}")
        print(f"\nWalk-forward portfolio halted during run: {wf_result.halted}")
        print(f"Naive baseline portfolio halted during run: {naive_result.halted}")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
