"""Top-level KBL exception hierarchy.

Individual modules may raise more specific subclasses; callers that want
to catch any KBL pipeline failure can catch ``KblError``.
"""
from __future__ import annotations


class KblError(RuntimeError):
    """Base class for KBL pipeline errors."""


class TriageParseError(KblError):
    """Raised when the Step 1 triage model returns output that cannot be
    parsed into a valid ``TriageResult`` (malformed JSON, missing required
    keys, enum violation)."""


class OllamaUnavailableError(KblError):
    """Raised when Ollama is unreachable or returns a non-2xx after the
    configured retry budget is exhausted. Callers may swap to the
    availability-fallback model per D1 ratification."""
