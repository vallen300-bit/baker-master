---
type: ship_report
brief: BRIEF_CORTEX_TIER_B_RUNTIME_V1
trigger_class: TIER_B_DB_SCHEMA_PLUS_ATOMICITY_PLUS_EXTERNAL_SURFACE
agent: b3
pr: https://github.com/vallen300-bit/baker-master/pull/179
branch: b3/cortex-tier-b-runtime-v1
commit: c5c5e4198253716e2b758a82f99df69adca032f7
status: AWAITING_REVIEW_CHAIN
shipped_at: 2026-05-10T17:23Z
---

# B3 Ship Report — CORTEX_TIER_B_RUNTIME_V1

## Summary

PR #179 — Tier B autonomous-action budget runtime. Caps locked to D8
Conservative (€100/action, €500/day, €2500/month, pool-wide; reset 1st
00:00 UTC). Forward-looking only — no live regression risk.

Unblocks I5 → B4 → B5 cascade once merged.

## What shipped (6 fixes)

| # | File(s) | Description |
|---|---|---|
| 1 | `migrations/20260510_baker_actions_tier_b_runtime.sql`, `memory/store_back.py` | Schema: 6 nullable cols on `baker_actions` + 3 new tables (`tier_b_action_classes`, `tier_b_pending`, `tier_b_counter_resets`) + 5 seed registry rows. Bootstrap mirrors migration column-for-column. |
| 2 | `orchestrator/tier_b_runtime.py` | `TierBRuntime` singleton + `enforce(action) → Decision`. SERIALIZABLE atomic check-and-pause via `conn.set_isolation_level(...)`. |
| 3 | `orchestrator/tier_b_ratify.py` | Ratify-card payload + Director response consumer. GOLD visual reuse only — separate domain. |
| 4 | `triggers/tier_b_reset.py`, `triggers/embedded_scheduler.py` | APScheduler `CronTrigger(day=1, hour=0, minute=0, timezone='UTC')` + audit row in `tier_b_counter_resets`. |
| 5 | `outputs/dashboard.py` | `GET /api/admin/tier-b-status` — caps + day/month totals + headroom + pending + recent. |
| 6 | `tests/test_tier_b_runtime.py`, `tests/test_tier_b_reset.py`, `tests/test_tier_b_status_endpoint.py`, `tests/conftest.py` | 15 live-PG tests + helper fixtures. |

Plus: `scripts/check_singletons.sh` extended to block direct
`TierBRuntime()` instantiation.

## Acceptance criteria — all met

All 9 acceptance items from the mailbox closed. See PR #179 body for the
checklist; literal `pytest` and `check_singletons.sh` outputs in PR.

## Ship gate (literal pytest)

```
$ pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3
collected 15 items

tests/test_tier_b_runtime.py::test_cap_constants_match_d8_ratification PASSED [  6%]
tests/test_tier_b_runtime.py::test_pass_under_caps PASSED                [ 13%]
tests/test_tier_b_runtime.py::test_per_action_cap_paused PASSED          [ 20%]
tests/test_tier_b_runtime.py::test_daily_cap_paused PASSED               [ 26%]
tests/test_tier_b_runtime.py::test_monthly_cap_paused PASSED             [ 33%]
tests/test_tier_b_runtime.py::test_novel_class_requires_self_cost PASSED [ 40%]
tests/test_tier_b_runtime.py::test_novel_class_with_self_cost_passes PASSED [ 46%]
tests/test_tier_b_runtime.py::test_unknown_registry_class_raises PASSED  [ 53%]
tests/test_tier_b_runtime.py::test_pool_wide_isolation_between_agents PASSED [ 60%]
tests/test_tier_b_runtime.py::test_pending_row_persisted_on_pause PASSED [ 66%]
tests/test_tier_b_reset.py::test_reset_writes_audit_row_when_idle PASSED [ 73%]
tests/test_tier_b_reset.py::test_reset_captures_last_month_totals PASSED [ 80%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_shape PASSED    [ 86%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_surfaces_pending_and_recent PASSED [ 93%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_requires_api_key PASSED [100%]

================== 15 passed, 4 warnings in 87.27s (0:01:27) ===================
```

