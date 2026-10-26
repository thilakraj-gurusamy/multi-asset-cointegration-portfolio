from datetime import datetime, timedelta, timezone

from pipeline.config import BacktestConfig, LiquidityConfig
from pipeline.paper_trading.signals import run_paper_signals_for_asset_class
from tests.fakes import FakeBacktestRepository

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _d(i):
    return BASE + timedelta(days=i)


def _flat(value, n=20):
    return [{"time": _d(i), "close": value, "volume": 1000.0} for i in range(n)]


def _a_pattern(n, elevated_from, elevated_value):
    base_vals = [100, 101, 100, 100, 101, 100, 100, 101, 100, 100]
    rows = []
    for i in range(n):
        value = base_vals[i] if i < 10 else elevated_value
        rows.append({"time": _d(i), "close": float(value), "volume": 1000.0})
    return rows


def _cfg(**overrides):
    base = dict(
        starting_equity=100_000.0, z_lookback_bars=3, z_entry=2.0, z_exit=0.5,
        transaction_cost_bps=0.0, slippage_bps=0.0, target_daily_vol_per_position=100_000.0,
        max_loss_per_position_pct=50.0, portfolio_max_drawdown_pct=90.0,
        liquidity=LiquidityConfig(equity_adv_fraction=1.0, fx_max_notional_per_position=1e9),
    )
    base.update(overrides)
    return BacktestConfig(**base)


def _single_window():
    return [{"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]}]


def test_skips_when_no_bars_available_yet():
    repo = FakeBacktestRepository()
    result = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())
    assert result["status"] == "skipped"


def test_opens_a_position_on_first_call_and_persists_it():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(11, 10, 103.0), "B": _flat(5.0, 11)},
    )
    repo.set_latest_bar_date("fx", _d(10))

    result = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())

    assert result["status"] == "success"
    assert result["entries_opened"] == 1
    position = repo.get_open_position("fx", "A,B")
    assert position is not None
    assert position["direction"] == "short"


def test_second_call_same_day_is_a_no_op():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(11, 10, 103.0), "B": _flat(5.0, 11)},
    )
    repo.set_latest_bar_date("fx", _d(10))

    first = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())
    second = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())

    assert first["status"] == "success"
    assert second["status"] == "skipped"
    assert len(repo._paper_equity["fx"]) == 1  # not double-logged


def test_position_closes_on_a_later_day_using_persisted_state():
    windows = [
        {"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]},
    ]
    # Day 10: elevated (103) -> entry. Day 11: back near the in-sample mean -> z-exit.
    a_prices = _a_pattern(12, 10, 103.0)
    a_prices[11]["close"] = 100.333  # ~in-sample mean -> |z| near 0

    repo = FakeBacktestRepository(
        pair_windows={"A,B": windows},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": a_prices, "B": _flat(5.0, 12)},
    )

    repo.set_latest_bar_date("fx", _d(10))
    day1 = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())
    assert day1["entries_opened"] == 1
    assert repo.get_open_position("fx", "A,B") is not None

    repo.set_latest_bar_date("fx", _d(11))
    day2 = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())

    assert day2["trades_closed"] == 1
    assert repo.get_open_position("fx", "A,B") is None
    assert len(repo.paper_trades) == 1
    assert repo.paper_trades[0]["exit_reason"] == "z_exit"


def test_drawdown_halted_state_reloads_across_calls():
    repo = FakeBacktestRepository()
    repo.insert_paper_equity_point(
        "fx", {"date": _d(5).date(), "equity": 50_000.0, "peak_equity": 100_000.0, "daily_pnl": -50_000.0, "drawdown_pct": 50.0, "halted": True},
    )
    repo.set_latest_bar_date("fx", _d(6))
    # No relationships configured -- just confirms the reloaded state persists through to the
    # next equity-curve write (no relationships evaluated, but still writes a point for the
    # new date carrying `halted=True` forward).
    result = run_paper_signals_for_asset_class(repo, "fx", "1day", _cfg())
    assert result["status"] == "success"
    assert result["halted"] is True
