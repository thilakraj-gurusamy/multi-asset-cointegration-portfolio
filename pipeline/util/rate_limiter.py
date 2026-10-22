from __future__ import annotations

import time
from datetime import datetime, timezone

from pipeline.exceptions import RateLimitExceededError


class RateLimiter:
    """Sliding-window per-minute throttle, with an optional hard daily cap.

    Blocks (sleeps) to stay within the per-minute limit. Raises RateLimitExceededError
    instead of sleeping/blocking once the daily cap would be exceeded -- a daily cap is a
    budget decision, not a transient condition to wait out.
    """

    def __init__(self, max_calls_per_minute: int, daily_budget: int | None = None, clock=time.monotonic):
        self.max_calls_per_minute = max_calls_per_minute
        self.daily_budget = daily_budget
        self._clock = clock
        self._call_times: list[float] = []
        self._day: str | None = None
        self._calls_today = 0

    def _reset_day_if_needed(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._day != today:
            self._day = today
            self._calls_today = 0

    def acquire(self) -> None:
        self._reset_day_if_needed()

        if self.daily_budget is not None and self._calls_today >= self.daily_budget:
            raise RateLimitExceededError(
                f"Daily request budget of {self.daily_budget} exhausted for this provider."
            )

        now = self._clock()
        window_start = now - 60
        self._call_times = [t for t in self._call_times if t > window_start]

        if len(self._call_times) >= self.max_calls_per_minute:
            sleep_for = 60 - (now - self._call_times[0])
            if sleep_for > 0:
                time.sleep(sleep_for)

        self._call_times.append(self._clock())
        self._calls_today += 1
