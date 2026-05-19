"""Mock anthropic SDK for director-facing-filter Phase 2 tests.

Only loaded into the hook subprocess via PYTHONPATH prepend by the pytest
harness; never reaches production. The real anthropic SDK (installed via
deploy script's `pip install --user anthropic`) is shadowed by this module
during tests so call_validator hits a predictable mock instead of the live
API.

Behavior is controlled by env vars set by the harness per fixture:
  MOCK_BEHAVIOR    — "success" (default) | "timeout" | "connection" |
                     "ratelimit" | "status4xx" | "status5xx"
  MOCK_VERDICT_JSON — raw response text the mock returns when behavior=success
                      (may be JSON, JSON-wrapped-in-fences, or non-JSON to
                      exercise the malformed-verdict degradation path).
"""
import os


class APITimeoutError(Exception):
    """Mirror of anthropic.APITimeoutError."""


class APIConnectionError(Exception):
    """Mirror of anthropic.APIConnectionError."""


class RateLimitError(Exception):
    """Mirror of anthropic.RateLimitError."""


class APIStatusError(Exception):
    """Mirror of anthropic.APIStatusError."""

    def __init__(self, message="", status_code=500):
        super().__init__(message)
        self.status_code = status_code


class _ContentBlock:
    def __init__(self, text):
        self.text = text


class _Response:
    def __init__(self, text):
        self.content = [_ContentBlock(text)]


class _Messages:
    def create(self, **kwargs):
        behavior = os.environ.get("MOCK_BEHAVIOR", "success")
        if behavior == "timeout":
            raise APITimeoutError("mocked APITimeoutError")
        if behavior == "connection":
            raise APIConnectionError("mocked APIConnectionError")
        if behavior == "ratelimit":
            raise RateLimitError("mocked RateLimitError")
        if behavior == "status5xx":
            raise APIStatusError("mocked 5xx", status_code=503)
        if behavior == "status4xx":
            raise APIStatusError("mocked 4xx", status_code=400)
        verdict = os.environ.get(
            "MOCK_VERDICT_JSON",
            '{"decision":"pass","reason":"mock default"}',
        )
        return _Response(verdict)


class Anthropic:
    def __init__(self, api_key=None, timeout=None):
        self.api_key = api_key
        self.timeout = timeout
        self.messages = _Messages()
