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


class VoyageUnavailableError(KblError):
    """Raised when the Voyage embedding API is unreachable (5xx / timeout
    / connection refused). Step 2 transcript + scan resolvers catch this
    and downgrade to new-arc semantics (empty ``resolved_thread_paths``)
    rather than failing the signal — see KBL-B §4.3 degraded-mode contract."""


class ResolverError(KblError):
    """Raised by a Step 2 resolver on unrecoverable errors (malformed
    payload shape the resolver cannot make sense of, etc.). Soft failures
    — Voyage unreachable, no matches — do NOT raise; they return empty
    path lists and the dispatcher advances the signal as a new arc."""


class ExtractParseError(KblError):
    """Raised when the Step 3 extract model returns top-level JSON that
    cannot be parsed (malformed JSON, non-object root). Missing sub-keys
    and sub-field hallucinations are NOT parse errors — the parser handles
    them by filling empty arrays and dropping bad entries per §7 policy.

    The Step 3 pipeline retries once on this error; the second failure
    writes an empty-entities stub and advances the signal to continue the
    pipeline (§7 error matrix, row 1)."""


class ClassifyError(KblError):
    """Raised by the Step 4 deterministic classifier on an unexpected
    precondition — principally the §4.5 "unreachable" edge where
    ``triage_score < KBL_PIPELINE_TRIAGE_THRESHOLD``. Step 1 is supposed
    to route that case to ``routed_inbox`` before Step 4 ever claims the
    signal; hitting it here means a pipeline invariant has drifted, so
    Step 4 halts the signal (status → ``classify_failed``) rather than
    silently guessing a decision."""


class AnthropicUnavailableError(KblError):
    """Raised when the Anthropic API is unreachable or returns a retryable
    transport failure (HTTP 5xx, 429 rate limit, connection timeout).
    Step 5 ``synthesize()`` catches this and advances the R3 retry ladder
    (§8 of KBL-B brief); after the budget is exhausted the signal is
    routed to ``opus_failed`` for pipeline_tick to inbox-route per §7."""


class OpusRequestError(KblError):
    """Raised when the Anthropic API returns a 4xx user error (malformed
    request, invalid model, auth) — distinct from ``AnthropicUnavailableError``
    in that retrying the same prompt CANNOT recover. Step 5 bypasses the R3
    retry ladder on this error and goes straight to ``opus_failed``."""


class FinalizationError(KblError):
    """Raised by Step 6 ``finalize()`` when the Opus draft cannot be
    validated into a canonical Silver document — Pydantic validation
    failure, status-provenance gate mismatch (§3.7), target_vault_path
    regex violation (R20), or a malformed ``opus_draft_markdown``
    frontmatter/body split.

    On first raise the signal flips to ``opus_failed`` and Step 5's
    R3 retry ladder fires (per KBL-B §4.7 + B3 spec §5). After 3
    exhausted Opus retries Step 6 routes the signal to
    ``finalize_failed`` terminal."""


class CommitError(KblError):
    """Raised by Step 7 ``commit()`` when the vault write/commit/push
    pipeline cannot complete — filesystem write failure, git commit
    failure, git push retry exhaustion, Inv 4 author=director collision
    on target path, or unrecoverable state.

    Terminal: signal flips to ``commit_failed``. Operator investigates
    (local vault may or may not have partial state depending on failure
    class; cleanup policy documented in :mod:`kbl.steps.step7_commit`)."""


class VaultLockTimeoutError(CommitError):
    """Raised when Step 7 fails to acquire the vault flock within
    ``BAKER_VAULT_FLOCK_TIMEOUT_SECONDS`` (default 60s). Subclass of
    :class:`CommitError` — pipeline_tick treats it identically to any
    other commit failure. Usually indicates another vault writer is
    stuck; operator should investigate the holder."""
