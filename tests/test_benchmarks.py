from datetime import datetime, timedelta, timezone

import numpy as np

from pipeline.backtest.benchmarks import compute_buy_and_hold_returns, run_naive_static_baseline
from pipeline.config import BacktestConfig, LiquidityConfig
from tests.fakes import FakeBacktestRepository

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _d(i):
    return BASE + timedelta(days=i)


def _price_rows(prices_by_day: dict[int, float], volume: float = 1000.0):
    return [{"time": _d(i), "close": p, "volume": volume} for i, p in prices_by_day.items()]


def _cfg(**overrides):
    base = dict(
        starting_equity=100_000.0, z_lookback_bars=3, z_entry=2.0, z_exit=0.5,
        transaction_cost_bps=0.0, slippage_bps=0.0, target_daily_vol_per_position=100.0,
        max_loss_per_position_pct=50.0, portfolio_max_drawdown_pct=90.0,
        liquidity=LiquidityConfig(equity_adv_fraction=1.0, fx_max_notional_per_position=10_000_000.0),
    )
    base.update(overrides)
    return BacktestConfig(**base)


def test_buy_and_hold_equal_weighted_return_matches_manual_calc():
    repo = FakeBacktestRepository(
        prices={
            "A": _price_rows({0: 100.0, 1: 110.0}),  # +10%
            "B": _price_rows({0: 50.0, 1: 45.0}),     # -10%
        }
    )
    returns = compute_buy_and_hold_returns(repo, "fx", "1day", ["A", "B"], _d(0), _d(1))
    # equal-weighted +10%/-10% nets to ~0% on day 1
    assert len(returns) == 1
    assert abs(returns[0]) < 1e-9


def test_naive_baseline_uses_only_the_first_window_and_forces_healthy():
    days = range(0, 20)
    prices = {
        "A": _price_rows({i: 10.0 + i * 0.1 for i in days}),
        "B": _price_rows({i: 5.0 for i in days}),
    }
    windows = [
        {"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]},
        {"window_start": _d(10), "window_end": _d(19), "legs": ["A", "B"], "weights": [1.0, -5.0]},  # must be IGNORED
    ]
    repo = FakeBacktestRepository(
        pair_windows={"A,B": windows},
        health={"A,B": {_d(9): "healthy", _d(19): "halted"}},  # second window's health must be ignored too
        prices=prices,
    )
    cfg = _cfg()
    result = run_naive_static_baseline(repo, "fx", "1day", ["A,B"], _d(0), _d(19), cfg)

    assert result.signals  # produced something
    assert all(s["health_status"] == "healthy" for s in result.signals)
    assert all(s["weights"] == [1.0, 0.0] for s in result.signals)  # window1's weights, never window2's
