import pytest

from pipeline.exceptions import FeedDownError, MalformedPayloadError, RateLimitExceededError
from pipeline.sources.binance_client import BinanceClient
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
    rate_limiter = RateLimiter(max_calls_per_minute=1000)
    return BinanceClient(session=session, rate_limiter=rate_limiter, max_retries=2, backoff_seconds=0, **kwargs)


def test_successful_response_returns_klines():
    session = FakeSession([FakeResponse(200, [[1700000000000, "1", "2", "0.5", "1.5", "100"]])])
    client = _client(session)
    klines = client.get_klines("BTCUSDT", "1h")
    assert klines == [[1700000000000, "1", "2", "0.5", "1.5", "100"]]


def test_rate_limit_status_raises():
    session = FakeSession([FakeResponse(429, "too many requests")])
    client = _client(session)
    with pytest.raises(RateLimitExceededError):
        client.get_klines("BTCUSDT", "1h")


def test_binance_418_banned_status_raises_as_rate_limit():
    # Binance's documented "IP auto-banned" status for repeated 429s -- treated the same way.
    session = FakeSession([FakeResponse(418, "banned")])
    client = _client(session)
    with pytest.raises(RateLimitExceededError):
        client.get_klines("BTCUSDT", "1h")


def test_non_list_payload_raises_malformed():
    session = FakeSession([FakeResponse(200, {"code": -1121, "msg": "Invalid symbol."})])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_klines("NOTREAL", "1h")


def test_non_json_response_raises_malformed():
    session = FakeSession([FakeResponse(200, raise_on_json=True)])
    client = _client(session)
    with pytest.raises(MalformedPayloadError):
        client.get_klines("BTCUSDT", "1h")


def test_server_error_retries_then_raises_feed_down():
    session = FakeSession([FakeResponse(503), FakeResponse(503)])
    client = _client(session)
    with pytest.raises(FeedDownError):
        client.get_klines("BTCUSDT", "1h")
    assert session.calls == 2


def test_server_error_then_success_recovers():
    session = FakeSession([FakeResponse(503), FakeResponse(200, [])])
    client = _client(session)
    klines = client.get_klines("BTCUSDT", "1h")
    assert klines == []
