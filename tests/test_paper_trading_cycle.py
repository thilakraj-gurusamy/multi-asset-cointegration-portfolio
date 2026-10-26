from datetime import datetime, timezone

import pipeline.paper_trading.cycle as cycle_module
from pipeline.config import load_settings
from tests.fakes import FakeBacktestRepository


class _Summary:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _fake_settings():
    return load_settings(require_api_keys=False)


def test_one_failing_ingest_step_does_not_stop_the_others(monkeypatch):
    sent_alerts = []
    monkeypatch.setattr(
        cycle_module.alerts, "send_alert",
        lambda webhook, event_type, message, details: sent_alerts.append((event_type, message)),
    )

    def fake_run_incremental_cycle(settings, repo, source, asset_class, interval):
        if asset_class == "crypto":
            raise RuntimeError("Binance unreachable")
        return 5

    monkeypatch.setattr(cycle_module, "run_incremental_cycle", fake_run_incremental_cycle)
    monkeypatch.setattr(
        cycle_module, "run_rolling_cointegration",
        lambda **kwargs: _Summary(windows_processed=3, adf_exclusions=0, engle_granger_pairs_tested=0, johansen_tests_run=0, disagreements_found=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_health_monitor",
        lambda **kwargs: _Summary(relationships_processed=1, windows_processed=3, transitions_logged=0, halted_transitions=0, failed_relationships=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_paper_signals_for_asset_class",
        lambda repo, asset_class, interval, cfg: {"status": "success", "entries_opened": 0, "trades_closed": 0},
    )

    backtest_repo = FakeBacktestRepository()
    settings = _fake_settings()
    started_at = datetime.now(timezone.utc)
    cycle_id = backtest_repo.start_cycle_log(started_at)

    result = cycle_module.run_cycle(
        settings, cycle_id, started_at,
        ingest_repo=object(), coint_repo=object(), health_repo=object(), backtest_repo=backtest_repo,
        build_source=lambda settings, asset_class: object(),
    )

    assert result["status"] == "partial"
    assert result["steps"]["ingest_crypto"]["status"] == "failed"
    assert result["steps"]["ingest_fx"]["status"] == "success"
    assert result["steps"]["ingest_equity"]["status"] == "success"
    # cointegration/health/paper-signal steps still ran for every asset class despite the
    # ingest failure for crypto specifically
    assert result["steps"]["cointegration_crypto"]["status"] == "success"
    assert result["steps"]["health_crypto"]["status"] == "success"

    failure_alerts = [a for a in sent_alerts if a[0] == "feed_downtime"]
    assert len(failure_alerts) == 1

    assert backtest_repo.cycle_logs[cycle_id]["status"] == "partial"


def test_all_steps_succeeding_gives_overall_success(monkeypatch):
    monkeypatch.setattr(cycle_module, "run_incremental_cycle", lambda *a, **k: 1)
    monkeypatch.setattr(
        cycle_module, "run_rolling_cointegration",
        lambda **kwargs: _Summary(windows_processed=1, adf_exclusions=0, engle_granger_pairs_tested=0, johansen_tests_run=0, disagreements_found=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_health_monitor",
        lambda **kwargs: _Summary(relationships_processed=1, windows_processed=1, transitions_logged=0, halted_transitions=0, failed_relationships=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_paper_signals_for_asset_class",
        lambda repo, asset_class, interval, cfg: {"status": "success"},
    )

    backtest_repo = FakeBacktestRepository()
    settings = _fake_settings()
    started_at = datetime.now(timezone.utc)
    cycle_id = backtest_repo.start_cycle_log(started_at)

    result = cycle_module.run_cycle(
        settings, cycle_id, started_at,
        ingest_repo=object(), coint_repo=object(), health_repo=object(), backtest_repo=backtest_repo,
        build_source=lambda settings, asset_class: object(),
    )

    assert result["status"] == "success"


def test_skipped_paper_signal_steps_count_as_success_not_partial(monkeypatch):
    # "skipped" is the idempotency guard's correct no-op (already processed today) -- it must
    # not make an otherwise-clean cycle look like something went wrong.
    monkeypatch.setattr(cycle_module, "run_incremental_cycle", lambda *a, **k: 1)
    monkeypatch.setattr(
        cycle_module, "run_rolling_cointegration",
        lambda **kwargs: _Summary(windows_processed=1, adf_exclusions=0, engle_granger_pairs_tested=0, johansen_tests_run=0, disagreements_found=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_health_monitor",
        lambda **kwargs: _Summary(relationships_processed=1, windows_processed=1, transitions_logged=0, halted_transitions=0, failed_relationships=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_paper_signals_for_asset_class",
        lambda repo, asset_class, interval, cfg: {"status": "skipped", "reason": "already processed"},
    )

    backtest_repo = FakeBacktestRepository()
    settings = _fake_settings()
    started_at = datetime.now(timezone.utc)
    cycle_id = backtest_repo.start_cycle_log(started_at)

    result = cycle_module.run_cycle(
        settings, cycle_id, started_at,
        ingest_repo=object(), coint_repo=object(), health_repo=object(), backtest_repo=backtest_repo,
        build_source=lambda settings, asset_class: object(),
    )

    assert result["status"] == "success"


def test_crypto_never_reaches_the_paper_signal_step(monkeypatch):
    seen_asset_classes = []
    monkeypatch.setattr(cycle_module, "run_incremental_cycle", lambda *a, **k: 1)
    monkeypatch.setattr(
        cycle_module, "run_rolling_cointegration",
        lambda **kwargs: _Summary(windows_processed=1, adf_exclusions=0, engle_granger_pairs_tested=0, johansen_tests_run=0, disagreements_found=0),
    )
    monkeypatch.setattr(
        cycle_module, "run_health_monitor",
        lambda **kwargs: _Summary(relationships_processed=1, windows_processed=1, transitions_logged=0, halted_transitions=0, failed_relationships=0),
    )

    def fake_paper_signals(repo, asset_class, interval, cfg):
        seen_asset_classes.append(asset_class)
        return {"status": "success"}

    monkeypatch.setattr(cycle_module, "run_paper_signals_for_asset_class", fake_paper_signals)

    backtest_repo = FakeBacktestRepository()
    settings = _fake_settings()
    started_at = datetime.now(timezone.utc)
    cycle_id = backtest_repo.start_cycle_log(started_at)

    cycle_module.run_cycle(
        settings, cycle_id, started_at,
        ingest_repo=object(), coint_repo=object(), health_repo=object(), backtest_repo=backtest_repo,
        build_source=lambda settings, asset_class: object(),
    )

    assert "crypto" not in seen_asset_classes
    assert set(seen_asset_classes) == {"fx", "equity"}
