"""Step 2 — thread/arc resolver (source-dispatched).

Contract per KBL-B §4.3:
    - Reads signal from ``signal_queue`` (``awaiting_resolve`` rows).
    - Dispatches on ``source`` to one of: email / whatsapp / transcript /
      scan resolvers.
    - Writes ``resolved_thread_paths`` as a JSONB array. Empty array is a
      valid state (new-arc / zero-Gold-read per CHANDA Inv 1).
    - Advances state: ``awaiting_resolve`` -> ``resolve_running`` ->
      ``awaiting_extract``. Only unrecoverable errors land in
      ``resolve_failed``; Voyage unreachability is degraded-mode (empty
      paths + WARN log + cost ledger with success=False).
    - Writes one ``kbl_cost_ledger`` row for transcript/scan resolvers
      (Voyage-3 embed). Email/WA: no row — metadata-only, zero cost.

Loop posture:
    - Q1: downstream of Step 1 reads. Does not modify Leg 3 mechanism.
    - Q2: pure wish-service (arc continuity = loop compounding).
    - Inv 1: empty ``resolved_thread_paths`` is valid for brand-new arcs.
    - Inv 9: resolver READS the vault (via embedding helpers) but never
      writes to it. Writes here are PostgreSQL only.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from kbl.exceptions import ResolverError
from kbl.resolvers import CostInfo, ResolveResult

logger = logging.getLogger(__name__)

_STATE_RUNNING = "resolve_running"
_STATE_NEXT = "awaiting_extract"
_STATE_FAILED = "resolve_failed"


# --------------------------- resolver dispatch ---------------------------


def _dispatch(source: str) -> Optional[Callable[..., ResolveResult]]:
    """Lazy imports keep every resolver module optional at import time."""
    if source == "email":
        from kbl.resolvers import email as email_resolver

        return email_resolver.resolve
    if source == "whatsapp":
        from kbl.resolvers import whatsapp as wa_resolver

        return wa_resolver.resolve
    if source == "meeting":
        from kbl.resolvers import transcript as transcript_resolver

        return transcript_resolver.resolve
    if source == "scan":
        from kbl.resolvers import scan as scan_resolver

        return scan_resolver.resolve
    # Unknown source — dispatcher returns None and the caller treats it
    # as new arc (empty paths). Fail-loud would escalate a data-shape
    # problem into a signal-level failure; the §4.3 degraded-mode posture
    # prefers new-arc semantics over blocking the pipeline.
    return None


# ----------------------------- DB helpers -----------------------------


# STEP_CONSUMERS_SIGNAL_CONTENT_SOURCE_FIX_1 (2026-04-21): the bridge
# (``kbl/bridge/alerts_to_signal.py``) writes body text into
# ``payload->>'alert_body'`` — there is no ``raw_content`` column. Each
# entry is a ``(sql_expression, dict_key)`` pair so the SELECT can use a
# COALESCE ladder while the returned dict preserves the legacy
# ``raw_content`` key (downstream resolvers read ``signal["raw_content"]``).
# The COALESCE is a SAFETY NET, not a cover-up: a future producer
# writing to a new canonical column should surface as an alignment
# error, not silently fall back. If you're adding a third body source,
# update the ladder here + update the bridge + update the other 3
# consumers (step 1, 3, 5).
_SIGNAL_SELECT_FIELDS: tuple[tuple[str, str], ...] = (
    ("id", "id"),
    ("source", "source"),
    ("primary_matter", "primary_matter"),
    (
        "COALESCE(payload->>'alert_body', summary, '') AS raw_content",
        "raw_content",
    ),
    ("payload", "payload"),
)


def _fetch_signal(conn: Any, signal_id: int) -> dict[str, Any]:
    col_list = ", ".join(expr for expr, _ in _SIGNAL_SELECT_FIELDS)
    keys = tuple(k for _, k in _SIGNAL_SELECT_FIELDS)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {col_list} FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"signal_queue row not found: id={signal_id}")
    return dict(zip(keys, row))


def _mark_running(conn: Any, signal_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_RUNNING, signal_id),
        )


def _write_result(
    conn: Any,
    signal_id: int,
    paths: tuple[str, ...],
    next_state: str,
) -> None:
    import json

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET "
            "  resolved_thread_paths = %s::jsonb, "
            "  status = %s "
            "WHERE id = %s",
            (json.dumps(list(paths)), next_state, signal_id),
        )


def _write_cost_ledger(
    conn: Any,
    signal_id: int,
    cost: CostInfo,
    latency_ms: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO kbl_cost_ledger "
            "(signal_id, step, model, input_tokens, output_tokens, "
            " latency_ms, cost_usd, success) "
            "VALUES (%s, 'resolve', %s, %s, NULL, %s, %s, %s)",
            (
                signal_id,
                cost.model,
                cost.input_tokens,
                latency_ms,
                cost.cost_usd,
                cost.success,
            ),
        )


# ----------------------------- invariant guard -----------------------------


_WIKI_PREFIX = "wiki/"


def _validate_paths(paths: tuple[str, ...]) -> tuple[str, ...]:
    """Drop non-string / non-vault-relative entries without raising.

    §4.3 invariant: every path is vault-relative and starts with ``wiki/``.
    If a resolver returns anything else (e.g., a DB row had a stale
    absolute path), log + drop rather than fail the signal. Empty list
    is always valid.
    """
    kept: list[str] = []
    for p in paths:
        if not isinstance(p, str) or not p.startswith(_WIKI_PREFIX):
            logger.warning("resolve: dropping non-vault-relative path %r", p)
            continue
        kept.append(p)
    return tuple(kept)


# ----------------------------- public API -----------------------------


def resolve(signal_id: int, conn: Any) -> list[str]:
    """Run Step 2 thread resolution for a single signal.

    Returns:
        Vault-relative path list (may be empty). Also written to
        ``signal_queue.resolved_thread_paths``.

    Raises:
        LookupError: when ``signal_id`` is absent from ``signal_queue``.
        ResolverError: when a resolver itself fails in a way we cannot
            downgrade to new-arc (e.g., DB error bubbled from metadata
            query). The caller marks the signal ``resolve_failed`` via
            the ``state`` column.
    """
    signal = _fetch_signal(conn, signal_id)
    _mark_running(conn, signal_id)

    source = signal.get("source") or ""
    resolver = _dispatch(source)

    # Track the latency for any embedding call; metadata resolvers don't
    # meaningfully benefit from this but we collect uniformly.
    start = time.monotonic()
    if resolver is None:
        result = ResolveResult()
    else:
        try:
            result = resolver(signal, conn)
        except LookupError:
            raise
        except ResolverError:
            _write_result(conn, signal_id, (), _STATE_FAILED)
            raise
        except Exception as e:
            # Any unexpected resolver failure: mark the signal failed +
            # surface the original exception (wrapped) so the pipeline
            # tick logs + alerts on structural bugs rather than quietly
            # downgrading.
            _write_result(conn, signal_id, (), _STATE_FAILED)
            raise ResolverError(f"resolver {source!r} raised: {e}") from e

    latency_ms = int((time.monotonic() - start) * 1000)

    paths = _validate_paths(result.paths)
    _write_result(conn, signal_id, paths, _STATE_NEXT)

    if result.cost_info is not None:
        _write_cost_ledger(conn, signal_id, result.cost_info, latency_ms)

    return list(paths)
