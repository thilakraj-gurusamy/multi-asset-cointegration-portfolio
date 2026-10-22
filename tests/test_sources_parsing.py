from datetime import datetime, timezone

import pytest

from pipeline.exceptions import MalformedPayloadError
from pipeline.sources.equity_source import _parse_record as parse_equity_record
from pipeline.sources.fx_source import _parse_record as parse_fx_record


def test_parse_fx_record_happy_path():
    bar = parse_fx_record({"datetime": "2024-01-01 10:00:00", "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15"})
    assert bar.time == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    assert bar.open == 1.1
    assert bar.volume is None


def test_parse_fx_record_missing_field_raises():
    with pytest.raises(MalformedPayloadError):
        parse_fx_record({"datetime": "2024-01-01 10:00:00", "open": "1.1"})


def test_parse_fx_record_non_numeric_raises():
    with pytest.raises(MalformedPayloadError):
        parse_fx_record({"datetime": "2024-01-01 10:00:00", "open": "oops", "high": "1.2", "low": "1.0", "close": "1.15"})


def test_parse_fx_record_bad_datetime_raises():
    with pytest.raises(MalformedPayloadError):
        parse_fx_record({"datetime": "not-a-date", "open": "1.1", "high": "1.2", "low": "1.0", "close": "1.15"})


def test_parse_equity_record_happy_path():
    bar = parse_equity_record({"t": "2024-01-01T14:00:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 123456})
    assert bar.time == datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
    assert bar.volume == 123456.0


def test_parse_equity_record_missing_field_raises():
    with pytest.raises(MalformedPayloadError):
        parse_equity_record({"t": "2024-01-01T14:00:00Z", "o": 100.0})