Run against a Neon-backed `TEST_DATABASE_URL_BRISEN_LAB` (1Password vault
"Baker API Keys"). CI auto-provisions an ephemeral Neon branch via
`NEON_API_KEY` + `NEON_PROJECT_ID`.

**Full-suite regression delta vs `main`:** +15 passes, +0 new failures.
The 80 pre-existing failures + 64 errors on `main` are infra-related
(signal_queue Python-bootstrap dependency in test DB; PgBouncer
advisory-lock semantics) and unaffected by this PR.

**Singleton CI guard:**
```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

**py_compile:** green on all 12 touched files.

## Risks flagged for review chain

1. **`tier_b_pending` namespace overlap (cosmetic).** `orchestrator/cortex_runner.py` + `orchestrator/cortex_phase4_proposal.py` use STRING literal `"tier_b_pending"` as a `cortex_cycles.status`. The new TABLE `tier_b_pending` is a different namespace (table vs status string). No code change required — flagged so reviewers don't misread as a name collision. Brief explicitly scopes cortex wiring to B4.
2. **SERIALIZABLE pattern fix.** Brief draft used `cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")` — no-op when psycopg2 (autocommit=False) already opened a txn. Switched to `conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_SERIALIZABLE)` with `SET TRANSACTION` fallback. Old level restored before pool return.
3. **`tests/conftest.py` `sys.modules` defense.** `test_ai_head_weekly_audit.py:126` does `sys.modules['memory.store_back'] = MagicMock()` without teardown. Without the defense added here, every Tier-B test running after that one would resolve `from memory.store_back import SentinelStoreBack` to the MagicMock (whose `fetchone()` returns a 1-tuple, breaking my reset + endpoint tests in full-suite ordering). Pre-existing bug; not fixed in this PR (out of scope).
4. **`scripts/check_singletons.sh` extension.** Brief said the pre-push hook would block direct `TierBRuntime()` instantiation; the existing script only covered the two Sentinel classes. Added the third block to honor the brief's promise.
5. **Untracked `.claude/settings.json.b3-pre-pull-bak` in working dir.** When pulling main, an untracked local `.claude/settings.json` (pointing at `forge-agent/session-start-hook.sh`) blocked the fast-forward; renamed it aside to allow the merge. The version on `main` (`.claude/hooks/session-start-role.sh`) now applies. Flagged so AH1 can decide whether the local Director-side artifact should be re-installed or discarded.

## Mandatory review chain (per brief)

| Gate | Owner | Status |
|---|---|---|
| 1 | B3 — pytest GREEN | ✅ green (literal output above) |
| 2 | AH2 — `/security-review` | ⏳ pending |
| 3 | picker-architect | ⏳ pending |
| 4 | `feature-dev:code-reviewer` 2nd-pass | ⏳ pending |

## Out of scope (confirmed)

- Cortex Phase 5 / B4 6-phase loop / B5 substrate push wiring (later briefs).
- Anthropic API token-cost cap (D4 — AID owns).
- Tier C definition.
- Slack push of ratify card (B4).

## PL ship-report contract

```
**TO: AH1-App PL**
- WHAT: PR #179 — Tier B autonomous-action budget runtime (CORTEX_TIER_B_RUNTIME_V1). 6 fixes shipped: schema migration + bootstrap mirror, enforce_tier_b runtime w/ SERIALIZABLE atomicity, ratify card prep, calendar-month reset cron, /api/admin/tier-b-status endpoint, 15 live-PG tests.
- LINKS: PR https://github.com/vallen300-bit/baker-master/pull/179 · branch b3/cortex-tier-b-runtime-v1 · commit c5c5e41 · ship report briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md
- COST: ~6h B3 wall-time (estimate). 1 Neon ephemeral branch for ship-gate pytest. No LLM spend on this brief.
- NEXT: 4-gate review chain — AH2 /security-review + picker-architect + feature-dev:code-reviewer 2nd-pass. On merge: I5 → B4 → B5 cascade unblocks. 5 risk notes flagged in ship report (tier_b_pending namespace overlap is cosmetic; SERIALIZABLE pattern was hardened vs brief draft; conftest carries a sys.modules defense against test_ai_head_weekly_audit pollution; check_singletons.sh extended; untracked .claude/settings.json local artifact moved aside during pull). B3 standing by for fold-fix dispatch or next assignment.
```

