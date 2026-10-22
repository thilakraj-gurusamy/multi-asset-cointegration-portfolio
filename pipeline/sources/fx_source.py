from __future__ import annotations

from datetime import datetime, timezone

from pipeline.exceptions import MalformedPayloadError
from pipeline.sources.base import Bar, DataSource
from pipeline.sources.twelvedata_client import TwelveDataClient

_REQUIRED_KEYS = ("datetime", "open", "high", "low", "close")


def _parse_record(record: dict) -> Bar:
    missing = [k for k in _REQUIRED_KEYS if k not in record]
    if missing:
        raise MalformedPayloadError(f"FX record missing required field(s) {missing}: {record}")

    try:
        dt = datetime.strptime(record["datetime"], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            dt = datetime.strptime(record["datetime"], "%Y-%m-%d")
        except ValueError as exc:
            raise MalformedPayloadError(f"Unparseable FX datetime {record['datetime']!r}") from exc
    dt = dt.replace(tzinfo=timezone.utc)

    try:
        return Bar(
            time=dt,
            open=float(record["open"]),
            high=float(record["high"]),
            low=float(record["low"]),
            close=float(record["close"]),
            volume=None,  # FX has no consolidated volume
        )
    except (TypeError, ValueError) as exc:
        raise MalformedPayloadError(f"Non-numeric OHLC in FX record: {record}") from exc


class FxDataSource(DataSource):
    name = "twelvedata"

    def __init__(self, client: TwelveDataClient):
        self.client = client

    def fetch_historical(self, ticker: str, interval: str, start: datetime, end: datetime) -> list[Bar]:
        values = self.client.get_time_series(
            symbol=ticker,
            interval=interval,
            start_date=start.strftime("%Y-%m-%d %H:%M:%S"),
            end_date=end.strftime("%Y-%m-%d %H:%M:%S"),
            outputsize=5000,
        )
        bars = [_parse_record(v) for v in values]
        bars.sort(key=lambda b: b.time)
        return [b for b in bars if start <= b.time <= end]

    def fetch_incremental(self, ticker: str, interval: str, since: datetime) -> list[Bar]:
        values = self.client.get_time_series(symbol=ticker, interval=interval, outputsize=50)
        bars = [_parse_record(v) for v in values]
        bars.sort(key=lambda b: b.time)
        return [b for b in bars if b.time > since]
