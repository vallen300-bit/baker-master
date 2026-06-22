"""AI Hotel Lab — search + routing layer (AI_HOTEL_LAB_SEARCH_ROUTING_1).

Sprint-0 Step 3. A controlled intelligence-intake system: it (1) searches across
the Step-2 registered sources, (2) returns results gated through the Step-1 policy
engine, (3) proposes a routing target (which dashboard section a result belongs to),
(4) captures useful unconfirmed material as an amber **raw signal** (never trusted
evidence), and (5) prepares promotion to verified evidence through the EXISTING
human-confirmation lifecycle gate.

**This step is a CONSUMER of Steps 1+2. It adds NO second allow path and forks NO
registry/taxonomy.** External visibility is decided ONLY by ``policy.engine`` +
``policy.engine.partner_projection``; promotion happens ONLY through
``policy.lifecycle``; source metadata is read ONLY from ``policy.sources``.

Public surface:

* ``models``   — SearchMode (5), RouteTarget (13), RoutingMethod, RawSignal (16 fields).
* ``routing``  — 11 deterministic rules + LLM-assist (proposes-only) + audited override.
* ``runner``   — ``search`` over registered sources; external = projection-only; zero
                 results = source-gap candidate, never a leak.
* ``signals``  — amber raw-signal capture + promotion via the Step-1 lifecycle gate.
* ``store``    — parameterized-SQL logging/records; fail-closed on any DB error.
"""

from __future__ import annotations

from policy.search import models, routing, runner, signals  # noqa: F401

__all__ = ["models", "routing", "runner", "signals"]
