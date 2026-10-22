"""Data-quality checks (FRD Section 8.4 / 9): gaps and semantically-malformed bars must be
logged and surfaced, never silently dropped or interpolated over.

Raw-payload parsing failures (missing/non-numeric fields) are caught earlier, in the source
modules, as MalformedPayloadError. This module checks *semantic* validity of already-parsed
Bar objects (e.g. high < low) and detects gaps in an otherwise well-formed series.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pipeline.sources.base import Bar


def validate_bar(bar: Bar) -> list[str]:
    """Return a list of human-readable issues; empty list means the bar is valid."""
    issues = []

    for field_name, value in (("open", bar.open), ("high", bar.high), ("low", bar.low), ("close", bar.close)):
        if value is None or value != value:  # NaN check without importing math
            issues.append(f"{field_name} is null/NaN")
        elif value <= 0:
            issues.append(f"{field_name} is non-positive ({value})")

    if not issues:
        if bar.high < bar.low:
            issues.append(f"high ({bar.high}) < low ({bar.low})")
        if not (bar.low <= bar.open <= bar.high):
            issues.append(f"open ({bar.open}) outside [low, high]")
        if not (bar.low <= bar.close <= bar.high):
            issues.append(f"close ({bar.close}) outside [low, high]")

    if bar.volume is not None and bar.volume < 0:
        issues.append(f"volume is negative ({bar.volume})")

    return issues


@dataclass
class GapEvent:
    asset_symbol: str
    interval: str
    gap_start: datetime
    gap_end: datetime
    gap_minutes: float


def detect_gaps(
    bars: list[Bar],
    expected_interval_minutes: float,
    gap_tolerance_minutes: float,
    asset_symbol: str,
    interval: str,
) -> list[GapEvent]:
    """Flag any consecutive pair of bars further apart than `gap_tolerance_minutes`.

    NOTE (documented Phase 1 limitation): this is calendar-naive. It will also flag
    legitimate market-closure gaps (weekends, equities overnight) once the gap exceeds the
    configured tolerance. Making this trading-calendar-aware (e.g. via
    `pandas_market_calendars`) is a deliberate follow-up, not solved here, to keep Phase 1
    scoped to ingestion + basic quality detection rather than full calendar logic.
    """
    gaps: list[GapEvent] = []
    sorted_bars = sorted(bars, key=lambda b: b.time)

    for prev, curr in zip(sorted_bars, sorted_bars[1:]):
        delta_minutes = (curr.time - prev.time).total_seconds() / 60
        if delta_minutes > gap_tolerance_minutes:
            gaps.append(
                GapEvent(
                    asset_symbol=asset_symbol,
                    interval=interval,
                    gap_start=prev.time,
                    gap_end=curr.time,
                    gap_minutes=delta_minutes,
                )
            )

    return gaps