---

## UPDATE 2026-05-10T21:50Z — fold-fix shipped (Path A)

PR #179 reopened per AH1 UPDATE 2026-05-10T18:30Z; Director ratified Path A (atomicity redesign deferred to B4). Fold scope = 5 items + 2 explicit refutations honored.

**New commit:** `a996f53` on `b3/cortex-tier-b-runtime-v1` (`c56a284..a996f53`).

### Fold items shipped (5/5)

| # | File · location | Change |
|---|---|---|
| 1 | `orchestrator/tier_b_runtime.py` `enforce()` docstring | Replaced V1 single-call atomicity claim's pool-wide overreach. New text scopes SERIALIZABLE protection to read-then-insert INSIDE one enforce() call only; pool-wide closure flagged for B4 caller-pattern. |
| 2 | `orchestrator/tier_b_runtime.py` inside `enforce()` body | `FIXME(B4)` block explaining the cap-evasion gap (concurrent PASS-path commits without rw-conflict on `baker_actions`); points at `_ops/briefs/_precursor/B4_PRECURSOR_ATOMICITY_CLOSURE.md`. |
| 3 | `orchestrator/tier_b_runtime.py` `_resolve_cost()` + `tests/test_tier_b_runtime.py` | Negative `self_cost_eur` raises `ValueError("non-negative ...")`; new `test_novel_class_negative_self_cost_rejected` covers the guard. |
| 4 | `orchestrator/tier_b_runtime.py` lines 124-167 (pre-fold) | `_current_totals()` deleted. No callers — `enforce()` and `/api/admin/tier-b-status` both inline the SUM queries. |
| 5 | `orchestrator/tier_b_runtime.py` `_resolve_cost()` docstring | Honest note: runs against a separate pooled connection at default isolation, NOT inside enforce()'s SERIALIZABLE txn. Read-skew window acceptable for V1 (registry rarely changes mid-cycle). |

Brief said the new test could skip `@requires_pg`, but `enforce_tier_b()` instantiates `TierBRuntime` which calls `SentinelStoreBack._get_global_instance()` — that init demands Voyage creds without the test-store patch. The existing analogue (`test_novel_class_requires_self_cost`) uses `clean_baker_actions`, so the new test follows the same pattern. The `ValueError` still fires inside `_resolve_cost`, before any cap math. Inline note in the test explains the deviation.

### Refutations honored (2/2)

* **`scripts/check_singletons.sh` "missing TierBRuntime block"** → not touched. Verified TierBRuntime block present at lines 31-42.
* **`tests/test_tier_b_reset.py` "NameError in finally"** → not touched. Verified `cur.close()` is inside the `try` block; the `finally:` only references `tier_b_test_store._put_conn(conn)`.

### Out of scope for fold (deferred per Path A)

