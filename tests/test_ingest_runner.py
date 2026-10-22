from datetime import datetime, timedelta, timezone

from pipeline.exceptions import FeedDownError
from pipeline.ingest_runner import run_ingestion
from pipeline.sources.base import Bar
from tests.fakes import FakeDataSource, InMemoryRepository


def _bar(hour: int, close: float = 1.1) -> Bar:
    return Bar(
        time=datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour),
        open=close, high=close + 0.01, low=close - 0.01, close=close, volume=None,
    )


def test_happy_path_inserts_all_bars_and_marks_success():
    repo = InMemoryRepository()
    source = FakeDataSource(incremental={"EUR/USD": [_bar(0), _bar(1), _bar(2)]})

    rows = run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    assert rows == 3
    assert repo.quality_events == []
    run = next(iter(repo.runs.values()))
    assert run["status"] == "success"
    assert run["rows_ingested"] == 3


def test_feed_down_for_one_symbol_is_logged_and_other_symbol_still_processed():
    repo = InMemoryRepository()
    source = FakeDataSource(
        incremental={"EUR/USD": FeedDownError("boom"), "GBP/USD": [_bar(0)]}
    )

    rows = run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}, {"symbol": "GBP/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    assert rows == 1  # GBP/USD's bar still landed
    feed_down_events = [e for e in repo.quality_events if e["event_type"] == "feed_downtime"]
    assert len(feed_down_events) == 1
    run = next(iter(repo.runs.values()))
    assert run["status"] == "partial"  # not "failed" -- one symbol succeeded


def test_malformed_bar_is_excluded_and_logged_not_silently_dropped():
    repo = InMemoryRepository()
    bad_bar = Bar(time=datetime(2024, 1, 1, 5, tzinfo=timezone.utc), open=1.0, high=0.5, low=0.9, close=0.8, volume=None)
    source = FakeDataSource(incremental={"EUR/USD": [_bar(0), bad_bar, _bar(1)]})

    rows = run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    assert rows == 2  # only the two well-formed bars
    malformed_events = [e for e in repo.quality_events if e["event_type"] == "malformed_payload"]
    assert len(malformed_events) == 1
    assert "high" in str(malformed_events[0]["details"]["issues"])
    run = next(iter(repo.runs.values()))
    assert run["status"] == "partial"


def test_gap_beyond_tolerance_is_logged_but_bars_still_inserted():
    repo = InMemoryRepository()
    source = FakeDataSource(incremental={"EUR/USD": [_bar(0), _bar(10)]})  # 10h jump

    rows = run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    assert rows == 2
    gap_events = [e for e in repo.quality_events if e["event_type"] == "data_gap"]
    assert len(gap_events) == 1


def test_stale_watermark_to_first_new_bar_is_detected_as_gap():
    """If the pipeline was down/stale for a long stretch, the next incremental pull's first
    bar can be far ahead of the stored watermark -- detect_gaps alone can't see that since it
    only compares bars *within* the newly-fetched batch. This is the boundary check added
    after a live Alpaca/Twelve Data run showed a ~2-year backfill-to-live jump going unlogged.
    """
    repo = InMemoryRepository()
    source = FakeDataSource(incremental={"EUR/USD": [_bar(0)]})
    asset_id = repo.upsert_asset("EUR/USD", "fx", None, "fake", "EUR/USD")
    stale_watermark = _bar(0).time - timedelta(days=400)
    repo.set_watermark(asset_id, "1hour", stale_watermark)

    run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    gap_events = [e for e in repo.quality_events if e["event_type"] == "data_gap"]
    assert len(gap_events) == 1
    assert gap_events[0]["details"]["gap_minutes"] > 400 * 24 * 60 - 100


def test_watermark_advances_to_last_bar_time():
    repo = InMemoryRepository()
    source = FakeDataSource(incremental={"EUR/USD": [_bar(0), _bar(1)]})

    run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    asset_id = repo.assets[("EUR/USD", "fx")]
    assert repo.get_watermark(asset_id, "1hour") == _bar(1).time


def test_derived_stats_computed_once_window_is_full():
    repo = InMemoryRepository()
    bars = [_bar(h, close=1.0 + h * 0.001) for h in range(25)]
    source = FakeDataSource(incremental={"EUR/USD": bars})

    run_ingestion(
        repo=repo, data_source=source, asset_class="fx", interval_name="1hour", provider_interval="1h",
        universe_entries=[{"symbol": "EUR/USD"}], run_type="incremental",
        expected_interval_minutes=60, gap_tolerance_minutes=90,
    )

    asset_id = repo.assets[("EUR/USD", "fx")]
    rows = repo.derived_rows[(asset_id, "1hour")]
    assert len(rows) == 25
    populated_means = [r for r in rows if r["rolling_mean_20"] is not None]
    assert len(populated_means) == 6  # bars index 19..24 (0-indexed), 20-bar window
