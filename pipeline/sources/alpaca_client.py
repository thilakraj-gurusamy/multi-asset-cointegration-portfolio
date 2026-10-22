"""Low-level HTTP client for Alpaca's Market Data API v2 bars endpoint (equities source).

This IS the budget-free equities substitute the FRD names explicitly in Section 8.1:
"Alpaca IEX feed (US equities only, single-venue, not consolidated tape)". Free-tier limits
(per Alpaca's docs at time of writing): IEX-only real-time/historical coverage, ~15-minute
historical delay, 200 API calls/minute. `feed=iex` must be passed explicitly -- requesting the
default/SIP feed on a free account returns empty results.
"""
from __future__ import annotations

import time

import requests

from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.logging_setup import get_logger
from pipeline.util.rate_limiter import RateLimiter

logger = get_logger(__name__)


class AlpacaClient:
    name = "alpaca_iex"

    def __init__(
        self,
        api_key_id: str,
        api_secret_key: str,
        base_url: str = "https://data.alpaca.markets",
        feed: str = "iex",
        max_calls_per_minute: int = 150,
        session: requests.Session | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 3.0,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.feed = feed
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.rate_limiter = rate_limiter or RateLimiter(max_calls_per_minute=max_calls_per_minute)
        self._headers = {
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": api_secret_key,
        }

    def get_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int = 10000,
    ) -> list[dict]:
        url = f"{self.base_url}/v2/stocks/{symbol}/bars"
        params = {"timeframe": timeframe, "feed": self.feed, "limit": limit}
        if start:
            params["start"] = start
        if end:
            params["end"] = end

        all_bars: list[dict] = []
        page_token: str | None = None

        while True:
            if page_token:
                params["page_token"] = page_token

            payload = self._get(url, params)
            bars = payload.get("bars")
            if bars is None:
                raise MalformedPayloadError(f"Alpaca response missing 'bars' field: {payload}")
            all_bars.extend(bars)

            page_token = payload.get("next_page_token")
            if not page_token:
                break

        return all_bars

    def _get(self, url: str, params: dict) -> dict:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self.rate_limiter.acquire()

            try:
                response = self.session.get(url, params=params, headers=self._headers, timeout=15)
            except requests.RequestException as exc:
                last_error = exc
                logger.warning("Alpaca request failed (attempt %s/%s): %s", attempt, self.max_retries, exc)
                time.sleep(self.backoff_seconds * attempt)
                continue

            if response.status_code == 429:
                raise RateLimitExceededError(f"Alpaca rate limit hit: {response.text}")

            if response.status_code >= 500:
                last_error = FeedDownError(f"Alpaca returned HTTP {response.status_code}")
                time.sleep(self.backoff_seconds * attempt)
                continue

            if response.status_code != 200:
                raise MalformedPayloadError(
                    f"Alpaca returned HTTP {response.status_code}: {response.text}"
                )

            try:
                return response.json()
            except ValueError as exc:
                raise MalformedPayloadError(f"Alpaca returned non-JSON response: {exc}") from exc

        raise FeedDownError(f"Alpaca unreachable after {self.max_retries} attempts: {last_error}")
