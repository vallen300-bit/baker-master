"""Layer 0 content-hash dedupe store (S5 — `kbl_layer0_hash_seen`).

Four operations consumed by the Layer 0 evaluator:

    normalize_for_hash(content)       — deterministic 5-step recipe
    content_hash(content)             — sha256 hex of normalized content
    has_seen_recent(conn, hash)       — read within TTL
    insert_hash(conn, hash, …)        — write on PASS only (see §3.6)
    cleanup_expired(conn)             — daily cron callable

Design rules (per B3 Step 0 §3.6 + B2 PR #5 reconciliation):
    - Normalization recipe is deterministic. Two near-identical email
      re-forwards (different sig, different quote-chain depth) must hash
      IDENTICAL. Genuinely-different content must hash differently.
    - Insert happens on PASS, never on DROP. A false-positive drop must
      not silently dedupe future legitimate copies of the same content.
    - Table column names match PR #5 schema exactly (``content_hash``,
      ``first_seen_at``, ``ttl_expires_at``, ``source_signal_id``,
      ``source_kind``). N1 divergence from the Step 0 spec sketch is
      resolved schema-wins.
    - PRIMARY KEY on ``content_hash`` means a race between two concurrent
      inserts of the same hash is caught by PG, not by us. Caller
      treats UniqueViolation as "already seen" (no-op).

See also:
    briefs/_drafts/KBL_B_STEP0_LAYER0_RULES.md §3.6 (hash-store spec)
    migrations/20260418_loop_infrastructure.sql (canonical schema)
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

# Regex for the standard signature / sign-off openings. Truncate the hash
# input at the first match so recurrent "Best regards, Dimitry" / "-- "
# footers do not differ across copies.
_SIG_PATTERNS = re.compile(
    r"\n\s*--\s*\n"                       # RFC-ish `-- \n` delimiter
    r"|\nbest\s+(?:regards|wishes|,)"     # common signoff openings
    r"|\nkind\s+regards"
    r"|\nthanks(?:\s+again)?,",
    re.IGNORECASE,
)

_WHITESPACE_RE = re.compile(r"\s+")

_DEFAULT_TTL_HOURS = 72


def normalize_for_hash(content: str) -> str:
    """Deterministic normalization for the 72h dedupe store.

    Steps (in order — each idempotent):
      1. Drop quoted-reply lines (any line whose first non-whitespace char
         is ``>``). Strips forward-chains and reply-quote noise.
      2. Truncate at the first signature/sign-off marker (stops
         ``Best regards,`` tail + ``\\n-- \\n`` delimiter variants).
      3. Lowercase.
      4. Collapse all consecutive whitespace (incl. newlines) to a
         single space.
      5. Strip leading + trailing whitespace.

    Empty / missing input returns empty string — caller decides whether
    to hash that or short-circuit.
    """
    if not content:
        return ""

    # 1. Drop quoted-reply lines.
    kept_lines = [
        line for line in content.split("\n") if not line.lstrip().startswith(">")
    ]
    text = "\n".join(kept_lines)

    # 2. Truncate at first signature marker.
    m = _SIG_PATTERNS.search(text)
    if m:
        text = text[: m.start()]

    # 3. Lower.
    text = text.lower()

    # 4 + 5. Collapse whitespace + strip.
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def content_hash(content: str) -> str:
    """Return sha256 hex (64 chars) of the normalized content."""
    return hashlib.sha256(normalize_for_hash(content).encode("utf-8")).hexdigest()


# -------------------------- read side --------------------------


def has_seen_recent(conn: Any, content_hash_value: str) -> bool:
    """True when ``content_hash_value`` exists in ``kbl_layer0_hash_seen``
    AND its ``ttl_expires_at`` is still in the future.

    The hot path: one PRIMARY KEY + index lookup, sub-ms on PG. On any DB
    error the caller's connection is rolled back and the exception
    re-raised — Layer 0 evaluator wraps this in a try/except and applies
    S4 soft-fail-CLOSED semantics (treat as not-seen so the signal flows
    through). Keeping rollback here protects transactional sanity
    regardless of caller choice.
    """
    if not content_hash_value:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM kbl_layer0_hash_seen "
                "WHERE content_hash = %s AND ttl_expires_at > now() "
                "LIMIT 1",
                (content_hash_value,),
            )
            return cur.fetchone() is not None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


# -------------------------- write side --------------------------


def insert_hash(
    conn: Any,
    content_hash_value: str,
    source_signal_id: int | None,
    source_kind: str,
    ttl_hours: int = _DEFAULT_TTL_HOURS,
) -> None:
    """INSERT a row into ``kbl_layer0_hash_seen``.

    Idempotent via ``ON CONFLICT (content_hash) DO NOTHING`` — a concurrent
    insert of the same hash (two copies of the same signal arriving within
    the same tick) is harmless.

    Only called on Layer 0 PASS per §3.6. Caller owns the connection;
    commit/rollback stays with the caller's transaction boundary. On DB
    error this function rolls back before re-raising, so the caller's
    connection isn't left aborted for subsequent queries.
    """
    if not content_hash_value:
        raise ValueError("content_hash_value must be non-empty")
    if not source_kind:
        raise ValueError("source_kind must be non-empty")
    if ttl_hours <= 0:
        raise ValueError(f"ttl_hours must be positive (got {ttl_hours!r})")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kbl_layer0_hash_seen "
                "(content_hash, first_seen_at, ttl_expires_at, "
                " source_signal_id, source_kind) "
                "VALUES (%s, now(), now() + (%s || ' hours')::interval, "
                "        %s, %s) "
                "ON CONFLICT (content_hash) DO NOTHING",
                (content_hash_value, str(ttl_hours), source_signal_id, source_kind),
            )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


def cleanup_expired(conn: Any) -> int:
    """Delete rows whose ``ttl_expires_at`` is in the past. Returns count."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM kbl_layer0_hash_seen WHERE ttl_expires_at < now()"
            )
            return cur.rowcount or 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise


# -------------------------- review-queue writer --------------------------
#
# Lives alongside the dedupe writers because both are Step-0 side-effects on
# the signal path. Column names match PR #5 schema exactly (dropped_by_rule,
# signal_excerpt, source_kind) per B2 N2 reconciliation — the B3 Step 0
# spec sketch used older column names (rule_name / excerpt / sampled_at)
# that predate the canonical migration.


_EXCERPT_LIMIT = 500


def kbl_layer0_review_insert(
    conn: Any,
    signal_id: int,
    dropped_by_rule: str,
    signal_excerpt: str,
    source_kind: str,
) -> None:
    """INSERT a sampled drop into ``kbl_layer0_review`` for Director audit.

    Called by ``_process_layer0`` on 1-in-50 drops per S6. Truncates
    ``signal_excerpt`` to 500 chars (§3.5); newlines preserved. Column
    names match PR #5 migration exactly — do not rename to spec-sketch
    names ``rule_name`` / ``excerpt`` / ``sampled_at``.
    """
    if not dropped_by_rule:
        raise ValueError("dropped_by_rule must be non-empty")
    if not source_kind:
        raise ValueError("source_kind must be non-empty")
    excerpt = (signal_excerpt or "")[:_EXCERPT_LIMIT]
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO kbl_layer0_review "
                "(signal_id, dropped_by_rule, signal_excerpt, source_kind) "
                "VALUES (%s, %s, %s, %s)",
                (signal_id, dropped_by_rule, excerpt, source_kind),
            )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
