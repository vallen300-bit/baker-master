---
brief: BRIEF_BRISEN_LAB_V2_BRIDGE_1 (V0.3.6)
builder: b4
phase: AH2 audit fix-up (post `88bf7ad`)
date: 2026-05-05
status: ready_for_security_review
brisen_lab_branch: b4/brisen-lab-v2-bridge-1
brisen_lab_head: 13212ff
brisen_lab_pr: https://github.com/vallen300-bit/brisen-lab/pull/1
baker_master_branch: b4/brisen-lab-v2-bridge-1
baker_master_head: (unchanged this round)
baker_master_pr: (pending — paired MCP-tools side, ships AFTER brisen-lab merge per ratification 2026-05-03)
---

# B4 ship report — BRIEF_BRISEN_LAB_V2_BRIDGE_1 V0.3.6 fix-up

## What changed (from `88bf7ad` to `13212ff`)

Four fixes from AH2 static audit, plus two latent test-scaffolding fixes
uncovered by running pytest live for the first time (DSN landed today —
prior runs were skip-clean).

| # | File | Severity | Change |
|---|------|----------|--------|
| 1 | `tests/test_a3_a8_a9_bus.py:65` | HIGH | A5 topic now `cortex/oskolkov/capital-call/q3` (was `capital-call/oskolkov/q3` — fell to default tier B, never rejected) |
| 2 | `tests/conftest.py:29-39` | MEDIUM | DSN alias: also accept `TEST_DATABASE_URL_BRISEN_LAB` (the 1Password-provisioned key) |
| 3 | `db.py:21-30` | MEDIUM | `_get_pool()` now uses `threading.Lock` + double-checked locking. Two FastAPI threadpool workers could both pass `if _pool is None` and build rival pools, leaking Neon connections |
| 4 | `bus.py` (5 endpoints) | MEDIUM | H2 freeze gate added to: `POST /msg/<id>/ratify_decision` (load-bearing — INSERTs row during freeze), `POST /msg/<id>/ack`, `DELETE /msg/<id>`, `POST /auth/register-session-pubkey`, `POST /auth/human-confirmation`. All return 503 `lab_frozen` consistent with `/msg` + `/api/event` |
| 5 | `tests/conftest.py:_set_required_env` | latent | Switched `os.environ.setdefault(...)` → hard override for FORGE_KEY / BRISEN_LAB_* / DATABASE_URL. Shell-leaked real `.env` (prod FORGE_KEY hash) was beating the test value, causing `/api/event` to 401 |
| 6 | `tests/conftest.py:otel_memory_exporter` | latent | Tracer is now pulled directly off the fixture's local provider via `provider.get_tracer(...)` instead of `trace.get_tracer(...)` (which goes through the global). OTel rejects re-setting the global provider after `init_tracing` already set it at app startup, so the previous fixture path landed spans on the old provider with no exporter |

V0.3.6 brief amendment dropped test (g) NC2 unreachability — per AH2
issue 5 + AH1 amendment 2026-05-05. No B4 action; A21g is correctly
SKIPPED in the run (1 skip below).

## Test evidence (literal pytest output, not "by inspection")

DSN: `op://Baker API Keys/l52lf6yww3p4zkjbyfjnbax4jq/credential` →
`TEST_DATABASE_URL_BRISEN_LAB`. Sibling DB `brisen_lab_test` on prod
Neon project `summer-sun` (compute `ep-summer-sun-aih7ha4h`). DB-level
isolation; no leak to prod `neondb`.

```
============ 27 passed, 1 skipped, 2 warnings in 178.26s (0:02:58) =============
```

Per-test results (28 tests collected; the 2 deprecation warnings are
FastAPI `on_event` and unrelated):

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
```

## Diff stat

```
 bus.py                     | 16 ++++++++++++
 db.py                      | 28 +++++++++++++--------
 tests/conftest.py          | 61 ++++++++++++++++++++++++++++++++--------------
 tests/test_a3_a8_a9_bus.py |  4 +--
 4 files changed, 79 insertions(+), 30 deletions(-)
```

## Coverage gaps (noted by AH2, not change-blocking; follow-up)

- `test_a2_schema.py` does not assert on `idx_msg_thread`,
  `idx_session_keys_worker_active`, or `idx_msg_to_terminals`
  (broad GIN per NM1). Coverage gap, not correctness gap. Tracker:
  add to a follow-up coverage brief if/when the indexes are touched.
- `test_a14g_atomic_h_a4` has `time.sleep(0.5)` — overkill but
  harmless. Replace with `await asyncio.wait_for` if/when the
  scheduling primitive in `lifecycle.py` exposes a hook.

## Open items / what's next

1. **AH1-App or AH2 runs `/security-review`** against the diff (Lesson
   #52 hard gate for Tier-B). All H1–H7 must pass on the same review.
2. **Merge order** (AH1-App): brisen-lab #1 FIRST, then baker-master
   MCP-tools side. Ratified 2026-05-03.
3. **Post-merge smoke**: Render auto-deploy → `/healthz` 200,
   `/lifecycle/status` returns `{v2_enabled: true, h4_watchdog: {…},
   token_pressure: {}}`.
4. **Vault PR for `wiki/research/2026-05-02-multi-agent-war-stories.md`
   §1/§3/§4/§5 corrections** is queued separately (AH1 owns) — do not
   block this PR on it.

## Heartbeat cadence

12h binding (ratified 2026-05-05). Commit-message-only heartbeats fine.
Two consecutive 12h misses → AH1-App auto-surfaces.

— B4