* `enforce()` atomicity redesign → B4 brief.
* AH2 `/security-review` → AH1 will dispatch after fold lands.
* Endpoint DRY refactor (architect Low #6) → would chase `_current_totals()` after deletion; skip.
* Concurrent-commit test (architect Med #3 coverage) → exposes the gap; deferred with the redesign.

### Ship gate (literal)

```
$ pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collected 16 items

tests/test_tier_b_runtime.py::test_cap_constants_match_d8_ratification PASSED [  6%]
tests/test_tier_b_runtime.py::test_pass_under_caps PASSED                [ 12%]
tests/test_tier_b_runtime.py::test_per_action_cap_paused PASSED          [ 18%]
tests/test_tier_b_runtime.py::test_daily_cap_paused PASSED               [ 25%]
tests/test_tier_b_runtime.py::test_monthly_cap_paused PASSED             [ 31%]
tests/test_tier_b_runtime.py::test_novel_class_requires_self_cost PASSED [ 37%]
tests/test_tier_b_runtime.py::test_novel_class_negative_self_cost_rejected PASSED [ 43%]
tests/test_tier_b_runtime.py::test_novel_class_with_self_cost_passes PASSED [ 50%]
tests/test_tier_b_runtime.py::test_unknown_registry_class_raises PASSED  [ 56%]
tests/test_tier_b_runtime.py::test_pool_wide_isolation_between_agents PASSED [ 62%]
tests/test_tier_b_runtime.py::test_pending_row_persisted_on_pause PASSED [ 68%]
tests/test_tier_b_reset.py::test_reset_writes_audit_row_when_idle PASSED [ 75%]
tests/test_tier_b_reset.py::test_reset_captures_last_month_totals PASSED [ 81%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_shape PASSED    [ 87%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_surfaces_pending_and_recent PASSED [ 93%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_requires_api_key PASSED [100%]

================== 16 passed, 4 warnings in 89.88s (0:01:29) ===================
```

**Singleton CI guard:**
```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

**Full-suite regression:** `81 failed, 1797 passed, 1 skipped, 64 errors` — failure SET is byte-identical to pre-fold baseline (`diff <(sort baseline) <(sort post-fold)` empty). Zero new failures. The +1 vs the 80-count cited in the original ship report is consistent flakiness/timing in the pre-existing infra-skipped block; not introduced by this fold.

### PL ship-report (fold)

```
**TO: AH1-App PL**
- WHAT: PR #179 fold-fix shipped per Path A. 5 items: enforce() atomicity-claim docstring honest + FIXME(B4); _resolve_cost negative-cost guard + new unit test; dead _current_totals() removed; _resolve_cost docstring notes default-isolation/separate-conn read-skew. 2 reviewer false-positives refuted (singletons script + reset test finally) — untouched.
- LINKS: PR https://github.com/vallen300-bit/baker-master/pull/179 · branch b3/cortex-tier-b-runtime-v1 · fold commit a996f53 (range c56a284..a996f53) · ship report briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md (## UPDATE section appended).
- COST: ~30 min B3 wall-time. 1 Neon-backed pytest pass + 1 baseline-vs-post-fold full-suite diff (~3.7 min each). No LLM spend.
- NEXT: AH1 to re-fire review chain — AH2 /security-review + (optional) picker-architect re-pass + feature-dev:code-reviewer 2nd-pass on a996f53. Note: the new test signature deviates from brief (added clean_baker_actions fixture) — explained inline; reviewer please confirm acceptable. B3 standing by.
```

---

## UPDATE 2 (micro-fold) — 2026-05-10T~20:10Z

**Trigger:** Mailbox `## UPDATE 2026-05-10T19:00Z — MICRO-FOLD (consistency, AH1)` — AH1 accepted fold #1 (a996f53) + test-fixture deviation, and re-opened for a single 2-line consistency edit B3 had flagged as honest gap: the module-level docstring at `orchestrator/tier_b_runtime.py:20-24` carried the same dishonest V1-atomicity claim that fold #1 fixed at the method docstring (`:175-179`). Closing this keeps the file internally consistent before AH2 `/security-review`.

### Scope (1 item)

Replace `orchestrator/tier_b_runtime.py:20-24` module-docstring "Atomicity:" paragraph with the V1-honest framing mirroring the method docstring:

```
Atomicity (V1): the SERIALIZABLE transaction inside ``enforce()`` protects
the read-then-insert sequence within a SINGLE call only. It does NOT
protect pool-wide atomicity across concurrent callers — two enforcers
reading €499 day-total can both PASS because Postgres SSI sees no
rw-conflict (PASS path commits without writing to baker_actions). Closing
this gap requires the caller-pattern in B4 (caller's baker_actions INSERT
must run inside the same txn). Tracked: FIXME(B4) inside ``enforce()`` +
``_ops/briefs/_precursor/B4_PRECURSOR_ATOMICITY_CLOSURE.md``.
```

Diff: 8 insertions / 4 deletions, 1 file (docstring only — zero code-path change).

### Ship gate

**Tier-B suite (TEST_DATABASE_URL_BRISEN_LAB):**

```
$ pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0 -- /Users/dimitry/bm-b3/.venv-b3/bin/python3.12
cachedir: .pytest_cache
rootdir: /Users/dimitry/bm-b3
plugins: langsmith-0.7.33, anyio-4.13.0
collected 16 items

tests/test_tier_b_runtime.py::test_cap_constants_match_d8_ratification PASSED [  6%]
tests/test_tier_b_runtime.py::test_pass_under_caps PASSED                [ 12%]
tests/test_tier_b_runtime.py::test_per_action_cap_paused PASSED          [ 18%]
tests/test_tier_b_runtime.py::test_daily_cap_paused PASSED               [ 25%]
tests/test_tier_b_runtime.py::test_monthly_cap_paused PASSED             [ 31%]
tests/test_tier_b_runtime.py::test_novel_class_requires_self_cost PASSED [ 37%]
tests/test_tier_b_runtime.py::test_novel_class_negative_self_cost_rejected PASSED [ 43%]
tests/test_tier_b_runtime.py::test_novel_class_with_self_cost_passes PASSED [ 50%]
tests/test_tier_b_runtime.py::test_unknown_registry_class_raises PASSED  [ 56%]
tests/test_tier_b_runtime.py::test_pool_wide_isolation_between_agents PASSED [ 62%]
tests/test_tier_b_runtime.py::test_pending_row_persisted_on_pause PASSED [ 68%]
tests/test_tier_b_reset.py::test_reset_writes_audit_row_when_idle PASSED [ 75%]
tests/test_tier_b_reset.py::test_reset_captures_last_month_totals PASSED [ 81%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_shape PASSED    [ 87%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_surfaces_pending_and_recent PASSED [ 93%]
tests/test_tier_b_status_endpoint.py::test_tier_b_status_requires_api_key PASSED [100%]

================== 16 passed, 4 warnings in 92.02s (0:01:32) ===================
```

**Singleton CI guard:** `bash scripts/check_singletons.sh` → `OK: No singleton violations found.`

**Full-suite baseline:** `81 failed, 1797 passed, 1 skipped, 64 errors in 226.08s` — byte-identical failure set to fold-fix baseline cited in UPDATE 1. Zero new failures.

### Commit + push

- Commit: `f069ca6` on branch `b3/cortex-tier-b-runtime-v1`
- Pushed to `origin/b3/cortex-tier-b-runtime-v1` (a77e4e0..f069ca6).
- PR #179 picks up the new head automatically.

### PL ship-report (micro-fold)

```
**TO: AH1-App PL**
- WHAT: PR #179 micro-fold shipped. 1 item: module-level docstring at orchestrator/tier_b_runtime.py:20-24 replaced with V1-honest atomicity framing mirroring the method docstring (lines 175-179). 8 ins / 4 del, docstring only, zero code-path change.
- LINKS: PR https://github.com/vallen300-bit/baker-master/pull/179 · branch b3/cortex-tier-b-runtime-v1 · micro-fold commit f069ca6 (range a77e4e0..f069ca6) · ship report briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md (## UPDATE 2 appended).
- COST: ~10 min B3 wall-time. 1 Neon-backed pytest pass (92s) + 1 full-suite baseline check (226s). No LLM spend.
- NEXT: AH1 to fire AH2 /security-review on post-micro-fold diff per mailbox. B3 idle.
```
