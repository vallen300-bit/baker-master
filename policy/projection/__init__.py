"""AI Hotel Lab — partner-safe projection surface (AI_HOTEL_LAB_PARTNER_PROJECTION_1).

Sprint-0 Step 4. The safety gate between internal intelligence and partner-facing
cooperation: a backend/view-model layer that turns ``verified_evidence`` +
``action_linked`` items into role-specific, redacted, partner-safe **view packets**
for NVIDIA / MOHG / venue-owner, plus a Brisen-internal preview and an evidence-admin
capability.

**This step is a CONSUMER of Steps 1-3. It adds NO second permission engine, joins NO
raw tables in an external response, and adds NO new promotion path.** External
visibility + the only safe-body builder is ``policy.engine`` /
``policy.engine.partner_projection``; promotion is ``policy.lifecycle``; source
metadata is ``policy.sources``; amber/research items live in ``policy.search`` and
never project externally.

Public surface:

* ``models``    — AudienceRole (4), ProjectionState (8), ProjectionItem (19 fields),
                  ViewPacket, the EXTERNAL field allowlist (AC4).
* ``projector`` — build a ProjectionItem per audience; cross-role isolation (absent,
                  not hidden); external bodies built ONLY by partner_projection.
* ``packets``   — SEPARATE external/internal/admin serializers; view-as parity;
                  server-side spoof guard; cache revalidation.
* ``admin``     — evidence-admin approve (via the Step-1 lifecycle gate) / revoke /
                  refresh, each audited.
* ``store``     — parameterized-SQL persistence; non-mutating reads; fail-closed.
"""

from __future__ import annotations

from policy.projection import admin, models, packets, projector, store  # noqa: F401

__all__ = ["models", "projector", "packets", "admin", "store"]
