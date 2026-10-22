from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Bar:
    time: datetime  # must be timezone-aware (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


class DataSource(ABC):
    """Common interface for both the FX (Twelve Data) and equity (Alpaca) sources.

    Historical backfill and scheduled incremental pulls are both required by FRD Section 8.1/8.4;
    this interface forces every source to implement both explicitly rather than treating
    "incremental" as an afterthought.
    """

    name: str

    @abstractmethod
    def fetch_historical(self, ticker: str, interval: str, start: datetime, end: datetime) -> list[Bar]:
        """Return bars for [start, end], inclusive, for backfill."""

    @abstractmethod
    def fetch_incremental(self, ticker: str, interval: str, since: datetime) -> list[Bar]:
        """Return bars strictly after `since`, for a scheduled incremental pull."""
