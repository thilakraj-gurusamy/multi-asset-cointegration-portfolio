"""Low-level HTTP client for Twelve Data's `time_series` endpoint (FX source).

Twelve Data is NOT named in FRD Section 8.1's institutional-grade FX list (Refinitiv/LSEG,
Bloomberg BPIPE, OANDA, Polygon.io). It is used here as the budget-free FX substitute, following
the same transparency principle the FRD applies to the equities substitutes (Alpaca IEX /
Stooq / Yahoo): free tier = 800 requests/day, 8 requests/minute, delayed/EOD-quality data,
"internal, non-display use only" license. See README "Known constraints".
"""
from __future__ import annotations

import time

import requests

from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.logging_setup import get_logger
from pipeline.util.rate_limiter import RateLimiter

logger = get_logger(__name__)

BASE_URL = "https://api.twelvedata.com/time_series"


class TwelveDataClient:
    name = "twelvedata"

    def __init__(
        self,
        api_key: str,
        daily_request_budget: int = 760,
        max_calls_per_minute: int = 7,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 5.0,
        rate_limiter: RateLimiter | None = None,
    ):
        self.api_key = api_key
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limiter = rate_limiter or RateLimiter(
            max_calls_per_minute=max_calls_per_minute, daily_budget=daily_request_budget
        )

    def get_time_series(
        self,
        symbol: str,
        interval: str,
        start_date: str | None = None,
        end_date: str | None = None,
        outputsize: int | None = None,
    ) -> list[dict]:
        params = {
            "symbol": symbol,
            "interval": interval,
            "apikey": self.api_key,
            "format": "JSON",
            "timezone": "UTC",
        }
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        if outputsize:
            params["outputsize"] = outputsize

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self.rate_limiter.acquire()  # may raise RateLimitExceededError (daily cap) -- not retried

            try:
                response = self.session.get(BASE_URL, params=params, timeout=15)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning(
                    "Twelve Data request failed (attempt %s/%s): %s", attempt, self.max_retries, exc
                )
                time.sleep(self.backoff_seconds * attempt)
                continue

            if response.status_code >= 500:
                last_error = FeedDownError(f"Twelve Data returned HTTP {response.status_code}")
                logger.warning(
                    "Twelve Data server error (attempt %s/%s): HTTP %s",
                    attempt,
                    self.max_retries,
                    response.status_code,
                )
                time.sleep(self.backoff_seconds * attempt)
                continue

            try:
                payload = response.json()
            except ValueError as exc:
                raise MalformedPayloadError(f"Twelve Data returned non-JSON response: {exc}") from exc

            if payload.get("status") == "error":
                code = payload.get("code")
                message = payload.get("message", "unknown error")
                if code == 429:
                    raise RateLimitExceededError(f"Twelve Data rate limit: {message}")
                raise MalformedPayloadError(f"Twelve Data error (code={code}): {message}")

            values = payload.get("values")
            if values is None:
                raise MalformedPayloadError(f"Twelve Data response missing 'values' field: {payload}")

            return values

        raise FeedDownError(
            f"Twelve Data unreachable for symbol={symbol} after {self.max_retries} attempts: {last_error}"
        )
