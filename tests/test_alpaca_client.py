import pytest

from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.sources.alpaca_client import AlpacaClient
from pipeline.util.rate_limiter import RateLimiter


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)

    def get(self, url, params=None, headers=None, timeout=None):
        return self._responses.pop(0)


def _client(session):
    rate_limiter = RateLimiter(max_calls_per_minute=1000)
    return AlpacaClient(
        api_key_id="id", api_secret_key="secret", session=session, rate_limiter=rate_limiter,
        max_retries=2, backoff_seconds=0,
    )


def test_get_bars_returns_bars_list():
    session = FakeSession([FakeResponse(200, {"bars": [{"t": "2024-01-01T00:00:00Z"}], "next_page_token": None})])
    client = _client(session)
    bars = client.get_bars("AAPL", "1Hour")
    assert bars == [{"t": "2024-01-01T00:00:00Z"}]


def test_get_bars_follows_pagination():
    session = FakeSession(
        [
            FakeResponse(200, {"bars": [{"t": "A"}], "next_page_token": "abc"}),
            FakeResponse(200, {"bars": [{"t": "B"}], "next_page_token": None}),
        ]
    )
    client = _client(session)
    bars = client.get_bars("AAPL", "1Hour")
    assert bars == [{"t": "A"}, {"t": "B"}]


def test_rate_limit_status_raises():
    session = FakeSession([FakeResponse(429, {"message": "slow down"})])
    client = _client(session)
    with pytest.raises(RateLimitExceededError):
        client.get_bars("AAPL", "1Hour")


def test_server_error_retries_then_raises_feed_down():
    session = FakeSession([FakeResponse(500), FakeResponse(500)])
    client = _client(session)
    with pytest.raises(FeedDownError):
        client.get_bars("AAPL", "1Hour")


def test_unexpected_status_raises_malformed_payload():
    session = FakeSession([FakeResponse(404, {"message": "not found"})])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_bars("NOTREAL", "1Hour")


def test_missing_bars_key_raises_malformed_payload():
    session = FakeSession([FakeResponse(200, {"next_page_token": None})])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_bars("AAPL", "1Hour")
