---
status: PENDING
brief: briefs/BRIEF_CORTEX_TIER_B_RUNTIME_V1.md
trigger_class: TIER_B_DB_SCHEMA_PLUS_ATOMICITY_PLUS_EXTERNAL_SURFACE
dispatched_at: 2026-05-10
dispatched_by: ai-head-1 (AH1)
target: b3
director_ratification: D8 ratified 2026-05-10 via D3+D8 Triaga (Conservative caps locked); AID-resolved 7 clarifications 2026-05-10 (pool-wide, mixed-cost-source, dedicated-tier-b-pending, 00:00 UTC reset)
priority: P1
unblocks:
  - I5 (first Cortex auto-trigger cycle, STUCK since 2026-05-03)
  - B4 (6-phase loop runtime — adopts enforce_tier_b)
  - B5 (substrate push runtime — adopts enforce_tier_b)
expected_pr_count: 1 (baker-master)
expected_branch_name: b3/cortex-tier-b-runtime-v1
expected_complexity: medium (~6-8h)
mandatory_2nd_pass: TRUE  # Triggers #2 (DB schema/migrations/atomicity) + #3 (concurrency-ordering) + #4 (external-surface endpoint)
last_heartbeat: null
---

# CODE_3_PENDING — BRIEF_CORTEX_TIER_B_RUNTIME_V1 — 2026-05-10

**Brief:** `briefs/BRIEF_CORTEX_TIER_B_RUNTIME_V1.md` (read first — full spec, 6 fixes, copy-pasteable code blocks, test plan, ship gate)
**Working dir:** `~/bm-b3`
**Working branch:** `b3/cortex-tier-b-runtime-v1`
**Repo:** `vallen300-bit/baker-master`

## Summary

Build forward-looking Tier-B autonomous-action budget enforcement runtime. Caps: €100/action, €500/day, €2500/mo (pool-wide); reset 1st calendar month 00:00 UTC. 6 fixes:
1. Schema extension on `baker_actions` (6 new nullable columns) + 3 new tables (`tier_b_action_classes`, `tier_b_pending`, `tier_b_counter_resets`) + seed registry. Migration `migrations/20260510_baker_actions_tier_b_runtime.sql` + matching `_ensure_*` bootstrap update in `memory/store_back.py`.
2. `orchestrator/tier_b_runtime.py` — `enforce_tier_b(action) → Decision` singleton with SERIALIZABLE-txn counter check-and-pause.
3. `orchestrator/tier_b_ratify.py` — pause-handler + ratify card prep (visual reuse from GOLD card; separate workflow domain).
4. `triggers/tier_b_reset.py` + register in `triggers/embedded_scheduler.py` — APScheduler cron, day=1, hour=0, minute=0, timezone="UTC".
5. `outputs/dashboard.py` — `GET /api/admin/tier-b-status` audit endpoint.
6. Tests: `tests/test_tier_b_runtime.py` + `tests/test_tier_b_reset.py` + `tests/test_tier_b_status_endpoint.py` (PG-required, skip-if-no-TEST_DATABASE_URL pattern).

