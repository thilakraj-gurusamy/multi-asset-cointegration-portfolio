from __future__ import annotations

from datetime import datetime, timezone

from pipeline.exceptions import MalformedPayloadError
from pipeline.sources.alpaca_client import AlpacaClient
from pipeline.sources.base import Bar, DataSource

_REQUIRED_KEYS = ("t", "o", "h", "l", "c")


def _parse_record(record: dict) -> Bar:
    missing = [k for k in _REQUIRED_KEYS if k not in record]
    if missing:
        raise MalformedPayloadError(f"Equity bar missing required field(s) {missing}: {record}")

    try:
        dt = datetime.strptime(record["t"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise MalformedPayloadError(f"Unparseable equity bar timestamp {record['t']!r}") from exc

    try:
        return Bar(
            time=dt,
            open=float(record["o"]),
            high=float(record["h"]),
            low=float(record["l"]),
            close=float(record["c"]),
            volume=float(record["v"]) if record.get("v") is not None else None,
        )
    except (TypeError, ValueError) as exc:
        raise MalformedPayloadError(f"Non-numeric OHLC in equity bar: {record}") from exc


class EquityDataSource(DataSource):
    name = "alpaca_iex"

    def __init__(self, client: AlpacaClient):
        self.client = client

    def fetch_historical(self, ticker: str, interval: str, start: datetime, end: datetime) -> list[Bar]:
        records = self.client.get_bars(
            symbol=ticker,
            timeframe=interval,
            start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        bars = [_parse_record(r) for r in records]
        bars.sort(key=lambda b: b.time)
        return bars

    def fetch_incremental(self, ticker: str, interval: str, since: datetime) -> list[Bar]:
        now = datetime.now(timezone.utc)
        records = self.client.get_bars(
            symbol=ticker,
            timeframe=interval,
            start=since.strftime("%Y-%m-%dT%H:%M:%SZ"),
            end=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        bars = [_parse_record(r) for r in records]
        bars.sort(key=lambda b: b.time)
        return [b for b in bars if b.time > since]
