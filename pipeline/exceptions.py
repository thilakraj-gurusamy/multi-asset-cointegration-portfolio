class FeedDownError(Exception):
    """Raised when a data source is unreachable or returns a repeated server-side failure."""


class MalformedPayloadError(Exception):
    """Raised when a data source returns a response that cannot be parsed into bars."""


class RateLimitExceededError(Exception):
    """Raised when a provider's per-minute or per-day request budget would be exceeded."""


class ConfigError(Exception):
    """Raised for missing/invalid configuration (e.g. a required API key is not set)."""