## Pre-requisites
- `baker_actions` table exists (bootstrap `memory/store_back.py:1036` — verified)
- GOLD ratify workflow exists (PR #66 — verified for visual template reuse)
- D8 caps ratified 2026-05-10
- `TEST_DATABASE_URL` env (CI ephemeral Neon branch — auto-provisioned)

## Acceptance criteria
- All 6 fixes implemented per spec.
- Migration creates 3 new tables + 6 new columns on baker_actions; bootstrap updated to match (Brief Standard #4).
- All caps enforce correctly (pytest scenarios in Fix 6 cover edge cases).
- Calendar-month reset fires at 1st 00:00 UTC (cron registered, verifiable in logs).
- `/api/admin/tier-b-status` returns valid JSON shape.
- No false-positive pauses (action below cap → PASS).
- No false-negative passes (action above cap → PAUSE_REQUIRED).
- Pool-wide isolation: AH1 spend visible to B3's enforce check.
- Singleton: `TierBRuntime._get_global_instance()` only; pre-push hook `scripts/check_singletons.sh` passes.
- All DB calls in try/except with rollback; all SELECTs have LIMIT.

## Ship gate
**Literal `pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v` output GREEN — no "pass by inspection."**

Plus full suite: `pytest` exit-0 (no regressions on existing baker_actions write paths).

## Mandatory review chain (4 gates per SKILL.md §Code-reviewer 2nd-pass Protocol)

This PR fires multiple triggers — full chain required pre-merge:

1. **Gate 1 — pytest GREEN** (B3 ships report w/ literal output)
2. **Gate 2 — AH2 `/security-review`** (atomicity + external-surface scrutiny)
3. **Gate 3 — picker-architect** (architectural soundness)
4. **Gate 4 — `feature-dev:code-reviewer` 2nd-pass** (mandatory: triggers #2 DB/migration/atomicity + #3 concurrency-ordering + #4 external-surface endpoint)

REQUEST_CHANGES on any FAIL or HIGH/CRITICAL findings. Re-fire chain on each fold-fix commit.

## Heartbeat policy (per SKILL.md §B-code stall chase)

Minimum heartbeat every 12h while actively building. Acceptable formats:
- Mailbox UPDATE entry in this file with ISO timestamp
- Ship-report file at `briefs/_reports/...`
- Commit-msg heartbeat on `b3/cortex-tier-b-runtime-v1` (`mailbox(b3): heartbeat <ISO> — <where>` pattern)

Two consecutive 12h misses → AH1 auto-surfaces stall to Director.

## Out of scope (do NOT implement)
- Wiring `enforce_tier_b()` into Cortex Phase 5 / B4 6-phase loop / B5 substrate push (those briefs adopt this runtime when they ship)
- Anthropic API token-cost cap (D4 risk action, AID owns, target 2026-05-31)
- Tier C definition (separate brief if needed)
- Slack push of ratify card actual-send (B3 prepares card payload + DB transitions; B4 wires Slack push)

## PL ship-report contract

End your chat ship report with a fenced PL paste-block per SKILL.md §"PL ship-report contract":

```
**TO: AH1-App PL**
- WHAT: <one-line summary>
- LINKS: <PR # / commit SHA / file paths / Render deploy ID>
- COST: <$X / time / N cycles, or "n/a">
- NEXT: <next blocker, dispatch, or "ready for next">
```

---

## UPDATE 2026-05-10T18:30Z — FOLD-FIX SCOPE (Path A ratified, AID via Director)

**Status:** RE-OPENED. Gate 3 (picker-architect) returned PASS-WITH-NITS; Gate 4 (`feature-dev:code-reviewer`) returned FAIL. AH1 verified findings against shipped source on `origin/b3/cortex-tier-b-runtime-v1` @ `c5c5e41` — 2 genuine HIGHs to fold, 2 reviewer false-positives refuted.

**Director ratified Path A 2026-05-10:** defer atomicity redesign to B4 brief; ship fold of other items; unblock cascade.

**Continue on same branch `b3/cortex-tier-b-runtime-v1`. PR #179 stays open — fold commits append.**

### Fold scope (5 items, ~30 min)

1. **Atomicity-claim docstring honesty** — replace dishonest claim at `orchestrator/tier_b_runtime.py:175-179` (the `enforce()` method docstring currently reads *"cost-resolve, counter-read, and pending-insert run inside one SERIALIZABLE transaction… two simultaneous committers can't both see headroom and together exceed cap"*). Replace with:

   ```
   """Decide PASS or PAUSE_REQUIRED for a candidate Tier-B action.

   V1 atomicity scope: single-call atomicity only. The SERIALIZABLE
   transaction protects the read-then-insert sequence INSIDE one
   enforce() call. It does NOT protect pool-wide atomicity across
   concurrent callers — that requires the caller-pattern in B4
   (caller's baker_actions INSERT must run inside the same txn).
   See FIXME(B4) below.
   """
   ```

2. **Add FIXME comment** inside `enforce()` body (top of method, after the docstring):

   ```python
   # FIXME(B4): close atomicity gap — pool-wide cap evasion possible when
   # concurrent callers materialize. Two enforcers reading €499 day-total
   # can both PASS because Postgres SSI sees no rw-conflict (PASS path
   # commits without writing to baker_actions). Closure ratified Path A
   # 2026-05-10; B4 brief carries hard acceptance criterion. See
   # _ops/briefs/_precursor/B4_PRECURSOR_ATOMICITY_CLOSURE.md.
   ```

3. **Negative `self_cost_eur` guard** at `orchestrator/tier_b_runtime.py` `_resolve_cost()` (around lines 83-90). Add after the `if action.self_cost_eur is None` check, before the `return`:

   ```python
   if action.self_cost_eur < 0:
       raise ValueError(
           f"self_cost_eur must be non-negative (got {action.self_cost_eur}); "
           f"negative values would bypass daily/monthly cap math"
       )
   ```

   **Plus 1 unit test** in `tests/test_tier_b_runtime.py` confirming the guard fires:

   ```python
   def test_novel_class_negative_self_cost_rejected():
       action = TierBAction(
           action_class="novel:cap_evasion_attempt",
           committer_agent="b3",
           payload={"test": "negative_cost"},
           self_cost_eur=-50.0,
       )
       with pytest.raises(ValueError, match="non-negative"):
           enforce_tier_b(action)
   ```

   (No `@requires_pg` needed — this test exits before any DB call. Place near `test_novel_class_requires_self_cost`.)

4. **Remove `_current_totals()` dead code** — `orchestrator/tier_b_runtime.py` lines 124-167 (the method body). `enforce()` inlines the same SUM queries; `/api/admin/tier-b-status` also inlines them; nothing calls `_current_totals()`. Delete the method.

5. **`_resolve_cost()` docstring honesty** (architect nit) — `_resolve_cost()` opens its own connection at default isolation and runs OUTSIDE the SERIALIZABLE block in `enforce()`. Add a brief docstring note:

   ```
   """Resolve (cost_eur, source_tag) for an action.

   Runs against a separate pooled connection at default isolation —
   NOT inside enforce()'s SERIALIZABLE txn. Registry rarely changes
   during a cycle so the read-skew window is acceptable for V1.
   """
   ```

### Explicit refutation block (do NOT touch these)

Reviewer flagged two HIGHs that don't exist in shipped source. AH1 verified against `origin/b3/cortex-tier-b-runtime-v1`. **Do not chase these:**

- **"`check_singletons.sh` missing TierBRuntime check"** — REFUTED. Script DOES include the TierBRuntime block at lines 31-42 (added per ship report risk #4). No change needed.
- **"NameError in `test_tier_b_reset.py` finally block"** — REFUTED. `cur.close()` is inside the `try` block; `finally:` only calls `tier_b_test_store._put_conn(conn)`. No `cur` reference in finally. No NameError possible. No change needed.

### Out of scope for this fold

- **Atomicity redesign** — deferred to B4 per Path A ratification. Do NOT redesign `enforce()` signature; keep SERIALIZABLE infra in place for V2.
- **AH2 `/security-review`** — held by AH1 until fold lands. Don't dispatch it; AH1 will fire after fold confirmed.
- **Endpoint DRY refactor** (architect Low #6 — `/api/admin/tier-b-status` re-implements counter queries) — defer; cleaning this in the same brief as #4 dead-code removal would mean callers reach for a method that doesn't exist. If `_current_totals()` is deleted, no caller can reuse it. Skip.
- **Concurrent-commit test** (architect Med #3 coverage gap) — would expose the atomicity gap; deferred to B4 closure with the redesign.

### Ship gate for fold

Literal `pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v` GREEN. Expect 16 passing (15 existing + 1 new negative-cost test). Plus full suite: no new failures.

Plus `bash scripts/check_singletons.sh` GREEN.

### AID-side already filed (do not re-file)

- Risk register D5 entry: Tier B atomicity gap (open until B4 merges)
- Tracker B3 row tagged "atomicity-debt → B4"
- B4 precursor note: `_ops/briefs/_precursor/B4_PRECURSOR_ATOMICITY_CLOSURE.md` (hard acceptance criterion for B4 — cannot merge without closure)

### Ship report for fold

Append a `## UPDATE` section to your existing `briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md` with:
- New commits (hashes)
- Literal pytest output (showing 16/16 + new test name)
- Literal `check_singletons.sh` output
- Confirmation that all 5 fold items shipped + 2 refutations honored (untouched)

End with the PL ship-report paste-block per SKILL.md.

### Heartbeat — same policy

12h cadence. ~30 min expected, so probably one heartbeat at fold-complete + ship-report-append.

---

## UPDATE 2026-05-10T19:00Z — MICRO-FOLD (consistency, AH1)

**Status:** RE-OPENED for one 2-line edit. Fold #1 (commit `a996f53`) shipped clean — pytest 16/16, check_singletons.sh OK, refutations honored. B3 surfaced an honest gap I should have caught when writing the fold scope: I line-cited the **method** docstring at `tier_b_runtime.py:175-179` but missed the **module-level** docstring at `tier_b_runtime.py:20-24` which carries the same dishonest atomicity claim verbatim.

**Accept B3's test-fixture deviation** (Flag 1): adding `clean_baker_actions` to `test_novel_class_negative_self_cost_rejected` matches the sibling `test_novel_class_requires_self_cost` pattern because `TierBRuntime._get_global_instance()` triggers SentinelStoreBack singleton init which demands Voyage creds. Inline comment is clear. No change needed on that test.

### Micro-fold scope (1 item, ~5 min)

Replace `orchestrator/tier_b_runtime.py` lines 20-24 (module-level docstring atomicity paragraph):

**Current (dishonest):**
```
Atomicity: cost-resolve, counter-read, and pending-insert all run inside a
single SERIALIZABLE transaction so two simultaneous committers can't both
see headroom and together exceed cap. Postgres surfaces serialization
failures as exceptions; the caller is expected to retry.
```

**Replace with:**
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

### Ship gate for micro-fold

- `pytest tests/test_tier_b_runtime.py tests/test_tier_b_reset.py tests/test_tier_b_status_endpoint.py -v` — same 16/16 GREEN as fold #1
- `bash scripts/check_singletons.sh` — OK
- Full suite — no new failures (baseline still 81 failed identical set)

### Ship report

Append a short `## UPDATE 2 (micro-fold)` section to `briefs/_reports/B3_cortex_tier_b_runtime_v1_20260510.md` with the new commit hash + literal pytest one-liner. End with PL paste-block.

### Why this matters

Path A ratification was "ship fold of other items honestly." Method docstring honest + module docstring still dishonest = a fresh reader opening the file sees the wrong mental model first. Closing this makes the file internally consistent before AH2 `/security-review` runs.

### After this lands

AH1 fires AH2 `/security-review` on the post-micro-fold diff. Don't wait — fold + report + push, then idle.


