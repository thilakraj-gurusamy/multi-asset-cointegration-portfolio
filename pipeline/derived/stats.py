"""Lightweight derived fields kept alongside raw bars for auditability (FRD Section 8.4).

Deliberately simple: log return + a rolling mean/std of close. This is NOT the cointegration/
half-life/hedge-ratio engine -- that is explicitly Phase 2/3 scope and must not be built here.

Rolling stats need lookback context beyond just the newly-ingested bars, so callers should pass
in `window` extra bars of prior history (fetched from the store) ahead of the new ones; only the
rows for the new bars need to actually be upserted by the caller.
"""
from __future__ import annotations

import math

import pandas as pd

from pipeline.sources.base import Bar

WINDOW = 20


def compute_derived_stats(bars_with_lookback: list[Bar]) -> pd.DataFrame:
    if not bars_with_lookback:
        return pd.DataFrame(columns=["time", "log_return", "rolling_mean_20", "rolling_std_20"])

    sorted_bars = sorted(bars_with_lookback, key=lambda b: b.time)
    df = pd.DataFrame({"time": [b.time for b in sorted_bars], "close": [b.close for b in sorted_bars]})

    prev_close = df["close"].shift(1)
    ratio = df["close"] / prev_close
    df["log_return"] = ratio.apply(lambda x: math.log(x) if pd.notna(x) and x > 0 else None)

    df["rolling_mean_20"] = df["close"].rolling(window=WINDOW, min_periods=WINDOW).mean()
    df["rolling_std_20"] = df["close"].rolling(window=WINDOW, min_periods=WINDOW).std()

    return df[["time", "log_return", "rolling_mean_20", "rolling_std_20"]]
