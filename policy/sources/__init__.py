"""AI Hotel Lab — source inventory / evidence supply chain (AI_HOTEL_LAB_SOURCE_INVENTORY_1).

Sprint-0 Step 2. A machine-usable **source registry** + a human-readable **source
map** for the AI Hotel Lab — the controlled evidence supply chain that inventories
what the Lab may search, ingest, monitor, and route, and classifies every source so
the later search/routing layer (Step 3) cannot leak to NVIDIA / MOHG / banks /
investors / site owners / PR / residence buyers / vendors.

**This step supplies classification METADATA only — it never decides external
visibility.** External visibility is decided ONLY by the live Step-1 policy engine
(`policy.engine.evaluate` + `policy.engine.partner_projection`). There is no second
allow path here (T3): every external read / source-map external column routes
through the Step-1 engine per source. Classification is not a grant (AC3).

NOT search (no content search, no snippets, no summaries — that is Step 3/5).

Public surface:

* ``models``    — domains (8), object types, SourceRecord, RegistryChange, enums.
* ``registry``  — fail-closed validation + Step-1 policy integration + AC10 change flow.
* ``store``     — parameterized-SQL persistence + fail-closed external read.
* ``sourcemap`` — human-readable markdown source map (internal vs external columns).
* ``fixtures``  — SAMPLE rows: ≥1 per domain + gap rows (demo / tests only).
"""

from __future__ import annotations

from policy.sources import models, registry  # noqa: F401

__all__ = ["models", "registry"]
