---
brief: briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md
amendment: V0.3.7 + Surface 6
trigger_class: TIER_B
worker: b4
branch: b4/brisen-lab-v2-bridge-1
prior_head: 913cfa7
new_head: a6d9995
pr: https://github.com/vallen300-bit/baker-master/pull/157
shipped_at: 2026-05-05
---

# B4 ship report — gate-4 code-reviewer fix-up

## Scope

Folded gate-4 `feature-dev:code-reviewer` findings (1 HIGH + 2 MEDIUM) on baker-master PR #157 (consumer-side hook + MCP tools). Per mailbox `UPDATE 2026-05-05 — gate 4 code-reviewer findings` block in `briefs/_tasks/CODE_4_PENDING.md`.

## Diff (commit a6d9995)

| File | Change |
|---|---|
| `.claude/hooks/user-prompt-submit-confirm.py` | Fix 1 [HIGH] privkey lifetime narrowed: `del privkey` runs immediately after `sign()`, BEFORE `/auth/human-confirmation` POST. Fix 2 [MED] drain preview drops body-fallback chain; emits `(preview unavailable)` placeholder. |
| `baker_mcp/baker_mcp_server.py` | Fix 3 [MED] new `_brisen_lab_extract_error()` helper applied at 3 daemon-body-surfacing sites (POST 4xx, GET 4xx, GET non-JSON 200). Surfaces only daemon `error` field; raw resp.text fallback truncated to 80 chars. |
| `tests/test_brisen_lab_gate4_fixes_2026_05_05.py` | NEW: 5 regression tests — privkey-ordering introspection, drain placeholder + no-body-leak, post 4xx + read 4xx context-leak guards, defensive non-JSON fallback. |

Stat: 3 files, +356 / -14 lines.

## Live pytest GREEN

### brisen-lab paired clone (`/Users/dimitry/bm-b4-brisen-lab`)
Branch `b4/v2-bridge-surface-6-session-keys-cleanup` at `e6fd4c3` (unchanged from prior cycle). Live DSN via 1Password `op://Baker API Keys/l52lf6yww3p4zkjbyfjnbax4jq/credential` → `brisen_lab_test` sibling DB on Neon prod project `summer-sun`.

```
============ 36 passed, 1 skipped, 2 warnings in 238.72s (0:03:58) =============
```

A21g remains the single skipped test per V0.3.6 amendment (NC2 unreachability dropped).

### baker-master (`/Users/dimitry/bm-b4`) — diff-scoped

```
tests/test_brisen_lab_user_prompt_submit_hook.py    31 passed
tests/test_brisen_lab_consumer_mcp.py               32 passed
tests/test_brisen_lab_gate4_fixes_2026_05_05.py      5 passed
tests/test_mcp_baker_extension_1.py                 36 passed
============================== 104 passed in 0.29s ==============================
```

### baker-master broader suite — pre-existing failures only (not regressions)

Full suite: 1676 passed, 31 failed, 30 errors. All failures verified pre-existing on HEAD `913cfa7` WITHOUT this diff (stash + re-test):

| Cluster | Files affected | Cause |
|---|---|---|
| ClickUp mock comparison | `test_clickup_client.py` (5) | MagicMock vs int `>=` — venv setup decay |
| Cortex SSE asyncio | `test_cortex_run_stream.py` (4) | `pytest.mark.asyncio` not registered (warning lists) |
| Scan auth 401 | `test_scan_endpoint.py` (3) | Auth fixture issue |
| Step 6 dispatch | `test_step6_cortex_dispatch.py` (8) | PosixPath/int + MagicMock |
| Vault tools | `test_mcp_vault_tools.py` (30 errors) | TypeErrors — likely missing fixture |

None touch `.claude/hooks/`, `baker_mcp/`, or any brisen-lab consumer surface. Pre-existing infrastructure decay; out of scope for this brief.

## Re-fired gate chain — diff-scoped

### feature-dev:code-reviewer 2nd-pass — APPROVE
Confirms all 3 original findings substantively closed. NIT only: defensive double-`try/except` around `del privkey` is redundant on happy path (does no harm). 5 new tests are load-bearing. Two follow-up notes (non-blocking):
1. Three `resp.text[:300]` sites in `baker_search` / `baker_ingest_signal` / `baker_health_check` (lines 1014, 1076, 1104) carry the same class of context-leakage risk on the **Baker** daemon side (different daemon, out of brief scope) — recommend follow-up brief.
2. Test for GET-200-with-non-JSON path not directly exercised; structurally covered by helper applied at site.

### code-architecture-reviewer spot-check (auth-adjacent) — APPROVE
- **Privkey lifetime:** "mostly symbolic, partially meaningful, fully defensible" — buys honesty alignment between brief §6 wording and code; defends against future code that widens the window. Should NOT be framed as a forward-secrecy upgrade. Existing comment language correct — keep it.
- **Auth-chain ordering:** sign → del privkey → POST `/auth/human-confirmation` composes cleanly with daemon's verify-then-burn nonce protocol. No regression vector.
- **Helper placement:** procedural module-level form is the right call alongside the existing `_brisen_lab_*` cluster. Premature to extract `BrisenLabClient` class.
- **Test design:** introspection for Fix 1 is correct — runtime tracking would lock to PyO3 implementation. One hardening idea: scan-for-no-stray-references between sign and post (not blocking).

### Pending — out of B4 scope, surface to AH1
- AH2 static re-audit on diff vs `913cfa7..a6d9995`
- AH2 `/security-review` on diff (Lesson #52 — auth-adjacent)

## Cross-repo merge order (post-AH2 clear)

Per V0.3.7 amendment: brisen-lab #2 FIRST → baker-master #157 → file Surface 6a partial unique index follow-up → `BRISEN_LAB_V2_ENABLED=true` Tier-B cutover.

## Anchors

- Mailbox UPDATE 2026-05-05 commit `913cfa7`
- Gate-4 code-reviewer agent `a07ab8c0a75168417` 2026-05-05 (original findings)
- 2nd-pass code-reviewer agent `a2d6792f542e15f64` 2026-05-05 (verdict APPROVE)
- Architect spot-check agent `a2c53219c29322a22` 2026-05-05 (verdict APPROVE)
- Brief V0.3.7 unchanged
- 1Password DSN `op://Baker API Keys/l52lf6yww3p4zkjbyfjnbax4jq/credential` (TEST_DATABASE_URL_BRISEN_LAB)

## Heartbeat

12h cadence per binding 2026-05-05 ratified. Mailbox `last_heartbeat` field to be updated to `2026-05-05T22:35:00Z` when AH1-App acks this report.
