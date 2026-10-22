import itertools

import pytest

from pipeline.exceptions import RateLimitExceededError
from pipeline.util.rate_limiter import RateLimiter


def test_allows_calls_up_to_per_minute_limit(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    clock = itertools.count(0.0, 1.0).__next__
    limiter = RateLimiter(max_calls_per_minute=3, clock=clock)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()  # should not need to sleep within this window
    assert sleep_calls == []


def test_daily_budget_raises_once_exhausted():
    limiter = RateLimiter(max_calls_per_minute=100, daily_budget=2)
    limiter.acquire()
    limiter.acquire()
    with pytest.raises(RateLimitExceededError):
        limiter.acquire()


def test_sleeps_when_per_minute_limit_exceeded(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    times = iter([0.0, 0.0, 10.0, 10.0])
    limiter = RateLimiter(max_calls_per_minute=1, clock=lambda: next(times))

    limiter.acquire()  # call_times = [0.0]
    limiter.acquire()  # now=10.0, window_start=-50, still 1 call in window -> must sleep
    assert sleep_calls, "expected a sleep once the per-minute limit was hit"
