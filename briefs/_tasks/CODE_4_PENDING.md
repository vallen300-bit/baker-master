# CODE_4_PENDING — BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1 — 2026-05-05

**Brief:** baker-master `briefs/BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md` (Tier A, ~3-4 hours, 12 ACs)
**Working branches (TWO PRs, cross-repo):**
- `b4/brisen-lab-surface-6a-partial-unique-index-1` (brisen-lab repo)
- `b4/baker-master-surface-6a-hook-retry-1` (baker-master repo)
**Pre-requisites:** brisen-lab main HEAD `bc1e3e6` (Surface 6 merged) + baker-master main HEAD `bad7c6d` (this brief commit)
**Acceptance criteria:** per brief §ACs (12 testable items, A1-A12)
**Ship gate:** literal `pytest` GREEN both sides — no by-inspection (Lesson #52)
**Heartbeat:** 12h cadence binding (per SKILL.md `59f23c4` §B-code stall chase)

**Read first (MANDATORY):**
1. `briefs/BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md` — full spec + 5 features + 12 ACs
2. `~/baker-vault/_ops/agents/b4/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

**Path forward:**
1. Read brief BRIEF_BRISEN_LAB_SURFACE_6A_PARTIAL_UNIQUE_INDEX_1.md cover-to-cover
2. **Pre-work — verify migration runner CONCURRENTLY-handling** (Sequencing step 3): inspect `~/bm-b4-brisen-lab/start.sh` (or migration runner). If runner wraps `.sql` files in BEGIN/COMMIT, surface to AH1 BEFORE writing migration.
3. **Pre-apply prod sanity check:** run duplicate-detect SELECT against prod brisen-lab DB. Surface to AH1 if non-empty.
4. Implement Feature 1 (migration) on `b4/brisen-lab-surface-6a-partial-unique-index-1` branch in brisen-lab repo
5. Apply locally + verify `pg_index.indisvalid = TRUE` post-CONCURRENTLY
6. Implement Feature 2 (handler 409 + observability) in brisen-lab `bus.py`
7. Implement Feature 3 (regression tests with threading.Barrier + 20× loop) in brisen-lab `tests/`
8. Implement Feature 5 (hook retry-on-409 with jitter, max-retry=1) in baker-master `.claude/hooks/user-prompt-submit-confirm.py` on `b4/baker-master-surface-6a-hook-retry-1` branch
9. Implement Feature 4 (cutover runbook in baker-vault `_ops/processes/v2-bridge-cutover-runbook.md`)
10. Live pytest GREEN both repos
11. Open TWO PRs (brisen-lab + baker-master)
12. Ship via PL paste-block per SKILL.md §"PL ship-report contract"
13. 4-gate review chain on each PR: live pytest + AH2 /security-review + architect spot-check + feature-dev:code-reviewer 2nd-pass

**Critical pre-merge gates (from architect post-WRITE review):**
- Hook retry-on-409 (Feature 5) is NEW scope, cross-repo — without it, race-loser silently fails fail-open. V0.3.7 hook does NOT retry on non-200 today (verified at `.claude/hooks/user-prompt-submit-confirm.py:216-217`).
- Migration runner CONCURRENTLY-handling: verify upfront before writing migration (cannot run inside transaction block).
- pg_index.indisvalid check post-CONCURRENTLY: INVALID index from duplicate-mid-build silently masks future re-runs via `IF NOT EXISTS`. Hard ship-blocker.
- DROP INDEX CONCURRENTLY for symmetry/online-safety.
- psycopg2 version: verify ≥2.8 in requirements.txt; fallback `e.pgcode == '23505'` if uncertain.
- Test determinism: `threading.Barrier(2)` + 20× loop + reject SQLite at conftest.

**Merge order (mandatory):** brisen-lab PR FIRST → baker-master PR second. Brisen-lab daemon emits 409 first; baker-master hook retries against the now-409-emitting daemon. Reverse order = hook retries against daemon that doesn't emit 409 → no-op, harmless but unverifiable.

**Anchor:** Director ratification 2026-05-05 ("agreed" → "go Surface 6a"); brief commit `bad7c6d` baker-master main; architect post-WRITE review agent `abd0422d6c3f380b8` 2026-05-05.

---

## DESIGN-BLOCKER RESOLUTION — V0.2 amendment ratified (2026-05-05)

**Status:** Director ratified Option A (adapt to bootstrap pattern, drop CONCURRENTLY). V0.2 amendment landed on baker-master main at commit **`9bac2a2`** — read brief tail §V0.2 §A-§F for full details.

**Net effect for B4:**
- **Feature 1 implementation REPLACED:** edit `db.py` `SCHEMA_V2_SQL` inline (no `migrations/` dir, no `applied_migrations.lock`, no CONCURRENTLY). Add `CREATE UNIQUE INDEX IF NOT EXISTS uq_session_keys_worker_active ON brisen_lab_session_keys (worker_slug) WHERE expired_at IS NULL` + `DROP INDEX IF EXISTS idx_session_keys_worker_active` to the SCHEMA_V2_SQL string in db.py.
- **ACs DROPPED:** A1, A8, A9, A11 (migration-runner-specific). REPLACED with A1' (grep db.py) + A8' (post-deploy `\d`) + A9' (duplicate-detect SELECT) + A11' (code-level rollback).
- **Pre-work DROPPED:** no runner inspection needed; bootstrap-pattern confirmed.
- **Architect folds STATUS:** Feature 5 hook retry-on-409 + psycopg2 ≥2.8 / SQLSTATE '23505' fallback + threading.Barrier(2) + stderr log = **STAY**. CONCURRENTLY symmetry / `pg_index.indisvalid` / runner-verification = **MOOT**.
- **Sequencing:** drop step 3 (runner inspection); replace step 5 (no migration file — db.py edit instead).
- **Features 2/3/4/5 unchanged.**

**Cleared to proceed.** Create branches `b4/brisen-lab-surface-6a-partial-unique-index-1` (brisen-lab) + `b4/baker-master-surface-6a-hook-retry-1` (baker-master), implement per V0.2 amendment, ship via PL paste-block.

No autonomous polling. Stop after ship report.

---

## GATE-4 2nd-pass UPDATE — 2026-05-05 (fold pre-merge across both repos)

**Source:** feature-dev:code-reviewer 2nd-pass on brisen-lab PR #3 + baker-master PR #161. Both = PASS-WITH-NITS-FOLD-NEEDED (1 MED each, no blockers). baker-vault PR #85 PL-reviewed manually = PASS clean (no fold needed). AH2 gate-2 security-review on PR #3 + PR #161 = PASS both (no findings).

### MED-B4-1 — brisen-lab `bus.py` bare `except Exception` returns HTTP 400 for non-FK server errors

File: `bus.py` (brisen-lab repo, branch `b4/brisen-lab-surface-6a-partial-unique-index-1`), `register_session_pubkey` handler, bare `except Exception` block immediately after the `UniqueViolation` catch.

Issue: comment above says "FK violation → unknown worker_slug → surface 400," but the bare except catches *any* unexpected DB error (pool exhaustion, connection timeout, other constraints) and maps them to HTTP 400 `register_failed`. 400 signals client error; server-side failures should surface 500. Misleading observability under pool/timeout failures.

Fix (one of):
- Change `status_code=400` → `status_code=500` in the bare except.
- Narrow the catch: `except psycopg2.errors.ForeignKeyViolation` returns 400; re-raise everything else as 500.

Regression test: add a unit test mocking the cursor to raise a non-FK / non-Unique DB error (e.g. `psycopg2.errors.QueryCanceled`) and assert the response is 500, not 400.

### MED-B4-2 — baker-master hook `_REGISTER_RETRY_JITTER_LO/HI` constants lack unit suffix

File: `.claude/hooks/user-prompt-submit-confirm.py` (baker-master repo, branch `b4/baker-master-surface-6a-hook-retry-1`), constants block lines 65-66.

Issue: `_REGISTER_RETRY_JITTER_LO = 0.05` and `_REGISTER_RETRY_JITTER_HI = 0.15` are passed directly to `time.sleep()` (seconds). Variable names lack a unit suffix; constants block comment says nothing about units. A future maintainer editing them assuming milliseconds would set values causing Claude startup to block ~2 minutes (50-150 *seconds*). Tests stub `time.sleep` so this would not be caught by the test suite.

Fix: rename + add inline unit comment:

```python
# Before (lines 65-66):
_REGISTER_RETRY_JITTER_LO = 0.05
_REGISTER_RETRY_JITTER_HI = 0.15

# After:
_REGISTER_RETRY_JITTER_LO_S = 0.05  # seconds (50 ms)
_REGISTER_RETRY_JITTER_HI_S = 0.15  # seconds (150 ms)
```

And update the call site (~lines 240-242):
```python
time.sleep(random.uniform(
    _REGISTER_RETRY_JITTER_LO_S, _REGISTER_RETRY_JITTER_HI_S
))
```

Regression test: not strictly needed (rename + comment); existing retry tests will continue to pass.

### LOW non-blocking (not appended for fold)

- LOW-B4-1 (brisen-lab tests): code-reviewer agent could not locate tests/ directory at the expected local path; per B4 ship report `40 passed, 1 skipped (Surface 6a tests = 4/4)`, file exists on branch.
- LOW-B4-2 (baker-master test fixture): `hook_mod` fixture uses `scope="module"`; per-function `monkeypatch` of `hook_mod.time.sleep` could leak across tests in failure scenarios. Structural brittleness, not a present bug. Address in a future cleanup if it bites.

**Path forward:**
1. Apply MED-B4-1 on `b4/brisen-lab-surface-6a-partial-unique-index-1` (brisen-lab worktree at `~/bm-b4-brisen-lab/`)
2. Apply MED-B4-2 on `b4/baker-master-surface-6a-hook-retry-1` (baker-master worktree at `~/bm-b4/`)
3. Add regression test for MED-B4-1 (non-FK DB error → HTTP 500); MED-B4-2 needs no new test
4. Live pytest GREEN both repos (literal output, Lesson #52)
5. Re-fire focused gate chain on diffs only
6. Report new HEAD SHAs back to PL → AH1 PL autonomous-merges in mandatory order: brisen-lab #3 → baker-master #161 → vault #85 (vault stays unchanged; ready to merge any time after).

No autonomous polling. Stop after step 6 report.

**Other gates state (for context):**
- AH2 /security-review gate 2: PASS both PR #3 + PR #161 (no findings).
- Architect spot-check gate 3: paste-blocks in Director hand; not yet relayed.
- baker-vault PR #85: PL-reviewed PASS clean; no gate dispatch pending.

---

## Prior CODE_4 task (archive reference)
BRIEF_BRISEN_LAB_V2_BRIDGE_1 V0.3.7 — COMPLETE 2026-05-05. baker-master PR #157 squash-merged 2026-05-05T20:57:19Z (commit `57ab073`); brisen-lab PR #2 squash-merged 2026-05-05T20:57:08Z (commit `bc1e3e6`). All 4 gates cleared (B4 pytest + AH2 /security-review + architect + code-reviewer). `BRISEN_LAB_V2_ENABLED=false` stays on Render until Surface 6a (this brief) ships + Tier-B cutover Director-ratified. Mailbox hygiene rule applied — overwriting per `_ops/processes/b-code-dispatch-coordination.md` §3.
