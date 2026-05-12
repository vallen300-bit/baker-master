---
status: COMPLETE
completed_at: 2026-05-12T23:22:38+00:00
pr: 196
pr_url: https://github.com/vallen300-bit/baker-master/pull/196
merge_commit: 0eba411
head_sha: 559e4c089bf0526da58949a12a8790b4353ec8b2
ship_report: briefs/_reports/B1_vault_mirror_thread_lifecycle_hygiene_ship_20260513.md
ship_gate_pytest: GREEN (tests/test_vault_mirror.py 12/12)
gates_cleared:
  ah1_static: PASS
  picker_architect: PASS-WITH-NITS (3 LOW)
  code_reviewer_2nd_pass: PASS-WITH-NITS (2 LOW, 1 dup with architect)
  security_review: PASS
nit_followups_low:
  - ".githooks/pre-commit:45 — stale comment text says .githooks/ should say pre-commit"
  - "vault_mirror.py:295 — add 1-line comment that dual-alive window is bounded by _git_lock"
  - "vault_mirror.py:283 — rename _sync_thread_stop -> _current_stop_event for clarity (optional)"
  - "tests/test_vault_mirror.py:225 — time.sleep(0.02) -> threading.Event signal (CI flake hardening)"
bus_post_message_id_ship: 191
brief: briefs/BRIEF_VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1.md
trigger_class: TIER_B_CONCURRENCY_PRIMITIVE_HYGIENE
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b1
director_ratification: Director 2026-05-13 "yes" (post-brief-draft surface)
priority: P2
phase: 1 of 1
expected_pr_count: 1 (baker-master)
expected_branch: b1/vault-mirror-thread-lifecycle-hygiene-1
expected_complexity: low (~1.5h B-code, three small fixes)
mandatory_2nd_pass: TRUE  # concurrency primitive (Fix 1 + Fix 2 touch threading lock ordering); follows §Code-reviewer 2nd-pass Protocol §When the protocol FIRES item 3
hard_ship_gate: |
  Literal `pytest tests/test_vault_mirror.py -v` GREEN output required in ship report.
  All existing 9 tests + 3 new tests (test_stop_sync_thread_does_not_block_concurrent_start,
  test_per_thread_stop_event_isolation, test_mirror_status_toctou_safety) MUST pass.
  No "by inspection" — literal output required.
scope:
  files_modify:
    - vault_mirror.py (stop_sync_thread atomic-swap + _sync_loop signature + mirror_status snapshot)
    - .githooks/pre-commit (Part 3 exclusion narrowing)
    - tests/test_vault_mirror.py (3 new tests)
  files_donottouch:
    - outputs/dashboard.py
    - triggers/embedded_scheduler.py
    - briefs/_reports/B1_vault_mirror_*
    - pre-commit Parts 1 + 2 (out of scope)
    - RETIRED_IDS_REGEX itself (correct as-is)
anchors:
  - PR #195 architect 2nd-pass NITs (L1 atomic-swap + L2 TOCTOU)
  - PR #194 PASS-WITH-NITS MEDIUM (.githooks/ exclusion narrowing)
  - PINNED §I (deleted on dispatch; preserved in handover archive)
heartbeat_cadence: 12h while in_progress per agent-bus-posting-contract.md
---

B1 — bundled hygiene follow-up. Three small fixes from PRs #194 + #195.

Read `briefs/BRIEF_VAULT_MIRROR_THREAD_LIFECYCLE_HYGIENE_1.md` for full spec.

**Fix 1 (L1, atomic-swap)**: `stop_sync_thread` race window during concurrent start. Architect's caveat cited verbatim — naïve release-lock-before-join introduces a different race. Brief recommends per-thread stop event for race-free implementation. If you see a simpler correct pattern, surface it via blocker bus-post before implementing — don't silently improvise.

**Fix 2 (L2, TOCTOU snapshot)**: `mirror_status` reads `_sync_thread` twice without lock. Local snapshot fix. No lock needed in `mirror_status` — GIL-atomic read sufficient.

**Fix 3 (MEDIUM, hook narrowing)**: `.githooks/pre-commit` Part 3 exclusion regex change from `^\.githooks/` to `^\.githooks/pre-commit$`. Plus error message string update at line 65. Manual hook verification (3 cases) — no formal hook test harness expected.

**Ship gate**: literal pytest output. **Heartbeat**: bus-post every 12h while active. **Bus-post on ship**: `ship/vault-mirror-thread-lifecycle-hygiene-1` to `lead` with PR link + commit SHA + pytest literal output + 4-gate readiness.

**Gate chain on ship** (AH1 will fire): AH2 static + /security-review + picker-architect + mandatory_2nd_pass (`feature-dev:code-reviewer`). All four must clear before merge.
