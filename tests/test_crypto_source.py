from datetime import datetime, timezone

import pytest

from pipeline.exceptions import MalformedPayloadError
from pipeline.sources.crypto_source import CryptoDataSource, _parse_kline


def _kline(open_time_ms, o="100", h="110", l="90", c="105", v="1000"):
    return [open_time_ms, o, h, l, c, v, open_time_ms + 3_600_000, "0", 10, "0", "0", "0"]


def test_parse_kline_happy_path():
    bar = _parse_kline(_kline(1_700_000_000_000))
    assert bar.time == datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=timezone.utc)
    assert bar.open == 100.0
    assert bar.volume == 1000.0


def test_parse_kline_wrong_shape_raises():
    with pytest.raises(MalformedPayloadError):
        _parse_kline([1, 2, 3])


def test_parse_kline_non_numeric_raises():
    with pytest.raises(MalformedPayloadError):
        _parse_kline(_kline(1_700_000_000_000, o="not-a-number"))


class FakeBinanceClient:
    name = "binance"

    def __init__(self, pages):
        self.pages = list(pages)  # list of lists-of-klines, returned in order
        self.calls = []

    def get_klines(self, symbol, interval, start_time_ms=None, end_time_ms=None, limit=1000):
        self.calls.append((start_time_ms, end_time_ms, limit))
        return self.pages.pop(0) if self.pages else []


def test_fetch_historical_paginates_when_a_full_page_is_returned():
    # First page is exactly MAX_KLINES_PER_CALL (1000) -> must fetch a second page.
    from pipeline.sources.binance_client import MAX_KLINES_PER_CALL

    page1 = [_kline(1_700_000_000_000 + i * 3_600_000) for i in range(MAX_KLINES_PER_CALL)]
    page2 = [_kline(1_700_000_000_000 + (MAX_KLINES_PER_CALL) * 3_600_000)]
    client = FakeBinanceClient([page1, page2])
    source = CryptoDataSource(client)

    start = datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp((1_700_000_000_000 + (MAX_KLINES_PER_CALL + 5) * 3_600_000) / 1000, tz=timezone.utc)
    bars = source.fetch_historical("BTCUSDT", "1h", start, end)

    assert len(client.calls) == 2
    assert len(bars) == MAX_KLINES_PER_CALL + 1


def test_fetch_historical_stops_when_page_is_short():
    client = FakeBinanceClient([[_kline(1_700_000_000_000)]])  # far fewer than a full page
    source = CryptoDataSource(client)
    start = datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=timezone.utc)
    end = datetime.fromtimestamp(1_800_000_000_000 / 1000, tz=timezone.utc)

    bars = source.fetch_historical("BTCUSDT", "1h", start, end)

    assert len(client.calls) == 1  # no unnecessary second call
    assert len(bars) == 1


def test_fetch_incremental_filters_to_strictly_after_since():
    client = FakeBinanceClient(
        [[_kline(1_700_000_000_000), _kline(1_700_000_000_000 + 3_600_000), _kline(1_700_000_000_000 + 7_200_000)]]
    )
    source = CryptoDataSource(client)
    since = datetime.fromtimestamp(1_700_000_000_000 / 1000, tz=timezone.utc)

    bars = source.fetch_incremental("BTCUSDT", "1h", since)

    assert len(bars) == 2
    assert all(b.time > since for b in bars)
