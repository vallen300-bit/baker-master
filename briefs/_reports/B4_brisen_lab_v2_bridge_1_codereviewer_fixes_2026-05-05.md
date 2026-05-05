---
brief: BRIEF_BRISEN_LAB_V2_BRIDGE_1 (V0.3.6)
builder: b4
phase: code-reviewer fix-up (post `13212ff`)
date: 2026-05-05
status: ready_for_re_review
brisen_lab_branch: b4/brisen-lab-v2-bridge-1
brisen_lab_head: 44b3697
brisen_lab_prev_head: 13212ff
brisen_lab_pr: https://github.com/vallen300-bit/brisen-lab/pull/1
baker_master_branch: b4/brisen-lab-v2-bridge-1
baker_master_head: (unchanged this round — mailbox-only commit pending)
baker_master_pr: (pending — paired MCP-tools side, ships AFTER brisen-lab merge per ratification 2026-05-03)
---

# B4 ship report — BRIEF_BRISEN_LAB_V2_BRIDGE_1 code-reviewer fix-up

## What changed (from `13212ff` to `44b3697`)

`feature-dev:code-reviewer` pass on `13212ff` returned 1 HIGH + 3 MEDIUM —
findings prior gates (static / security / architect) all missed. Path A
per Director "Follow your recommendation" 2026-05-05: single bundled
fix-up commit on `b4/brisen-lab-v2-bridge-1`.

| # | File | Severity | Change |
|---|------|----------|--------|
| 1 | `bus.py` `/auth/human-confirmation` (lines 671-718) | HIGH | Inverted nonce/sig order: `verify_ed25519_signature` runs FIRST, `consume_nonce` ONLY on verify-success. Pre-fix DoS: forged-sig request burned the legit caller's nonce, locking them out for the remainder of the 60s window |
| 2 | `app.py` `_emit_freeze_broadcast` (lines 179-211) | MEDIUM | Converted to `async def`; DB persist runs via `asyncio.to_thread`. `_freeze_flag_watch_loop` callers now `await` it. Matches the codebase rule documented at lines 233-236 ("blocking psycopg2 pool wrapped via asyncio.to_thread"). Pre-fix would block SSE clients at the worst moment (the freeze flip itself) |
| 3 | `lifecycle.py` `confirm_idle` (lines 279-300) | MEDIUM | `_flows.pop(worker_slug, None)` after `timer_task.cancel()`. Render uptime is weeks → entries previously accumulated per worker per restart event. The `trigger_force_fresh_context` guard at lines 226-232 already None-paths a missing flow, so popping is concurrency-safe |
| 4 | `tier_classification.py` `tier_priority` (lines 170-179) + `bus.py` `_do_decision` | MEDIUM | `_TIER_ORDER.get(tier)` returns Optional[int]; bus call site adds `if required_level is None → {"err": "unknown_tier", "tier": parent_tier}` and outer handler raises structured 500. DB CHECK constraint is primary mitigation; this defends data pre-dating the constraint or written via raw SQL |
| 5 | `tests/test_review_fixes_2026_05_05.py` (NEW) | — | 5 regression guards: invalid_sig+valid_nonce → nonce still valid; valid_sig replayed → 403 nonce_replayed; `_emit_freeze_broadcast` is coroutine; `confirm_idle` pops `_flows`; `tier_priority("invalid") is None` |

Architect LOW nits (forge-agent SPOF on kill path; `/lifecycle/status`
unauth read accepted by design; session_keys soft-restart accumulation)
deferred to follow-up brief — not change-blocking, captured in
`CODE_4_PENDING.md` UPDATE 2026-05-05.

## Test evidence (literal pytest output, not "by inspection")

DSN: `op://Baker API Keys/l52lf6yww3p4zkjbyfjnbax4jq/credential` →
`TEST_DATABASE_URL_BRISEN_LAB`. Sibling DB `brisen_lab_test` on prod
Neon project `summer-sun` (compute `ep-summer-sun-aih7ha4h`). DB-level
isolation; no leak to prod `neondb`.

```
============ 32 passed, 1 skipped, 2 warnings in 206.55s (0:03:26) =============
```

Per-test (33 collected; +5 new in `test_review_fixes_2026_05_05.py`;
A21g still correctly SKIPPED per V0.3.6 amendment):

