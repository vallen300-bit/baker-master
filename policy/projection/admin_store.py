"""Persisted projection-admin overlay (Sprint-0 Step 5.1).

The Step-4 store (:mod:`policy.projection.store`) persists projection rows; this
module is the SOURCE OF FINAL STATE for the revoke/refresh kill switch on top of it.

Design (matter-level revoke):
  A revoke/refresh decision is taken by a Brisen human admin against a *source
  evidence item* and applies across EVERY partner audience for that item — a partner
  must never see an item Brisen has pulled, regardless of which audience packet it
  would land in. So the admin decision is persisted ONCE, under the internal
  ``brisen_internal`` projection record (deterministic opaque id), keyed for lookup by
  ``source_evidence_item_id``. The per-audience external packets then read this overlay
  and a revoked/stale source item is ABSENT from every external surface generically
  (no per-surface special-casing) — the same chokepoint serves packet/evidence/audit.

Fail-closed (T11): :func:`load_admin_overlay` raises ``ProjectionStoreUnavailableError``
on any store error (it never returns a partial/empty overlay that could resurrect a
revoked item). External callers translate that into a generic "temporarily
unavailable" empty packet — never a raw fallback, never the last-known partner body.

The persisted state is reused verbatim from the Step-4 schema (AC10/T12): no new
columns — ``projection_state`` + ``revoked_at/by/reason`` + ``updated_at`` already
exist on ``projection_item``. The backend is injectable (:func:`set_backend`) so unit
tests exercise the full state machine without a live database; production uses the
DB-backed default.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional

from policy.projection import store as projection_store
from policy.projection.models import (
    ProjectionAuditLog,
    ProjectionItem,
    ProjectionState,
)

logger = logging.getLogger("policy.projection.admin_store")

# The internal audience under which the matter-level admin decision is persisted.
ADMIN_AUDIENCE_ROLE = "brisen_internal"


@dataclass(frozen=True)
class AdminOverlayState:
    """The persisted admin decision for one source evidence item.

    ``revoked`` is a HARD STOP — once true it overrides everything downstream and is
    never cleared by a refresh (un-revoke is out of scope, a separate Brisen-human
    action). ``stale`` reflects the last refresh's freshness recompute.
    """

    source_evidence_item_id: str
    projection_state: str
    revoked: bool
    stale: bool
    revoked_at: Optional[str] = None
    revoked_by: Optional[str] = None
    revoke_reason: Optional[str] = None
    updated_at: Optional[str] = None


def _state_flags(projection_state: str, revoked_at) -> tuple[bool, bool]:
    revoked = (projection_state == ProjectionState.REVOKED.value) or bool(revoked_at)
    stale = projection_state == ProjectionState.STALE_PROJECTION.value
    return revoked, stale


# --------------------------------------------------------------------------- #
# Backends — DB-backed default (reuses Step-4 store); in-memory for tests.
# --------------------------------------------------------------------------- #
class _DBBackend:
    """Persists/loads the admin overlay via the Step-4 projection store.

    Reuses ``save_projection_item`` / ``record_projection_audit`` /
    ``load_projection_items`` (the brief's named persistence layer). Fails closed:
    load propagates ``ProjectionStoreUnavailableError`` from the store.
    """

    def load(self) -> Dict[str, AdminOverlayState]:
        rows = projection_store.load_projection_items(ADMIN_AUDIENCE_ROLE, limit=500)
        overlay: Dict[str, AdminOverlayState] = {}
        for r in rows:
            src = r.get("source_evidence_item_id")
            if not src:
                continue
            state = r.get("projection_state") or ""
            revoked, stale = _state_flags(state, r.get("revoked_at"))
            updated = r.get("updated_at")
            overlay[src] = AdminOverlayState(
                source_evidence_item_id=src,
                projection_state=state,
                revoked=revoked,
                stale=stale,
                revoked_at=str(r.get("revoked_at")) if r.get("revoked_at") else None,
                revoked_by=r.get("revoked_by"),
                revoke_reason=r.get("revoke_reason"),
                updated_at=str(updated) if updated else None,
            )
        return overlay

    def record(self, item: ProjectionItem, audit: Optional[ProjectionAuditLog]) -> None:
        # Persist the decision row first, THEN the audit. If the item write fails the
        # store raises (fail closed) and no audit is appended for an unapplied action.
        projection_store.save_projection_item(item)
        if audit is not None:
            projection_store.record_projection_audit(audit)


class InMemoryAdminBackend:
    """Deterministic, DB-free backend for unit tests (full state machine, no I/O)."""

    def __init__(self) -> None:
        self.items: Dict[str, ProjectionItem] = {}        # keyed by source_evidence_item_id
        self.audit: List[ProjectionAuditLog] = []
        self.fail = False                                  # flip to simulate store outage

    def load(self) -> Dict[str, AdminOverlayState]:
        if self.fail:
            raise projection_store.ProjectionStoreUnavailableError("in-memory backend forced failure")
        overlay: Dict[str, AdminOverlayState] = {}
        for src, item in self.items.items():
            state = item.projection_state.value
            revoked, stale = _state_flags(state, item.revoked_at)
            overlay[src] = AdminOverlayState(
                source_evidence_item_id=src,
                projection_state=state,
                revoked=revoked,
                stale=stale,
                revoked_at=item.revoked_at,
                revoked_by=item.revoked_by,
                revoke_reason=item.revoke_reason,
                updated_at=item.last_verified_at,
            )
        return overlay

    def record(self, item: ProjectionItem, audit: Optional[ProjectionAuditLog]) -> None:
        if self.fail:
            raise projection_store.ProjectionStoreUnavailableError("in-memory backend forced failure")
        self.items[item.source_evidence_item_id] = item
        if audit is not None:
            self.audit.append(audit)


_BACKEND = _DBBackend()


def set_backend(backend) -> None:
    """Swap the persistence backend (tests inject :class:`InMemoryAdminBackend`)."""
    global _BACKEND
    _BACKEND = backend


def get_backend():
    return _BACKEND


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def load_admin_overlay() -> Dict[str, AdminOverlayState]:
    """Load the persisted admin overlay, keyed by ``source_evidence_item_id``.

    Raises ``ProjectionStoreUnavailableError`` on store error (fail closed) — callers
    on a partner-facing surface MUST translate that into a generic unavailable state,
    never a raw / last-known fallback (T11)."""
    return _BACKEND.load()


def record_admin_action(item: ProjectionItem, audit: Optional[ProjectionAuditLog]) -> None:
    """Persist a revoke/refresh decision row + its audit. Fail closed: a store error
    propagates so the endpoint reports the action as NOT applied."""
    _BACKEND.record(item, audit)
