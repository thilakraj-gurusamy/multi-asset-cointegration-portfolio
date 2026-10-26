"""Low-level HTTP client for Binance's public market-data REST API (crypto source, FRD
Section 8.1). Unlike Twelve Data (FX) and Alpaca (equities), this needs no API key, no
account, and no signup -- public spot market klines are a genuinely free, unauthenticated
endpoint. There is no budget-free-substitute disclosure needed here because Binance IS one of
the FRD's own named crypto sources (Section 8.1: "Binance, Coinbase, or an aggregator such as
CoinGecko/CoinAPI"), used at full fidelity, not a stand-in for something else.

Binance's published weight-based rate limit (1200 weight/minute on the public endpoints) is far
more generous than Twelve Data's FX budget, so no daily-budget throttle is needed here --
only an ordinary per-minute pace limiter, consistent with the other clients' shape.
"""
from __future__ import annotations

import time

import requests

from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.logging_setup import get_logger
from pipeline.util.rate_limiter import RateLimiter

logger = get_logger(__name__)

BASE_URL = "https://api.binance.com/api/v3/klines"
MAX_KLINES_PER_CALL = 1000


class BinanceClient:
    name = "binance"

    def __init__(
        self,
        max_calls_per_minute: int = 300,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 3.0,
        rate_limiter: RateLimiter | None = None,
    ):
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limiter = rate_limiter or RateLimiter(max_calls_per_minute=max_calls_per_minute)

    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = MAX_KLINES_PER_CALL,
    ) -> list[list]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_time_ms is not None:
            params["startTime"] = start_time_ms
        if end_time_ms is not None:
            params["endTime"] = end_time_ms

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self.rate_limiter.acquire()

            try:
                response = self.session.get(BASE_URL, params=params, timeout=15)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("Binance request failed (attempt %s/%s): %s", attempt, self.max_retries, exc)
                time.sleep(self.backoff_seconds * attempt)
                continue

            if response.status_code == 429 or response.status_code == 418:
                raise RateLimitExceededError(f"Binance rate limit hit (HTTP {response.status_code}): {response.text}")

            if response.status_code >= 500:
                last_error = FeedDownError(f"Binance returned HTTP {response.status_code}")
                time.sleep(self.backoff_seconds * attempt)
                continue

            if response.status_code != 200:
                raise MalformedPayloadError(f"Binance returned HTTP {response.status_code}: {response.text}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise MalformedPayloadError(f"Binance returned non-JSON response: {exc}") from exc

            if not isinstance(payload, list):
                raise MalformedPayloadError(f"Binance klines response was not a list: {payload}")

            return payload

        raise FeedDownError(f"Binance unreachable for symbol={symbol} after {self.max_retries} attempts: {last_error}")
