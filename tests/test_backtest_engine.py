from datetime import datetime, timedelta, timezone

from pipeline.backtest.engine import run_walk_forward_backtest
from pipeline.config import BacktestConfig, LiquidityConfig
from tests.fakes import FakeBacktestRepository

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _d(i):
    return BASE + timedelta(days=i)


def _flat(symbol, value, n=20):
    return [{"time": _d(i), "close": value, "volume": 1000.0} for i in range(n)]


def _a_pattern(n=20, elevated_from=10, elevated_value=103.0):
    """days 0-9: 100,101,100,100,101,100,100,101,100,100 (mean/std fixed for the lookback=3
    tail at days 7,8,9); from `elevated_from` onward, held at `elevated_value`."""
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


def _single_window(legs=("A", "B")):
    return [{"window_start": _d(0), "window_end": _d(9), "legs": list(legs), "weights": [1.0, 0.0]}]


def _signals_for(result, key, date=None):
    rows = [s for s in result.signals if s["relationship_key"] == key]
    if date is not None:
        rows = [s for s in rows if s["date"] == date]
    return rows


def test_no_trade_when_relationship_is_in_warning():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "warning"}},
        prices={"A": _a_pattern(), "B": _flat("B", 5.0)},
    )
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), _cfg())

    assert result.trades == []
    day10 = _signals_for(result, "A,B", _d(10))
    assert day10[0]["action"] == "suppressed_warning"


def test_entry_and_exit_with_costs_deducted_from_net_pnl():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(elevated_from=10, elevated_value=103.0), "B": _flat("B", 5.0)},
    )
    cfg = _cfg(transaction_cost_bps=10.0, slippage_bps=5.0)
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), cfg)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["direction"] == "short"  # spread elevated above mean -> bet it falls
    expected_net = trade["gross_pnl"] - trade["transaction_cost"] - trade["slippage_cost"]
    assert abs(trade["net_pnl"] - expected_net) < 1e-9
    assert trade["transaction_cost"] > 0 and trade["slippage_cost"] > 0


def test_vol_targeting_sizes_inversely_to_spread_volatility_when_uncapped():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(), "B": _flat("B", 5.0)},
    )
    # Generous leverage/liquidity so vol-targeting alone determines size.
    cfg = _cfg(target_daily_vol_per_position=100.0, max_loss_per_position_pct=1000.0)
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), cfg)

    trade = result.trades[0]
    # in-sample diffs over days 0-9: [1,-1,0,1,-1,0,1,-1,0] -> std = 0.8165
    expected_units = 100.0 / 0.816496580927726
    assert abs(trade["position_units"] - expected_units) < 1e-3
    assert trade["sizing_detail"]["vol_target_units"] == trade["position_units"]


def test_leverage_cap_overrides_vol_target_when_tighter():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(), "B": _flat("B", 5.0)},
    )
    # target_vol would want ~122 units, but max_loss_pct is tiny -> leverage cap must bind.
    cfg = _cfg(target_daily_vol_per_position=100.0, max_loss_per_position_pct=0.01)
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), cfg)

    trade = result.trades[0]
    # max_loss_dollars = 100_000 * 0.01/100 = 10; worst_case_move over in-sample diffs = 1.0
    assert abs(trade["position_units"] - 10.0) < 1e-6
    assert trade["sizing_detail"]["leverage_cap_units"] < trade["sizing_detail"]["vol_target_units"]


def test_fx_liquidity_cap_binds_when_set_tight():
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(), "B": _flat("B", 5.0)},
    )
    cfg = _cfg(
        target_daily_vol_per_position=100_000.0, max_loss_per_position_pct=1000.0,
        liquidity=LiquidityConfig(equity_adv_fraction=1.0, fx_max_notional_per_position=50.0),
    )
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), cfg)

    trade = result.trades[0]
    # entry day price (day10) = 103; weight on A = 1.0 -> unit_notional = 103
    assert abs(trade["position_units"] - (50.0 / 103.0)) < 1e-6
    assert trade["sizing_detail"]["liquidity_cap_units"] < trade["sizing_detail"]["vol_target_units"]


def test_health_halted_stop_closes_position_even_with_favorable_z():
    windows = [
        {"window_start": _d(0), "window_end": _d(9), "legs": ["A", "B"], "weights": [1.0, 0.0]},
        {"window_start": _d(5), "window_end": _d(14), "legs": ["A", "B"], "weights": [1.0, 0.0]},
    ]
    # A stays elevated (103) all the way through day19 -- z never reverts, so only the
    # health-halted stop (not a z-exit) can close the position.
    a_prices = []
    base_vals = [100, 101, 100, 100, 101, 100, 100, 101, 100, 100]
    for i in range(20):
        a_prices.append({"time": _d(i), "close": float(base_vals[i] if i < 10 else 103.0), "volume": 1000.0})

    repo = FakeBacktestRepository(
        pair_windows={"A,B": windows},
        health={"A,B": {_d(9): "healthy", _d(14): "halted"}},
        prices={"A": a_prices, "B": _flat("B", 5.0)},
    )
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), _cfg())

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade["exit_reason"] == "health_halted_stop"
    assert trade["exit_date"] == _d(15)  # first day of the halted segment


def test_portfolio_drawdown_halt_blocks_a_later_entry_on_a_different_relationship():
    # Relationship A,B: enters short on day10, then a large adverse move on day11 blows
    # through the (deliberately tiny) drawdown limit.
    a_prices = _a_pattern(elevated_from=10, elevated_value=103.0)
    for row in a_prices:
        if row["time"] == _d(11):
            row["close"] = 110.0  # adverse jump the day after entry

    # Relationship C,D: identical in-sample shape, but stays near its mean through day11 so
    # it has NOT entered yet, then crosses the entry threshold on day12 -- one day AFTER
    # A,B's breach is already reflected in drawdown.halted.
    c_prices = _a_pattern(elevated_from=10, elevated_value=100.0)  # no entry on day10/11
    for row in c_prices:
        if row["time"] == _d(12):
            row["close"] = 103.0  # now it would cross, if the portfolio weren't halted

    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window(("A", "B")), "C,D": _single_window(("C", "D"))},
        health={"A,B": {_d(9): "healthy"}, "C,D": {_d(9): "healthy"}},
        prices={"A": a_prices, "B": _flat("B", 5.0), "C": c_prices, "D": _flat("D", 5.0)},
    )
    cfg = _cfg(target_daily_vol_per_position=100_000.0, max_loss_per_position_pct=50.0, portfolio_max_drawdown_pct=1.0)
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B", "C,D"], [], _d(0), _d(19), cfg)

    assert result.halted is True
    cd_day12 = _signals_for(result, "C,D", _d(12))
    assert cd_day12[0]["action"] == "no_action"
    assert all(t["relationship_key"] != "C,D" for t in result.trades)


def test_still_open_positions_are_closed_at_end_of_backtest():
    # A stays elevated through the last date with no health change and no z-reversion, so
    # the only way the position closes is the end-of-backtest sweep.
    repo = FakeBacktestRepository(
        pair_windows={"A,B": _single_window()},
        health={"A,B": {_d(9): "healthy"}},
        prices={"A": _a_pattern(elevated_from=10, elevated_value=103.0), "B": _flat("B", 5.0)},
    )
    result = run_walk_forward_backtest(repo, "fx", "1day", ["A,B"], [], _d(0), _d(19), _cfg())

    assert len(result.trades) == 1
    assert result.trades[0]["exit_reason"] == "end_of_backtest"
    assert result.trades[0]["exit_date"] == _d(19)
