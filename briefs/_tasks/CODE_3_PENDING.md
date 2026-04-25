# CODE_3_PENDING — B3: KBL_PEOPLE_ENTITY_LOADERS_1 — 2026-04-25

**Dispatcher:** AI Head A (Build-lead, post-handover refresh)
**Working dir:** `~/bm-b3`
**Branch:** `kbl-people-entity-loaders-1` (create from main; B3 currently on main but 5 behind — pull first).
**Brief:** `briefs/BRIEF_KBL_PEOPLE_ENTITY_LOADERS_1.md`
**Status:** OPEN
**Reviewer on PR:** AI Head B (cross-team)

**§2 pre-dispatch busy-check** (per `_ops/processes/b-code-dispatch-coordination.md`):
- Mailbox prior state: B3 last review dispatch was for PR #61 (commit 2cb7eb6); B3 shipped review at 7280acc. Mailbox §3 hygiene gap — never marked COMPLETE despite review shipped. **This dispatch overwrites that stale state.** Logged for Monday audit.
- Branch prior state: main behind 5. Pre-execution `git checkout main && git pull -q` resolves.
- No file overlap with B1 (HAGENAUER_WIKI_BOOTSTRAP_1) — B3 touches `kbl/` + `tests/`; B1 touches `scripts/` + `tests/`. Independent.

**§3 hygiene retroactive note:** B3's prior PR #61 review (commit `7280acc`) closed by AI Head B's merge `92e4129`. CODE_3_PENDING.md was never overwritten. This dispatch closes the loop.

**Dispatch authorisation:** Director cleared M1 parallel-3 dispatch in handover at 14:00 UTC 2026-04-25 ("ok. give me tasks for codes" 2026-04-25 ~afternoon).

---

## Brief route (charter §6A)

`/write-brief` 6 steps applied:
1. EXPLORE — done by AI Head A (read kbl/ingest_endpoint.py:97-110 explicit TODO, slug_registry.py pattern, M0 ship reports).
2. PLAN — embedded in brief.
3. WRITE — full brief at `briefs/BRIEF_KBL_PEOPLE_ENTITY_LOADERS_1.md`.
4. TRACK — this mailbox.
5. DOCUMENT — PR description MUST include `KBL_REGISTRY_STRICT` flip plan (when, observability, rollback).
6. CAPTURE LESSONS — apply LONGTERM.md DDL-drift check to verify no DB write paths.

## Code Brief Standards compliance

- API version: N/A (internal Python).
- Deprecation check: N/A.
- Fallback: `KBL_REGISTRY_STRICT` env flag default-off preserves current ingest behaviour exactly. Flag flip is a separate Tier B with B1 situational review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`.
- DDL drift: zero DB writes; grep verification.
- Literal pytest output: required (3 test files, ≥16 tests across them).

## Verification before shipping

Brief §"Verification criteria" (1-5 items). Item 1+2+3 cover unit behaviour; item 5 covers PR documentation hygiene for the cross-capability state-write trigger class.

## Ship report path

`briefs/_reports/B3_kbl_people_entity_loaders_1_<YYYYMMDD>.md`
