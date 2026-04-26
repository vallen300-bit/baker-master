# BRIEF: KBL_SCHEMA_DRIFT_DETECTOR_1 — Per-write registry-yaml drift guard + weekly audit

**Milestone:** M1 (Wiki stream foundation), row M1.3
**Roadmap source:** `_ops/processes/cortex3t-roadmap.md` §M1
**Spec source:** `baker-vault/_ops/ideas/2026-04-26-kbl-schema-drift-detector-1-spec.md` (RA-21 drafted, Director Q1–Q4 ratified)
**Estimated time:** ~6–8h
**Complexity:** Medium (hook stage discipline + small migration + 7 checks + dispatcher consolidation)
**Prerequisites:**
- M0 KBL_SCHEMA_1 (PR #52) — slug registry shipped
- M1.2 KBL_PEOPLE_ENTITY_LOADERS_1 (PR #62 `5ae6545`) — `kbl/people_registry.PersonSchema` available as import
- M1 HAGENAUER_WIKI_BOOTSTRAP_1 (PR #63 `d48dac8`) — confirms registry yamls are consumed truth
- M1 WIKI_LINT_1 (PR #67 in flight) — clean wiki baseline before drift guard activates

---

## Context

Registry yamls (`baker-vault/slugs.yml` v10, `baker-vault/people.yml` v3) are the canonical KBL classification source. They have **load-time** validation (`kbl/slug_registry.py` rejects on duplicates) but **no write-time** guard. A bad commit lands in main and breaks at next ingestion.

Today this discipline is human:

- Lifecycle transitions (`active → retired`) are guarded only by Director ratification quote in commit msg — checked by reviewer's eyeball.
- Alias preservation on retire is convention.
- Reference-integrity (`people.yml::primary_matter` resolves to a real `slugs.yml` slug) is checked nowhere automatically.

Recent near-miss: `edita-russo` composite slug retired today (v9 → v10) with full Director quote — discipline held because a human reviewed.

`.githooks/author_director_guard.sh` (CHANDA invariant #4) was the prior attempt at write-time enforcement but it's installed at the wrong stage (pre-commit, can't read `-F`/`-m` commit message — see `feedback_chanda_4_hook_stage_bug.md`). This brief installs the new detector at **commit-msg stage** from day one and folds the existing CHANDA #4 logic into the same dispatcher per Director Q4 ratification.

---

## Problem

1. No write-time hard gate on registry yaml schema, lifecycle, or reference integrity.
2. `author_director_guard.sh` exists but is broken — wrong stage, never fires reliably on `-m` commits.
3. Two complementary commit-msg checks (Gold drift from PR #66, registry drift from this brief) can't both claim the `commit-msg` symlink without a dispatcher.
4. No defense-in-depth: if a write bypasses the hook (`--no-verify`, direct push from a stale clone, GitHub web edit), nothing catches it until the next ingestion crash.

## Solution

One Python module + one bash dispatcher (folding existing GOLD hook + new drift hook + migrated CHANDA #4 hook) + one weekly APScheduler audit + one schema migration.

### Components

| Component | Path | Purpose |
|---|---|---|
| `kbl/schema_drift_detector.py` | `15_Baker_Master/01_build/kbl/schema_drift_detector.py` | Pure-Python checker. Loads target yaml, runs 7 checks, returns structured `Violation` list (severity-tiered). Importable + scriptable. |
| `.githooks/kbl_schema_drift.sh` | `baker-vault/.githooks/kbl_schema_drift.sh` | Bash wrapper invoking the Python module. Hard-fails commit on any error-tier violation. |
| `.githooks/commit_msg_dispatcher.sh` | `baker-vault/.githooks/commit_msg_dispatcher.sh` | New small dispatcher. Replaces current `commit-msg → gold_drift_check.sh` symlink. Calls each sub-check in sequence; any failure aborts. |
| `.githooks/author_director_guard.sh` | `baker-vault/.githooks/author_director_guard.sh` | **Migrated** from `15_Baker_Master/01_build/invariant_checks/author_director_guard.sh`. Re-targeted to commit-msg stage. Logic preserved (Director-signed: marker check on `author: director` md edits). |
| `orchestrator/kbl_drift_audit_job.py` | `15_Baker_Master/01_build/orchestrator/kbl_drift_audit_job.py` | APScheduler weekly job (Mon 09:15 UTC, between AI Head 09:00 audit and Gold 09:30 audit). Runs full drift scan, writes `kbl_drift_audits` row, Slack-DM AI Head on warn-tier. |
| Migration | `15_Baker_Master/01_build/migrations/00NN_kbl_drift_audits.sql` | New tables: `kbl_drift_audits` + `kbl_drift_hook_failures`. |

### 7 checks (severity-tiered, per spec §2)

| # | Check | Tier | Trigger |
|---|-------|------|---------|
| 1 | Schema validity (parses against `SlugSchema` / `PersonSchema`) | error | every write |
| 2 | Version bump discipline (`version:` strictly incremented on non-cosmetic change) | error | diff touches matters/people block |
| 3 | No duplicate slugs / aliases | error | every write |
| 4 | Lifecycle ratification guard (`active → retired` requires "ratified" + quoted Director phrase in commit msg) | error | status changed to retired |
| 5 | Alias preservation on retire (retire MUST NOT delete aliases) | error | status changed AND aliases shrank |
| 6 | Reference integrity (`people.yml::primary_matter` + `related_matters` resolve to real `slugs.yml` slugs, active OR retired) | error | people.yml diff |
| 7 | Author identity (registry yaml edits require Director author OR Tier B commit message with quoted authorization — extends current `author_director_guard.sh` scope to registry yamls) | error | author ≠ Director AND msg lacks Tier B authorization quote |

### Severity tiers

- **error** — hard-fail at commit-msg hook; commit rejected
- **warn** — soft-flag in weekly audit; Slack-DM AI Head; no commit block
- **info** — logged only; surfaced in monthly review

### Operational discipline (Director Q2 anchor)

Reference-integrity is hard-fail. Multi-file commits stage `slugs.yml` BEFORE `people.yml` in the same push; hook reads target file in isolation, so two-commit sequence works equally well. Hook error message names the missing slug explicitly so AI Head sees the gap.

Emergency Director write: `--no-verify` bypass available, logged to `kbl_drift_audits` for next-day audit (the weekly job catches anything the hook missed).

## Files to modify

- **Create:** `kbl/schema_drift_detector.py` (pure-Python checker, 7 checks)
- **Create:** `tests/test_schema_drift_detector.py` (8 tests: 1 valid + 7 synthetic-bad)
- **Create:** `orchestrator/kbl_drift_audit_job.py` (APScheduler weekly job)
- **Create:** `migrations/00NN_kbl_drift_audits.sql` (two new tables)
- **Modify:** `orchestrator/scheduler.py` (register `kbl_drift_audit_sentinel`)
- **Modify:** `tests/test_scheduler.py` (assert new job registered)
- **Vault — create:** `baker-vault/.githooks/kbl_schema_drift.sh` (bash wrapper invoking Python module)
- **Vault — create:** `baker-vault/.githooks/commit_msg_dispatcher.sh` (sequence: author_director_guard → gold_drift_check → kbl_schema_drift; any non-zero aborts)
- **Vault — migrate:** `baker-vault/.githooks/author_director_guard.sh` (copy from `15_Baker_Master/01_build/invariant_checks/`; preserve logic; verify it works at commit-msg stage)
- **Vault — re-link:** `baker-vault/.githooks/commit-msg` symlink — currently `→ gold_drift_check.sh`; new `→ commit_msg_dispatcher.sh`
- **Vault — install verification:** `baker-vault/.githooks/INSTALL_VERIFY.md` (1-page how-to for fresh clones — `git config core.hooksPath .githooks` already set, but document the symlink + chmod steps)

## Files NOT to touch

- `baker-vault/slugs.yml` / `baker-vault/people.yml` content (Director-curated; out of scope).
- `kbl/slug_registry.py` / `kbl/people_registry.py` — model reference only; do not refactor schemas in this brief.
- `kbl/gold_drift_detector.py` (PR #66 ship) — read-only reference for sentinel pattern.
- `15_Baker_Master/01_build/invariant_checks/author_director_guard.sh` — leave the source-of-truth in place after vault migration; remove only after acceptance test passes (revert path if migration needs rollback).
- `_ops/director-gold-global.md` / `wiki/matters/*/gold.md` — covered by gold_drift_check.sh, untouched here.

## Risks

- **Hook stage-bug regression** (CHANDA #4 lesson, `feedback_chanda_4_hook_stage_bug.md`) — install at commit-msg stage from day one; verify by deliberately committing with `git commit -m '...'` (not interactive editor) and confirming hook fires.
- **Hook crashes on edge case → blocks all commits** — soft-fail on hook *runtime* error (allow commit + Slack-DM); hard-fail only on *violation*. Distinguish in the bash wrapper.
- **Two commit-msg checks already exist** (gold from PR #66 + author_director_guard via this brief) — dispatcher pattern is the consolidation; verify each sub-check exits 0 on no-op (i.e. running the dispatcher on a commit that touches nothing protected must exit 0 fast).
- **Migration-bootstrap drift** (`feedback_migration_bootstrap_drift.md`) — `grep "_ensure_kbl_drift\|kbl_drift_audits\|kbl_drift_hook" memory/store_back.py` returned ZERO at draft time (verified); migration file is the only DDL path. If a future bootstrap is added, it must match types — call this out in the migration's header comment.
- **Grandfather clause masks real drift** — V1 ships against current `slugs.yml` v10 + `people.yml` v3 with **zero violations** (clean baseline). If detector flags any pre-existing violation at acceptance, hand-fix BEFORE hook activates. No permanent grandfather list.
- **Director emergency bypass** — `--no-verify` allowed (logged); use sparingly. Weekly audit catches what the hook missed.
- **Reference-integrity false positives during multi-file commits** — hook reads target file in isolation; multi-file refs validated only at weekly audit.
- **Existing `commit-msg → gold_drift_check.sh` symlink** — re-linking to dispatcher must preserve gold drift behavior. Acceptance test: commit a Gold change without `Director-signed:` marker; dispatcher must reject (gold sub-check fires).

## Code Brief Standards (mandatory)

- **API version:** N/A — internal Python + bash hooks.
- **Deprecation check:** confirm `kbl/slug_registry.SlugSchema` + `kbl/people_registry.PersonSchema` (both shipped 2026-04-26 in PR #62 `5ae6545`) are stable as imports at build start.
- **DDL drift check:** `grep -n "_ensure_kbl_drift\|kbl_drift_audits\|kbl_drift_hook" memory/store_back.py` → must return zero lines (verified at draft time 2026-04-27 00:30 UTC). If non-zero, treat as bootstrap-drift trap and reconcile per `feedback_migration_bootstrap_drift.md` BEFORE writing the migration.
- **Fallback on Python crash in hook:** log to `kbl_drift_hook_failures` table; allow commit through (soft-fail) + Slack-DM AI Head — never block on tooling bug. Distinguish in `kbl_schema_drift.sh`: `python3 -c "..." || EXIT=$?` then if `EXIT == 1` (violation) → reject; if `EXIT == 2+` (crash) → soft-fail.
- **Literal pytest output mandatory:** ship report MUST include literal `pytest tests/test_schema_drift_detector.py tests/test_scheduler.py -v` stdout. No "passes by inspection" (per `feedback_no_ship_by_inspection.md`).

## Verification criteria

1. `pytest tests/test_schema_drift_detector.py -v` — 8 tests pass (1 valid baseline + 7 synthetic-bad, one per check).
2. `pytest tests/test_scheduler.py -v -k drift` — new `kbl_drift_audit_sentinel` job registered, fires Mon 09:15 UTC.
3. `python -c "import py_compile; py_compile.compile('kbl/schema_drift_detector.py', doraise=True); py_compile.compile('orchestrator/kbl_drift_audit_job.py', doraise=True)"` exits 0.
4. **Hook smoke tests** (run from a sandbox vault clone, NOT main vault):
   - `git commit -m 'test: noop'` on a commit touching no protected paths → dispatcher exits 0 fast.
   - Commit retiring a slug without ratification quote → rejected with named violation.
   - Commit changing `people.yml::primary_matter` to a non-existent slug → rejected with named missing slug.
   - Commit by non-Director author touching `slugs.yml` without Tier B authorization quote → rejected.
   - Commit touching Gold without `Director-signed:` → rejected (gold sub-check still fires through dispatcher — regression check).
5. Backfill validation: `python -c "from kbl.schema_drift_detector import audit_all; print(audit_all('/Users/dimitry/baker-vault'))"` against current registries → empty violation list.
6. PR description documents (a) the symlink re-link, (b) the migration table names, (c) the order of dispatcher sub-checks, (d) the rollback path if migration needs to be undone.
7. Migration applied + `SELECT COUNT(*) FROM schema_migrations WHERE name LIKE '%kbl_drift%'` returns 1 (post-deploy poll up to 60s per Lesson #41).

## Out of scope

- WIKI_LINT_1 territory (wiki/ markdown content) — separate brief, in flight as PR #67.
- Postgres-side drift between yaml registries and `vip_contacts` / `matters` tables — orthogonal.
- LLM-assisted "soft" drift detection (semantic alias collision) — V2 if signal-to-noise warrants.
- Entity registry yaml — loader shipped (PR #62) but yaml file not yet populated; V1 hardcodes `slugs.yml` + `people.yml`. Generalize to entity yaml in a thin V2 follow-up once the file lands.
- Pre-existing CHANDA #4 hook removal from `15_Baker_Master/01_build/invariant_checks/` — leave in place until acceptance complete; remove in a follow-up commit (revert path).
- Backfill audit of historical commits that bypassed CHANDA #4 — separate forensic brief if Director wants it.

---

## Branch + PR

- Branch: `kbl-schema-drift-detector-1`
- PR title: `KBL_SCHEMA_DRIFT_DETECTOR_1: per-write registry yaml drift guard + commit-msg dispatcher consolidation + weekly audit`
- Trigger class: **medium** (DB migration + commit-msg hook stage discipline + cross-capability state writes)
- Reviewer: **B1 situational review per `_ops/ideas/2026-04-24-b1-situational-review-trigger.md`** (DB migration + cross-capability state writes hit two trigger classes).
- Builder ≠ B1 (b1-builder-can't-review-own-work). **Recommend B3 builder** (current capacity post-#66/#68 ship; familiar with vault `.githooks/` layout from gold_drift_check.sh build) **OR B4 builder** (parallel option if B3 idle is uncertain).
- Cross-lane reviewer: AI Head B (per Pattern C; merge gate after B1 APPROVE + AI Head B `/security-review` skill invocation per Lesson #52).

## /write-brief 6-step compliance

1. **EXPLORE** — done. `kbl/people_registry.py` + `kbl/slug_registry.py` import shapes verified (PR #62 `5ae6545`). `gold_drift_check.sh` reviewed at `baker-vault/.githooks/gold_drift_check.sh` for hook architecture pattern. `author_director_guard.sh` located at `15_Baker_Master/01_build/invariant_checks/author_director_guard.sh` (NOT in vault — flag-worthy). `core.hooksPath = .githooks` confirmed in vault. `memory/store_back.py` grepped for `_ensure_kbl_drift_*` — zero hits (clean for migration). Lesson #47 redundancy sweep on `git log --grep`, `briefs/archive/`, and codebase grep — zero shipped feature under names `schema_drift|drift_detector|kbl_drift|drift_audit`. New territory.
2. **PLAN** — embedded in this brief (Architecture, Files-to-modify, Files-NOT-to-touch, Verification, Risks). Q1–Q4 from spec §4 ratified by Director per spec §10.
3. **WRITE** — this file.
4. **TRACK** — mailbox `briefs/_tasks/CODE_<N>_PENDING.md` written at dispatch time. **Dispatch gated on PR #67 merge** per RA-22 + Director.
5. **DOCUMENT** — PR description must surface the 4 architectural decisions: (a) commit-msg dispatcher pattern, (b) `author_director_guard.sh` migration path, (c) reference-integrity hard-fail with isolated-file-read semantics, (d) clean-baseline grandfather-fix discipline.
6. **CAPTURE LESSONS** — if migration / hook discipline / dispatcher sequencing surface unexpected patterns, append to `tasks/lessons.md`.

## Flag-worthy items for Director / AI Head review

1. **Q5/Q6/Q7 reference in handover** — handover says "Q5/Q6/Q7 ratified defaults per Director 'your call'" but spec §4 only has Q1–Q4. Treating handover-writer numbering as off-by-one carryover; Q1–Q4 ratifications per spec §10 are the operative answers. Surface for Director re-confirmation if there were extra exploration-stage Qs not migrated to spec.
2. **Hook dispatcher consolidation is a NEW architectural decision** beyond spec §2 — three commit-msg sub-checks (gold + drift + author-guard) must share the slot via the new `commit_msg_dispatcher.sh`. Spec implied separate hooks; this brief consolidates. Calling it out for explicit AI Head A blessing before dispatch.
3. **`author_director_guard.sh` migration semantics** — spec Q4 ratifies "single hook covering Director-only files AND registry yamls." Real path: migrate the script from baker-master `invariant_checks/` to vault `.githooks/`, re-stage commit-msg, integrate into dispatcher. The pre-existing pre-commit installation (per `feedback_chanda_4_hook_stage_bug.md`) is broken — this brief retires it. Confirm Director ack on retirement before dispatch.

## §6C orchestration note (B-code dispatch coordination)

- This brief touches commit-msg hook discipline (cross-capability surface) — every developer's commits are affected. Acceptance MUST be on a sandbox vault clone before re-link in the live vault. Re-link itself is reversible (single `ln -sf` revert).
- Builder must respect §6C visibility — RA-22 and Director hold concurrent dispatch authority during M1/M2 parallel lanes. If a same-task collision surfaces, halt per Lesson #46.
- §3 mailbox hygiene: dispatcher uses standard `briefs/_tasks/CODE_<N>_PENDING.md` overwrite pattern; mailbox marked COMPLETE post-merge.
- Wake-paste mandatory same turn as dispatch (Lesson #48).

## Co-Authored-By

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
