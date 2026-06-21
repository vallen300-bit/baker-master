"""AI Hotel Lab — policy + evidence-lifecycle core (AI_HOTEL_LAB_POLICY_CORE_1).

The foundational permission + evidence-lifecycle engine for the AI Hotel Lab, a
permissioned cooperation cockpit for Brisen + NVIDIA + Mandarin Oriental (MOHG) +
the Santa Clara venue owner.

This package is the SINGLE server-side control point. Every future surface —
search, read, digest, partner projection, audit, export — MUST call
``policy.engine.evaluate`` before constructing any response. UI/client filters are
never accepted as the control (AC2). Default-deny external + fail-closed are
load-bearing (AC9 / T10).

Brisen owns this engine, the ontology, promotion rules, citations, and the
partner-safe object model. Vendors may later host backbone/projection/UI but never
own this layer (Ownership invariant, brief Context Contract).

Public surface:

* ``models``   — enums, dataclasses (Principal, EvidenceItem, PolicyDecision), reason codes.
* ``engine``   — ``evaluate`` decision function + partner projection / audit redaction.
* ``lifecycle``— evidence state machine (raw_signal → … → action_linked) + promotion gate.
* ``store``    — parameterized-SQL persistence + fail-closed visible-item query.
"""

from __future__ import annotations

from policy import engine, lifecycle, models  # noqa: F401

__all__ = ["models", "engine", "lifecycle"]
