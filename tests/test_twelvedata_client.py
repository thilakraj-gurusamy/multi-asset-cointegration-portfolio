import pytest

from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.sources.twelvedata_client import TwelveDataClient
from pipeline.util.rate_limiter import RateLimiter


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise_on_json = raise_on_json
        self.text = str(payload)

    def json(self):
        if self._raise_on_json:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def _client(session, **kwargs):
    rate_limiter = RateLimiter(max_calls_per_minute=1000)  # effectively unlimited for these tests
    return TwelveDataClient(api_key="k", session=session, rate_limiter=rate_limiter, max_retries=2, backoff_seconds=0, **kwargs)


def test_successful_response_returns_values():
    session = FakeSession([FakeResponse(200, {"status": "ok", "values": [{"datetime": "2024-01-01 00:00:00"}]})])
    client = _client(session)
    values = client.get_time_series("EUR/USD", "1h")
    assert values == [{"datetime": "2024-01-01 00:00:00"}]


def test_rate_limit_error_raises_rate_limit_exceeded():
    session = FakeSession([FakeResponse(200, {"status": "error", "code": 429, "message": "too many requests"})])
    client = _client(session)
    with pytest.raises(RateLimitExceededError):
        client.get_time_series("EUR/USD", "1h")


def test_generic_error_status_raises_malformed_payload():
    session = FakeSession([FakeResponse(200, {"status": "error", "code": 400, "message": "bad symbol"})])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_time_series("NOT/REAL", "1h")


def test_missing_values_key_raises_malformed_payload():
    session = FakeSession([FakeResponse(200, {"status": "ok"})])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_time_series("EUR/USD", "1h")


def test_non_json_response_raises_malformed_payload():
    session = FakeSession([FakeResponse(200, raise_on_json=True)])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_time_series("EUR/USD", "1h")


def test_server_error_retries_then_raises_feed_down():
    session = FakeSession([FakeResponse(503), FakeResponse(503)])
    client = _client(session)
    with pytest.raises(FeedDownError):
        client.get_time_series("EUR/USD", "1h")
    assert session.calls == 2


def test_server_error_then_success_recovers():
    session = FakeSession([FakeResponse(503), FakeResponse(200, {"status": "ok", "values": []})])
    client = _client(session)
    values = client.get_time_series("EUR/USD", "1h")
    assert values == []
