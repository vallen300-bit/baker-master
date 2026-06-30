---
status: PENDING
brief_id: PROJECT_NUMBER_REGISTRY_1
to: b4
from: lead
dispatched_by: cowork-ah1
dispatched_at: 2026-06-30
branch: project-number-registry-1
reply_target: cowork-ah1 (bus) for ship report; gate verdicts to lead
effort: medium
task_class: additive new module (kbl/project_registry_store.py) + idempotent table + 4 resolvers + live-PG tests
gate_plan: G1 pytest tests/test_project_registry.py + py_compile + check_singletons -> codex G3 (effort medium) -> lead /security-review G4 -> lead merge. NO deploy (library only, no prod caller; idempotent CREATE TABLE IF NOT EXISTS self-heals on boot).
full_brief: briefs/BRIEF_PROJECT_NUMBER_REGISTRY_1.md
---

# PROJECT_NUMBER_REGISTRY_1 — human + machine project-number registry (Baker OS V2 Box 5 foundation)

## Read this first
The complete, copy-pasteable implementation is in **`briefs/BRIEF_PROJECT_NUMBER_REGISTRY_1.md`** (on main, committed alongside this dispatch). Implement exactly as written there. This envelope carries only dispatch metadata + acceptance gates. Brief was authored + SOP'd + codex-ratified (#4679 format, #4680 guardrails) by cowork-ah1; do not redesign.

## Context (one paragraph)
Baker OS V2 / Signal Journey Management (codex-arch design, Director-directed) needs a human-typeable **project number** (`DESK-MATTER-###`, e.g. `BB-AUK-001`) that a person puts in an email subject / WhatsApp, that Baker resolves to matter + desk + people + ClickUp list, and the ClickUp Dispatcher reads natively. No such scheme exists today (only kebab slugs + opaque ClickUp IDs). This brief builds the **registry table + resolver + soft-lane lookup primitives** ONLY — it does NOT wire the Box 5 fast lane (separate downstream brief).

## Scope (locked — do NOT exceed)
- ADD new file `kbl/project_registry_store.py`: one idempotent `project_registry` table (`CREATE TABLE IF NOT EXISTS`, mirror `ensure_airport_ticket_table` pattern) + `register_project()` + 3 resolvers: `resolve_project_number()` (hard lane), `resolve_by_participant()` + `resolve_by_alias()` (soft-lane primitives).
- Validate `matter_slug` via `kbl.slug_registry.is_canonical`. DB via `from kbl.db import get_conn` (contextmanager, default tuple cursor, explicit `conn.commit()` / `conn.rollback()` in except).
- Guardrails (codex #4680 — HARD): number-alone never clears; sender-only forbidden.
- ADD `tests/test_project_registry.py` (7 vertical live-PG tests, written FIRST; real Postgres via `TEST_DATABASE_URL`, auto-skip if unset; no implementation-coupled mocks).
- Additive ONLY. Touches NO live code (no Box 5 / pipeline / dispatcher wiring). No migration file (idempotent boot-ensure). No new env vars. No new deps. Every SELECT has a LIMIT. Blast radius ~0.

## Acceptance criteria
- AC1: `python3 -c "import py_compile; py_compile.compile('kbl/project_registry_store.py', doraise=True)"` passes.
- AC2: `pytest tests/test_project_registry.py -v` → all 7 pass (or auto-skip if no `TEST_DATABASE_URL` locally; CI runs them live).
- AC3: `bash scripts/check_singletons.sh` OK (no new direct-instantiation violation introduced).
- AC4: Guardrail tests prove number-alone never clears and sender-only is rejected.
- AC5: `resolve_project_number` rejects a non-canonical `matter_slug` (via `is_canonical`).

## Done rubric
Build-done = PR merged + AC1-AC5 green. NO live AC / no POST_DEPLOY_AC — library only, no prod caller, no deploy. Confirm `DESK_CODES` values + canonical Aukera/Annaberg slug with dispatcher (cowork-ah1) before any non-pilot seed (NOT part of this build).

## Context-economy (HARD — no auto-compaction)
- Read ONLY: `briefs/BRIEF_PROJECT_NUMBER_REGISTRY_1.md`, `orchestrator/airport_ticketing_bridge.py:262` (`ensure_airport_ticket_table` template), `kbl/db.py:45` (`get_conn`), `kbl/slug_registry.py` (public accessors). Do not read more than needed.
- Output to /tmp; tails only. Context >70%: commit, push, bus handoff, STOP.
