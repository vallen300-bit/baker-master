"""Audit sinks for the policy core (AC9 — fail-loud logging of every event).

The engine + lifecycle are pure: they compute decisions and emit ``AuditEvent``s
to a *sink*. Decoupling the sink from the logic keeps AC1–AC10 unit-testable with
no database, while still guaranteeing "every deny/promotion/export/projection
writes audit or structured log" (AC9).

Sinks:

* ``LoggingAuditSink``  — default. Structured ``logger`` line; never raises.
* ``ListAuditSink``     — in-memory collector for tests (assert audit rows).
* ``policy.store.DbAuditSink`` — writes ``policy_audit_log`` rows.

A sink that fails MUST NOT widen access: by the time a sink is called the
allow/deny decision is already made and returned to the caller. A DB-sink write
failure is logged, not raised, so an audit-store outage can never flip a deny to
an allow (defends T10 — fallback-open via the audit path).
"""

from __future__ import annotations

import logging
from typing import List, Protocol

from policy.models import AuditEvent

logger = logging.getLogger("policy.audit")


class AuditSink(Protocol):
    def write(self, event: AuditEvent) -> None:  # pragma: no cover - protocol
        ...


class LoggingAuditSink:
    """Default sink — emit a structured log line. Never raises (AC9 fail-loud
    but non-fatal: logging must not itself become a denial-of-service)."""

    def write(self, event: AuditEvent) -> None:
        try:
            logger.info(
                "policy.audit event_type=%s allow=%s reason=%s org=%s role=%s "
                "action=%s object_id=%s object_type=%s detail=%s",
                event.event_type,
                event.allow,
                event.reason_code,
                event.principal_org,
                event.principal_role,
                event.action,
                event.object_id,
                event.object_type,
                dict(event.detail),
            )
        except Exception:  # noqa: BLE001 - logging must never break the caller
            logger.exception("policy.audit: logging sink failed")


class ListAuditSink:
    """In-memory sink for tests. Records every event in ``.events``."""

    def __init__(self) -> None:
        self.events: List[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)


_DEFAULT_SINK: AuditSink = LoggingAuditSink()


def default_sink() -> AuditSink:
    """Process-wide default sink (structured logging)."""

    return _DEFAULT_SINK
