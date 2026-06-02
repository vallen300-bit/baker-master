# CODE_1_PENDING — BUS_AUTOWAKE_TEST_HARDEN_1

status: COMPLETE
completed: 2026-06-02 — PR #57 merged 2d0fc42 (squash). G0 codex PASS-WITH-NIT #1609 + G1 lead static PASS (diff = tests/test_bus_autowake.py only; full _reset_wake_state clears all 6 dicts; Fix 1b backdate-trick preserves first-fire sentinel) + G2/G3 N/A. Evidence: isolated 8/8 + targeted containment+autowake 5x = 0 autowake failures. FOLLOW-UP (separate): containment suite itself intermittently flaky under remote-Neon latency (b1 #1620) — env/test-infra, not this diff.
dispatched_by: lead
ship-report recipient: lead
repo: brisen-lab (your brisen-lab checkout, e.g. ~/bm-b1-brisen-lab)
task class: test reliability (NO production code change)
gate plan: G0 codex (brief PASS-WITH-NIT #1609) → G1 lead static → G2 security-review N/A (test-only, codex confirmed) → merge
bus topics: ship/bus-autowake-test-harden-1

## Context

Canonical brief (READ IN FULL FIRST): `~/baker-vault/_ops/briefs/BRIEF_BUS_AUTOWAKE_TEST_HARDEN_1.md` (v2, commit on baker-vault main; codex G0 PASS-WITH-NIT #1609 — all 3 prior REVISE findings + the cache nit folded).

The autonomous loop is ARMED in prod. `tests/test_bus_autowake.py` (6 cases) passes 8/8 isolated but ~5 fail under full-suite load (cowork-ah1 #1597). No CI on brisen-lab, so this flakiness silently erodes trust in the suite guarding an armed prod autonomy system.

## Problem

Full-suite flake = LEAKED module-level wake-suppression state across test order, NOT a queue race. `tests/test_bus_autowake.py:29-33` `_reset_debounce()` clears only `bus._last_wake_emit_at`; the other five `bus.py` module dicts (`_wake_count_by_slug`, `_cap_alert_emitted_at`, `_recent_edges`, `_loop_edges_5min`, `_auto_disabled_until`) leak from earlier wake-firing tests (e.g. the containment suite) and suppress the wake a later case expects → `assert len(wakes)==1` sees 0.

## Files Modified

`tests/test_bus_autowake.py` ONLY — replace `_reset_debounce()` with full `_reset_wake_state()` clearing all SIX dicts (mirror `tests/test_bus_autowake_containment.py:32-42` `_reset_containment_state`), called at top of every test. Optionally add the defensive poll helper. Absence tests keep original sender/kind.

Do NOT touch: `bus.py`, `app.py` (production wake path is correct); `tests/test_bus_autowake_containment.py` (the reference pattern).

## Quality Checkpoints (load-bearing — codex #1605/#1609)

1. PRIMARY fix = `_reset_wake_state()` clears all six `bus.py` module dicts; called at top of every test. EXPLICIT AC.
2. Do NOT clear `bus._CACHE` (that's the /api/v2 response cache, unrelated). Master gate uses `bus._master_flag_cache`, already reset by conftest `fresh_db` — no action needed (codex #1609).
3. Root cause is leaked module state, NOT a queue race (broadcast is synchronous before response — bus.py:536-542 + app.py:531-538). Any poll helper is documented defensive only.
4. Absence tests keep `kind="broadcast"`, `to=["*"]`, sender `lead` (don't narrow contract).
5. Only `tests/test_bus_autowake.py` changes (git diff confirms).

## Verification

- Isolated: `python3 -m pytest tests/test_bus_autowake.py -v` → 6/6 (literal output).
- **Full-suite reproduce-then-confirm (the AC that matters):** run the FULL suite 5×; show 0 `test_bus_autowake` failures across all 5. The 1 unrelated pre-existing failure cowork-ah1 noted may remain — name it, out of scope. Literal output.
- `git diff --name-only` shows only the one test file.

## Constraints

Test-only; no production code/config touched → no deploy, no post-deploy AC. No `--no-verify`. Ship to topic `ship/bus-autowake-test-harden-1`; do NOT merge (lead gates). Ship report answers the done rubric (terminal state = 0 wake-test failures across 5 full-suite runs).
