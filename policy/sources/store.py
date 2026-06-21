"""Parameterized-SQL persistence for the source registry + fail-closed external read.

Mirrors the Step-1 store discipline: validate fail-closed before persisting, never
return default-public rows, and route ALL external visibility through the Step-1
policy engine via ``registry.external_projection_for``.

``query_external_visible_sources`` is the read path that, like Step-1's
``query_visible_items``, ALWAYS returns redacted projections for external callers
and FAILS CLOSED (``SourceRegistryUnavailableError``) on any DB problem — never an
unfiltered or default-public payload (AC1/T10).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, List, Mapping, Optional

from policy.audit import AuditSink
from policy.models import Classification, LifecycleState, Org, Principal, Sensitivity
from policy.sources import registry
from policy.sources.models import (
    CollectionStatus,
    ProvenanceClass,
    RegistryChange,
    SourceDomain,
    SourceObjectType,
    SourceRecord,
)

logger = logging.getLogger("policy.sources.store")

ConnFactory = Callable[[], Any]


def _default_conn_factory() -> Any:
    from kbl.db import get_conn

    return get_conn()


class SourceRegistryUnavailableError(RuntimeError):
    """Raised when the registry store cannot be reached. ALWAYS fail closed (T10)."""


def _enum(v: Any) -> Any:
    return getattr(v, "value", v)


def _row_to_record(row: Mapping[str, Any]) -> SourceRecord:
    return SourceRecord(
        source_id=row["source_id"],
        domain=SourceDomain(row["domain"]),
        source_type=row["source_type"],
        object_type=SourceObjectType(row["object_type"]),
        owner_org=Org(row["owner_org"]),
        classification=Classification(row["classification"]),
        lifecycle_state=LifecycleState(row["lifecycle_state"]),
        sensitivity=Sensitivity(row["sensitivity"]) if row.get("sensitivity") else None,
        provenance_class=ProvenanceClass(row["provenance_class"]),
        collection_status=CollectionStatus(row["collection_status"]),
        allowed_orgs=frozenset(Org(o) for o in (row.get("allowed_orgs") or [])),
        allowed_roles=frozenset(row.get("allowed_roles") or []),
        raw_body_available_internal=row["raw_body_available_internal"],
        external_projection_available=row["external_projection_available"],
        redaction_reason=row.get("redaction_reason"),
        provenance_refs=tuple(row.get("provenance_refs") or []),
        policy_object_id=row.get("policy_object_id"),
        name=row.get("name"),
        claim=row.get("claim"),
        confidence=row.get("confidence"),
        freshness=row["freshness"],
        gap_owner=row.get("gap_owner"),
        gap_reason=row.get("gap_reason"),
        gap_next_action=row.get("gap_next_action"),
    )


def save_source(
    rec: SourceRecord, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Upsert a source registry row. Validates fail-closed FIRST (AC1/AC7)."""

    registry.validate_record(rec)  # raises RegistryInvalidError — fail closed
    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO source_registry (
                        source_id, domain, source_type, object_type, owner_org,
                        classification, lifecycle_state, sensitivity, provenance_class,
                        collection_status, allowed_orgs, allowed_roles,
                        raw_body_available_internal, external_projection_available,
                        redaction_reason, provenance_refs, policy_object_id, name,
                        claim, confidence, freshness, gap_owner, gap_reason,
                        gap_next_action, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb,
                            %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s,
                            %s, %s, %s, now())
                    ON CONFLICT (source_id) DO UPDATE SET
                        domain=EXCLUDED.domain, source_type=EXCLUDED.source_type,
                        object_type=EXCLUDED.object_type, owner_org=EXCLUDED.owner_org,
                        classification=EXCLUDED.classification,
                        lifecycle_state=EXCLUDED.lifecycle_state,
                        sensitivity=EXCLUDED.sensitivity,
                        provenance_class=EXCLUDED.provenance_class,
                        collection_status=EXCLUDED.collection_status,
                        allowed_orgs=EXCLUDED.allowed_orgs,
                        allowed_roles=EXCLUDED.allowed_roles,
                        raw_body_available_internal=EXCLUDED.raw_body_available_internal,
                        external_projection_available=EXCLUDED.external_projection_available,
                        redaction_reason=EXCLUDED.redaction_reason,
                        provenance_refs=EXCLUDED.provenance_refs,
                        policy_object_id=EXCLUDED.policy_object_id,
                        name=EXCLUDED.name, claim=EXCLUDED.claim,
                        confidence=EXCLUDED.confidence, freshness=EXCLUDED.freshness,
                        gap_owner=EXCLUDED.gap_owner, gap_reason=EXCLUDED.gap_reason,
                        gap_next_action=EXCLUDED.gap_next_action, updated_at=now()
                    """,
                    (
                        rec.source_id, _enum(rec.domain), rec.source_type,
                        _enum(rec.object_type), _enum(rec.owner_org),
                        _enum(rec.classification), _enum(rec.lifecycle_state),
                        _enum(rec.sensitivity) if rec.sensitivity else None,
                        _enum(rec.provenance_class), _enum(rec.collection_status),
                        json.dumps(sorted(_enum(o) for o in rec.allowed_orgs)),
                        json.dumps(sorted(rec.allowed_roles)),
                        rec.raw_body_available_internal,
                        rec.external_projection_available, rec.redaction_reason,
                        json.dumps(list(rec.provenance_refs)), rec.policy_object_id,
                        rec.name, rec.claim, rec.confidence, rec.freshness,
                        rec.gap_owner, rec.gap_reason, rec.gap_next_action,
                    ),
                )
            conn.commit()
    except registry.RegistryInvalidError:
        raise
    except Exception as exc:  # noqa: BLE001 - fail loud, surface as unavailable
        logger.exception("save_source failed for source_id=%s", rec.source_id)
        raise SourceRegistryUnavailableError(str(exc)) from exc


def load_sources(
    *, domain: Optional[SourceDomain] = None, conn_factory: ConnFactory = _default_conn_factory
) -> List[SourceRecord]:
    """Load registry rows (optionally one domain). Fail closed on DB error."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                if domain is not None:
                    cur.execute("SELECT * FROM source_registry WHERE domain = %s",
                                (_enum(domain),))
                else:
                    cur.execute("SELECT * FROM source_registry")
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        return [_row_to_record(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("load_sources failed — failing closed")
        raise SourceRegistryUnavailableError(str(exc)) from exc


def query_external_visible_sources(
    principal: Principal,
    *,
    conn_factory: ConnFactory = _default_conn_factory,
    sink: Optional[AuditSink] = None,
) -> List[Mapping[str, Any]]:
    """Return ONLY the redacted projections an external principal may see.

    Each row is routed through ``registry.external_projection_for`` (the Step-1
    policy engine). Gap rows, never-external sources, cross-partner classifications,
    and ungranted sources resolve to hidden and are dropped. FAILS CLOSED on any
    DB error — never an unfiltered or default-public payload (T10).
    """

    records = load_sources(conn_factory=conn_factory)  # may raise -> fail closed
    out: List[Mapping[str, Any]] = []
    for rec in records:
        proj = registry.external_projection_for(principal, rec, sink=sink)
        if proj is not None:
            out.append(proj)
    return out


def record_registry_change(
    change: RegistryChange, *, conn_factory: ConnFactory = _default_conn_factory
) -> None:
    """Persist an AC10 change-audit row. Fail closed."""

    try:
        with conn_factory() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO source_registry_audit (
                        source_id, field, prior_value, new_value, actor_org,
                        actor_role, actor_is_ai, rationale, decision_source,
                        increases_external_exposure)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        change.source_id, change.field, change.prior_value,
                        change.new_value, change.actor_org, change.actor_role,
                        change.actor_is_ai, change.rationale, change.decision_source,
                        change.increases_external_exposure,
                    ),
                )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - fail closed
        logger.exception("record_registry_change failed")
        raise SourceRegistryUnavailableError(str(exc)) from exc