```
tests/test_a10_a14_lifecycle.py::test_a10_freeze_blocks_post_msg PASSED
tests/test_a10_a14_lifecycle.py::test_a10_freeze_blocks_api_event PASSED
tests/test_a10_a14_lifecycle.py::test_a14_force_fresh_context_emits_lifecycle_restart PASSED
tests/test_a10_a14_lifecycle.py::test_a14g_atomic_h_a4_session_expiry_and_broadcast PASSED
tests/test_a10_a14_lifecycle.py::test_a14_h4_threshold_triggers_hermes PASSED
tests/test_a13_otel.py::test_a13_post_msg_emits_brisen_lab_bus_post_span PASSED
tests/test_a13_otel.py::test_a13_force_fresh_context_emits_lifecycle_span PASSED
tests/test_a1_routes.py::test_a1_routes_registered PASSED
tests/test_a21_h7_auth.py::test_a21a_no_human_token_returns_403 PASSED
tests/test_a21_h7_auth.py::test_a21b_cross_worker_token_rejected PASSED
tests/test_a21_h7_auth.py::test_a21c_replay_rejected PASSED
tests/test_a21_h7_auth.py::test_a21d_expired_token_rejected PASSED
tests/test_a21_h7_auth.py::test_a21e_forged_signature_rejected PASSED
tests/test_a21_h7_auth.py::test_a21f_valid_path_succeeds PASSED
tests/test_a21_h7_auth.py::test_a21g_double_register_rejected SKIPPED
tests/test_a21_h7_auth.py::test_a21h_client_provided_session_id_rejected PASSED
tests/test_a2_schema.py::test_a2_tables_exist PASSED
tests/test_a2_schema.py::test_a2_msg_columns PASSED
tests/test_a2_schema.py::test_a2_msg_indexes PASSED
tests/test_a2_schema.py::test_a2_session_keys_server_issued_uuid PASSED
tests/test_a2_schema.py::test_a2_session_keys_pubkey_check PASSED
tests/test_a2_schema.py::test_a2_kind_enum_no_bare_ratify PASSED
tests/test_a3_a8_a9_bus.py::test_a3_dispatch_kind_sets_wake_attempted_at_on_drain PASSED
tests/test_a3_a8_a9_bus.py::test_a4_exclude_self_filter PASSED
tests/test_a3_a8_a9_bus.py::test_a5_director_only_tier_validates PASSED
tests/test_a3_a8_a9_bus.py::test_a8_soft_delete_sender_within_window PASSED
tests/test_a3_a8_a9_bus.py::test_a8_director_can_delete_anytime PASSED
tests/test_a3_a8_a9_bus.py::test_a9_retention_forever_soft_delete_only PASSED
tests/test_review_fixes_2026_05_05.py::test_fix1_invalid_sig_does_not_burn_nonce PASSED
tests/test_review_fixes_2026_05_05.py::test_fix1_valid_sig_replayed_nonce_still_403 PASSED
tests/test_review_fixes_2026_05_05.py::test_fix2_emit_freeze_broadcast_is_async PASSED
tests/test_review_fixes_2026_05_05.py::test_fix3_confirm_idle_pops_flow PASSED
tests/test_review_fixes_2026_05_05.py::test_fix4_tier_priority_unknown_returns_none PASSED
```

## Push state

- brisen-lab: `13212ff..44b3697` pushed to `b4/brisen-lab-v2-bridge-1`
- baker-master: untouched this round (only the paired MCP-tools side is
  in baker-master; per ratification 2026-05-03 it ships AFTER brisen-lab
  merge)
- PR #1 (https://github.com/vallen300-bit/brisen-lab/pull/1) updated
  in place; new HEAD = `44b3697`

## Re-review chain (per dispatch path forward)

1. AH2 static re-audit on diff `13212ff..44b3697`
2. AH2 `/security-review` on diff (Lesson #52 — Issue 1 is auth-adjacent;
   focused, not full re-audit)
3. Architect spot-check on Issues 1 + 2 (auth ordering + async correctness)
4. Then merge: brisen-lab #1 → baker-master MCP-tools → flip
   `BRISEN_LAB_V2_ENABLED=true`

## Heartbeat

12h cadence continues per binding (2026-05-05 ratified). Next heartbeat
~2026-05-06T01:30Z absent earlier signal.
