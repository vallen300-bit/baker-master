"""Parameterized-SQL persistence for the search/routing layer (Step 3).

Mirrors the Step-1/Step-2 store discipline: parameterized SQL only, every DB call
wrapped, and ``except`` fails CLOSED (raises ``SearchStoreUnavailableError``) — it
NEVER returns unfiltered rows, raw bodies, or default-public payloads (T10).

Six logging/record tables (codex-arch #3679):

* ``search_query_log``        — query, principal/role, mode, filters, count, ts
* ``search_result_audit``     — what was returned to whom (projected vs raw + reason)
* ``raw_signal_inbox``        — the amber raw-signal record (16 fields)
* ``routing_suggestions``     — proposed target + reason + method + confidence
* ``routing_overrides``       — actor/prior/new/rationale (audited)
* ``zero_result_gaps``        — zero-result queries as source_gap candidates

This module records; it does not decide visibility. Visibility is the Step-1
engine's job (see :mod:`policy.search.runner`).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from policy.search.models import (
    RawSignal,
    RoutingOverride,
    RoutingSuggestion,
    SearchMode,
    SearchResultSet,
)

logger = logging.getLogger("policy.search.store")

ConnFactory = Callable[[], Any]


def _default_conn_factory() -> Any:
    from kbl.db import get_conn

    return get_conn()


class SearchStoreUnavailableError(RuntimeError):
    """Raised when the search store cannot be reached. ALWAYS fail closed (T10)."""


def _enum(v: Any) -> Any:
    return getattr(v, "value", v)


def log_search_query(
    principal_org: str,
    principal_role: str,
    is_external: bool,
    result_set: SearchResultSet,
    *,
    filters: Optional[dict[str, Any]] = None,
    conn_factory: ConnFactory = _default_conn_factory,
) -> None:
    """Append a ``search_query_log`` row. Fail closed on DB error."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO search_query_log (
                        principal_org, principal_role, is_external, mode, filters,
                        result_count, zero_result)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        principal_org,
                        principal_role,
                        is_external,
                        _enum(result_set.mode),
                        json.dumps(filters or {}),
                        result_set.result_count,
                        result_set.is_zero_result,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("log_search_query failed — failing closed")
        raise SearchStoreUnavailableError(str(exc)) from exc


def record_result_audit(
    principal_org: str,
    principal_role: str,
    result_ref: str,
    projected: bool,
    policy_reason_code: str,
    route_target: str,
    *,
    conn_factory: ConnFactory = _default_conn_factory,
) -> None:
    """Append a ``search_result_audit`` row (what was returned to whom). Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO search_result_audit (
                        principal_org, principal_role, result_ref, projected,
                        policy_reason_code, route_target)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (principal_org, principal_role, result_ref, projected,
                     policy_reason_code, route_target),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_result_audit failed")
        raise SearchStoreUnavailableError(str(exc)) from exc


def save_raw_signal_row(
    signal: RawSignal, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Upsert an amber signal into ``raw_signal_inbox`` (all 16 fields). Fail closed.

    Refuses any non-raw lifecycle state at the persistence boundary too — the only
    legitimate way to a higher state is the Step-1 lifecycle gate (AC7)."""

    from policy.models import LifecycleState

    if signal.lifecycle_state is not LifecycleState.RAW_SIGNAL:
        raise ValueError(
            f"raw_signal_inbox only stores raw_signal rows; got "
            f"{signal.lifecycle_state.value} for {signal.signal_id}"
        )
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO raw_signal_inbox (
                        signal_id, source_id, source_domain, object_type,
                        raw_summary_internal, projected_summary_external,
                        proposed_route_target, route_reason, confidence,
                        lifecycle_state, classification, allowed_orgs, allowed_roles,
                        owner, reviewer, policy_object_id, freshness, observed_at,
                        evidence_needed_to_confirm, duplicate_of, related_signal_ids,
                        audit_trail, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                            %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                            %s::jsonb, now())
                    ON CONFLICT (signal_id) DO UPDATE SET
                        proposed_route_target = EXCLUDED.proposed_route_target,
                        route_reason          = EXCLUDED.route_reason,
                        confidence            = EXCLUDED.confidence,
                        reviewer              = EXCLUDED.reviewer,
                        duplicate_of          = EXCLUDED.duplicate_of,
                        related_signal_ids    = EXCLUDED.related_signal_ids,
                        audit_trail           = EXCLUDED.audit_trail,
                        updated_at            = now()
                    """,
                    (
                        signal.signal_id, signal.source_id,
                        _enum(signal.source_domain), _enum(signal.object_type),
                        signal.raw_summary_internal, signal.projected_summary_external,
                        _enum(signal.proposed_route_target), signal.route_reason,
                        signal.confidence, _enum(signal.lifecycle_state),
                        _enum(signal.classification),
                        json.dumps(sorted(_enum(o) for o in signal.allowed_orgs)),
                        json.dumps(sorted(signal.allowed_roles)),
                        signal.owner, signal.reviewer, signal.policy_object_id,
                        signal.freshness, signal.observed_at,
                        signal.evidence_needed_to_confirm, signal.duplicate_of,
                        json.dumps(list(signal.related_signal_ids)),
                        json.dumps(list(signal.audit_trail)),
                    ),
                )
            conn.commit()
    except SearchStoreUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("save_raw_signal_row failed for signal_id=%s", signal.signal_id)
        raise SearchStoreUnavailableError(str(exc)) from exc


def record_routing_suggestion(
    signal_id: Optional[str],
    source_id: str,
    suggestion: RoutingSuggestion,
    *,
    conn_factory: ConnFactory = _default_conn_factory,
) -> None:
    """Append a ``routing_suggestions`` row. Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO routing_suggestions (
                        signal_id, source_id, route_target, route_reason, method,
                        confidence, rule_no, secondary_targets)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        signal_id, source_id, _enum(suggestion.route_target),
                        suggestion.route_reason, _enum(suggestion.method),
                        suggestion.confidence, suggestion.rule_no,
                        json.dumps([t.value for t in suggestion.secondary_targets]),
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_routing_suggestion failed")
        raise SearchStoreUnavailableError(str(exc)) from exc


def record_routing_override(
    override: RoutingOverride, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Append a ``routing_overrides`` audit row (AC5). Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO routing_overrides (
                        signal_id, prior_target, new_target, actor_org, actor_role,
                        actor_is_ai, rationale)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        override.signal_id, _enum(override.prior_target),
                        _enum(override.new_target), override.actor_org,
                        override.actor_role, override.actor_is_ai, override.rationale,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_routing_override failed")
        raise SearchStoreUnavailableError(str(exc)) from exc


def record_zero_result_gap(
    principal_org: str,
    principal_role: str,
    query: str,
    mode: SearchMode,
    result_set: SearchResultSet,
    *,
    conn_factory: ConnFactory = _default_conn_factory,
) -> None:
    """Append a ``zero_result_gaps`` row (done rubric #7). Fail closed.

    Logs the searcher's OWN query as a source-gap candidate. It never records or
    reveals what (if anything) was hidden by policy — only that the visible result
    set was empty for this principal."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO zero_result_gaps (
                        principal_org, principal_role, query, mode, route_target,
                        reason)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        principal_org, principal_role, query, _enum(mode),
                        _enum(result_set.zero_result_route),
                        result_set.zero_result_reason,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_zero_result_gap failed")
        raise SearchStoreUnavailableError(str(exc)) from exc
