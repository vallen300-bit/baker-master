# CODE_3_PENDING — HOLD: PLAUD_SENTINEL_1 dispatched against shipped sentinel

**Status:** 🛑 HOLD pending Director re-decision (2026-04-26)
**Dispatch superseded:** the eb68dca dispatch is **stale** — do NOT proceed with the brief as written.

---

## Why hold

B3's pre-build codebase audit caught a gap that AI Head A's §2 busy-check missed:

- **`triggers/plaud_trigger.py` (599 LOC) already shipped** at commit `2f5675c` (PLAUD-INGESTION-1).
- Earlier brief archived at `briefs/archive/BRIEF_PLAUD_INGESTION_1.md`.
- Endpoints already discovered: `/file/simple/web` + `/file/detail/{file_id}`.
- Storage: writes to `meeting_transcripts` with `source="plaud"` (NOT a separate table).
- Scheduler: `plaud_scan` job at 15 min, gated on `config.plaud.api_token` (`triggers/embedded_scheduler.py:111-122`).
- Config: `PlaudConfig` already in `config/settings.py:139-141` with `PLAUD_TOKEN`, `PLAUD_API_DOMAIN`, `PLAUD_SCAN_INTERVAL`.
- Backfill: `backfill_plaud()` with PG advisory lock 867532 already runs at scheduler startup.
- Pipeline integration: PM signal detection, contact interactions, deadlines, commitments, meeting_pipeline async — already wired.

PLAUD_SENTINEL_1 brief Q3 ratification ("new plaud_notes table") was made without knowledge of the existing `meeting_transcripts` design.

## What B3 should do (until Director re-decides)

1. **Do NOT create branch `plaud-sentinel-1`.**
2. **Do NOT modify any plaud-related file.**
3. Stay on main, idle.
4. Optional: prepare option-3 delta brief mentally if Director chooses that path (it's the recommended option).

## Awaiting Director on three paths

| Option | Effort | Trade-off |
|---|---|---|
| 1. Refactor: split `meeting_transcripts source=plaud` into new `plaud_notes` table; deprecate `triggers/plaud_trigger.py`; rebuild | ~12–18h | redoes shipped work; data migration brittle |
| 2. Layer: keep existing; add `baker-plaud` Qdrant collection + `plaud_search` Scan route on top | ~3–5h | violates Q3 ratification; vector-only differentiation |
| 3. **Cancel + delta brief: close PLAUD_SENTINEL_1; write tight follow-up covering only the actual deltas Director wants on top of PLAUD_INGESTION_1** | depends on deltas | recommended by B3 + AI Head A; surfaces real Director intent |

AI Head A endorses **Option 3** — Director's Q3 ratification was made on incomplete info; redoing shipped work for an answer that may itself be wrong is the trap.

## Rollback log for AI Head A

- Brief at `briefs/BRIEF_PLAUD_SENTINEL_1.md` retained for now (decision log; revisit after Director re-decision).
- This mailbox supersedes eb68dca dispatch authority.
- Lesson capture pending — see Director response on §2 busy-check upgrade (codebase grep + `briefs/archive/` scan should be mandatory steps).

## Cross-stream

B3 idle. B2 still in flight on WIKI_LINT_1 (no impact). B1, B4 idle.
