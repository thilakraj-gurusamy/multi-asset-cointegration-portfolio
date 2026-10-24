from datetime import datetime, timedelta, timezone

import pipeline.health.monitor as monitor_module
from pipeline.health.monitor import run_health_monitor
from tests.fakes import FakeHealthRepository

BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _w(i, **overrides):
    row = {
        "window_start": BASE + timedelta(days=i * 5),
        "window_end": BASE + timedelta(days=i * 5 + 90),
        "p_value": 0.01,
        "hedge_ratio": 0.5,
        "half_life_days": 20.0,
    }
    row.update(overrides)
    return row


def test_drift_is_none_on_first_window_then_computed_on_second():
    windows = [_w(0, hedge_ratio=0.5), _w(1, hedge_ratio=0.55)]
    repo = FakeHealthRepository(pair_windows={"A,B": windows})
    run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))

    rows = sorted(repo.relationship_health, key=lambda r: r["window_end"])
    assert rows[0]["hedge_ratio_drift_pct"] is None
    assert rows[0]["hedge_ratio_drift_status"] is None
    assert abs(rows[1]["hedge_ratio_drift_pct"] - 10.0) < 1e-6
    assert rows[1]["hedge_ratio_drift_status"] == "warning"


def test_transition_only_logged_on_actual_status_change():
    windows = [
        _w(0, p_value=0.01),       # healthy
        _w(1, p_value=0.02),       # still healthy -- no transition
        _w(2, p_value=0.5),        # now halted -- transition
    ]
    repo = FakeHealthRepository(pair_windows={"A,B": windows})
    summary = run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))

    # First window always logs a transition (previous_status=None -> something).
    assert summary.transitions_logged == 2
    statuses = [t["new_status"] for t in sorted(repo.transitions, key=lambda t: t["window_end"])]
    assert statuses == ["healthy", "halted"]


def test_halted_transition_flags_position_and_fires_alert(monkeypatch):
    sent_alerts = []
    monkeypatch.setattr(
        monitor_module.alerts, "send_alert",
        lambda webhook, event_type, message, details: sent_alerts.append((event_type, message, details)),
    )

    windows = [_w(0, p_value=0.01), _w(1, p_value=0.5)]  # healthy -> halted
    repo = FakeHealthRepository(pair_windows={"A,B": windows})
    run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200), alert_webhook_url="http://example.test")

    assert len(repo.review_flags) == 1
    assert repo.review_flags[0]["relationship_key"] == "A,B"
    halted_alerts = [a for a in sent_alerts if a[0] == "relationship_halted"]
    assert len(halted_alerts) == 1


def test_is_suspended_reflects_latest_status_and_lifts_on_requalify():
    windows = [_w(0, p_value=0.5), _w(1, p_value=0.01)]  # halted -> healthy
    repo = FakeHealthRepository(pair_windows={"A,B": windows})
    run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))

    # Latest window is healthy -> no longer suspended, even though it WAS halted earlier.
    assert repo.is_suspended("fx", "1day", "A,B") is False


def test_relationship_stays_suspended_while_latest_window_is_halted():
    windows = [_w(0, p_value=0.01), _w(1, p_value=0.5)]  # healthy -> halted
    repo = FakeHealthRepository(pair_windows={"A,B": windows})
    run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))
    assert repo.is_suspended("fx", "1day", "A,B") is True


def test_failed_relationship_does_not_stop_others(monkeypatch):
    sent_alerts = []
    monkeypatch.setattr(
        monitor_module.alerts, "send_alert",
        lambda webhook, event_type, message, details: sent_alerts.append((event_type, message, details)),
    )

    good_windows = [_w(0)]
    broken_windows = [{"window_start": BASE, "window_end": BASE + timedelta(days=90)}]  # missing required keys

    repo = FakeHealthRepository(pair_windows={"GOOD,PAIR": good_windows, "BROKEN,PAIR": broken_windows})
    summary = run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))

    assert summary.failed_relationships == 1
    assert summary.relationships_processed == 1  # the good one still completed
    good_results = [r for r in repo.relationship_health if r["relationship_key"] == "GOOD,PAIR"]
    assert len(good_results) == 1
    failure_alerts = [a for a in sent_alerts if a[0] == "health_check_failed"]
    assert len(failure_alerts) == 1


def _basket_w(i, **overrides):
    row = {
        "window_start": BASE + timedelta(days=i * 5),
        "window_end": BASE + timedelta(days=i * 5 + 90),
        "trace_stat": 50.0,
        "crit_90": 10.0,
        "crit_95": 15.0,
        "crit_99": 20.0,
        "cointegration_rank": 1,
        "cointegrating_vectors": [[1.0, -0.5, -0.5]],
        "half_life_days": 20.0,
    }
    row.update(overrides)
    return row


def test_basket_rank_zero_is_pinned_not_significant():
    windows = [_basket_w(0, cointegration_rank=0, cointegrating_vectors=[])]
    repo = FakeHealthRepository(basket_windows={"A,B,C": windows})
    run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))

    row = repo.relationship_health[0]
    assert row["p_value_is_proxy"] is True
    assert row["p_value_status"] == "halted"
    assert row["hedge_ratio_or_vector"] == []


def test_basket_rank_ge_1_uses_pseudo_p_value_and_primary_vector():
    windows = [_basket_w(0, trace_stat=50.0)]  # well above crit_99=20 -> very significant
    repo = FakeHealthRepository(basket_windows={"A,B,C": windows})
    run_health_monitor(repo, "fx", "1day", BASE, BASE + timedelta(days=200))

    row = repo.relationship_health[0]
    assert row["p_value_is_proxy"] is True
    assert row["p_value_status"] == "healthy"
    assert row["hedge_ratio_or_vector"] == [1.0, -0.5, -0.5]
