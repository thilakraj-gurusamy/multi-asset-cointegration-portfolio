from __future__ import annotations

from datetime import datetime, timezone

from pipeline.exceptions import MalformedPayloadError
from pipeline.sources.base import Bar, DataSource
from pipeline.sources.binance_client import MAX_KLINES_PER_CALL, BinanceClient

_EXPECTED_FIELDS = 12  # Binance's documented kline array shape


def _parse_kline(record: list) -> Bar:
    if not isinstance(record, list) or len(record) < _EXPECTED_FIELDS:
        raise MalformedPayloadError(f"Crypto kline has unexpected shape: {record}")

    try:
        open_time_ms = record[0]
        dt = datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc)
        return Bar(
            time=dt,
            open=float(record[1]),
            high=float(record[2]),
            low=float(record[3]),
            close=float(record[4]),
            volume=float(record[5]),
        )
    except (TypeError, ValueError, IndexError) as exc:
        raise MalformedPayloadError(f"Unparseable crypto kline: {record}") from exc


class CryptoDataSource(DataSource):
    name = "binance"

    def __init__(self, client: BinanceClient):
        self.client = client

    def fetch_historical(self, ticker: str, interval: str, start: datetime, end: datetime) -> list[Bar]:
        start_ms = int(start.timestamp() * 1000)
        end_ms = int(end.timestamp() * 1000)

        all_bars: list[Bar] = []
        cursor_ms = start_ms
        while cursor_ms < end_ms:
            records = self.client.get_klines(ticker, interval, start_time_ms=cursor_ms, end_time_ms=end_ms, limit=MAX_KLINES_PER_CALL)
            if not records:
                break
            bars = [_parse_kline(r) for r in records]
            all_bars.extend(bars)

            last_open_time_ms = records[-1][0]
            next_cursor_ms = last_open_time_ms + 1
            if next_cursor_ms <= cursor_ms or len(records) < MAX_KLINES_PER_CALL:
                break
            cursor_ms = next_cursor_ms

        all_bars.sort(key=lambda b: b.time)
        return [b for b in all_bars if start <= b.time <= end]

    def fetch_incremental(self, ticker: str, interval: str, since: datetime) -> list[Bar]:
        records = self.client.get_klines(ticker, interval, limit=50)
        bars = [_parse_kline(r) for r in records]
        bars.sort(key=lambda b: b.time)
        return [b for b in bars if b.time > since]
