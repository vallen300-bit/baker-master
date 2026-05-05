---
status: CLAIMED
brief: briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md
trigger_class: TIER_B
dispatched_at: 2026-05-03T20:00:00Z
dispatched_by: ai-head-a
claimed_at: 2026-05-03T20:30:00Z
claimed_by: b4
last_heartbeat: 2026-05-05T19:00:00Z — code-reviewer 4 fixes folded (brisen-lab 13212ff→44b3697): (1) HIGH bus.py verify-then-burn (consume_nonce now after verify_ed25519_signature); (2) MEDIUM app.py _emit_freeze_broadcast async + asyncio.to_thread; (3) MEDIUM lifecycle.py confirm_idle pops _flows; (4) MEDIUM tier_classification.py tier_priority None-guard + bus.py structured 500 on unknown_tier. 5 new regression tests added (tests/test_review_fixes_2026_05_05.py). Live pytest GREEN: 32 passed / 1 skipped (A21g per V0.3.6) / 0 failed against TEST_DATABASE_URL_BRISEN_LAB. brisen-lab PR #1 updated in place; awaiting AH2 static re-audit + AH2 /security-review + architect spot-check on Issues 1+2 per dispatch path forward.
blocker_question: |
  §7 A1-A21 live acceptance pass requires a TEST_DATABASE_URL pointing at
  an isolated Neon branch. Local 1Password has the prod DATABASE_URL
  (Baker API Keys vault) — running tests against it would touch live
  brisen_lab_msg / brisen_lab_session_keys data on the production daemon.
  Need either:
    (a) Director / AH1 provisions a Neon ephemeral branch + drops the
        DSN into 1Password as TEST_DATABASE_URL_BRISEN_LAB, OR
    (b) explicit ratification to run tests against prod Neon with a
        scoped test-only schema (would still need a clean truncate
        between cases — risky on shared infra), OR
    (c) ratification to defer the live A1-A21 pass to /security-review
        gate (which would need to provision its own Neon branch anyway,
        per Lesson #52).
  Recommendation: (a). 1-time vault entry, ~5 min Neon branch provision,
  unblocks both A1-A21 and the future /security-review gate. Test
  scaffolding (28 tests, conftest, fixtures) is ready to run end-to-end
  the moment TEST_DATABASE_URL is available.
  Compile-clean + skip-clean today; brisen-lab branch
  b4/brisen-lab-v2-bridge-1 at 88bf7ad ready for review.
# RATIFIED 2026-05-03 by AH1: cross-repo split confirmed (brisen-lab daemon ↔
# baker-master MCP tools); 2 paired PRs; /security-review MANDATORY against
# brisen-lab PR (Lesson #52); merge order brisen-lab FIRST then baker-master;
# branch b4/brisen-lab-v2-bridge-1 in both repos; mailbox single-source-of-truth
# stays in baker-master. AH1 will fold repo-split correction into V0.3.6 brief
# amendment (no rework here). Schema commit 8e7c98f confirmed clean.
# UNBLOCKED 2026-05-05 by AH1-Terminal under Director auth 2026-05-05 "pls do":
# TEST_DATABASE_URL_BRISEN_LAB landed in 1Password Baker API Keys vault.
# Reference: op://Baker API Keys/l52lf6yww3p4zkjbyfjnbax4jq/credential
# Path taken: fallback (c) — sibling DB `brisen_lab_test` on prod Neon project
# `summer-sun` (compute ep-summer-sun-aih7ha4h, role neondb_owner has CREATEDB).
# Neon API key not in 1Password + no neonctl auth + 0 logged-in console.neon.tech
# tab in debug Chrome → option (a) ephemeral branch not reachable from Terminal.
# Pooler DSN written; smoke verified: connect OK, public.tables=0 (fresh),
# write+read OK in brisen_lab_test, no leak to prod neondb. DB-level isolation
# (shared compute autoscale). Acceptable for Tier-B per brief authorization.
# Re-engage §7 A1–A21 acceptance pass.
ship_report: briefs/_reports/B4_brisen_lab_v2_bridge_1_codereviewer_fixes_2026-05-05.md
ship_report_prev: briefs/_reports/B4_brisen_lab_v2_bridge_1_ah2_fixes_2026-05-05.md
pr: https://github.com/vallen300-bit/brisen-lab/pull/1
autopoll_eligible: false
---

# DISPATCH: B4 → BRIEF_BRISEN_LAB_V2_BRIDGE_1 (V0.3.5)

**Brief:** `briefs/BRIEF_BRISEN_LAB_V2_BRIDGE_1.md` (V0.3.5, 711 lines)

## Why you (B4)

You shipped `CORTEX_PHASE6_VAULT_RECONCILER_1` 2026-05-01. V2_BRIDGE_1 §4 endpoints + Component 6 (§7 A15–A20) read from `cortex_cycles` + `cortex_phase_outputs` + `cortex-roadmap-current.yml` heavily — your Phase-6 reconciler context maps directly. You also know the vault YAML loading patterns (`BAKER_VAULT_PATH`).

## Provenance

V0.1 → V0.3.5 evolution:
- V0.1 (Cowork) — original 19-decision spec
- V0.2 (Cowork) — scope-shrunk to bus + 6 hardening
- V0.3 (AH1) — Director ratified Q1(c), Q2(b), OTel mandatory, verify-before-dispatch, Component 6 fold, Hermes-pattern Amendment 2
- V0.3.1 (AH1, post-AH2 anchor verify) — H3/H4/H5 anchors corrected (Lakera, AICosts.ai 49-helpers, Anthropic Apr 23 postmortem)
- V0.3.2 → V0.3.5 (AH1, post-architect-reviewer 4 passes) — schema fixes, auth primitives, idle threshold, atomicity

## Pass-history convergence (architect-reviewer code-architecture-reviewer)
- Pass 1: 5 Critical / 6 High / 5 Medium / 3 Low
- Pass 2: 3 Critical / 2 High / 3 Medium (introduced by V0.3.2 patches)
- Pass 3: 0 Critical / 3 High / 3 Medium / 2 Low
- Pass 4: 0 Critical / 1 High / 2 Medium / 1 Low
- All folded as of V0.3.5; architect's last-pass verdict: "ship-ready after [the V0.3.5 fixes]". Director ratified ship 2026-05-03.

## Read order (recommended)

1. **§0 Version log + V0.3.x patch history** — explains WHY each constraint exists; many are responses to specific architect findings.
2. **§3 Schema** — `brisen_lab_msg`, `brisen_lab_worker_authority`, `brisen_lab_session_keys`. Read with the V0.3.x annotations (C1, C3, NM3, M-A2, H-A2 etc.) — they tell you what would-be-bugs each line defends.
3. **§4 Endpoints + §4.1 Topic→tier classification** — auth chain.
4. **§5.1 Hermes-pattern** — pay attention to H-A4 atomicity (V0.3.5) for the lifecycle/restart UPDATE+INSERT transaction.
5. **§6 Production Hardening H1–H7** — H3 wrapper+egress-firewall (C5), H4 watchdog, H5 Lakera anchor, H6 audit emit, H7 ed25519 session-key flow (NC2).
6. **§7 Acceptance criteria A1–A21** — your test plan.
7. **§8 Lane** — sequence; you're step 7 (build).

## Constraints

- **Tier B / mandatory `/security-review`** (Lesson #52). H1–H7 ALL must pass — hard gate, not checkbox.
- **`/write-brief` SOP** ran on the spec (4 architect passes); your job is implementation per spec, not redesign.
- **Migration order (L-A1):** `brisen_lab_msg` → `brisen_lab_worker_authority` → `brisen_lab_session_keys` (FK ordering).
- **No worker direct DB writes (NM3):** all `acknowledged_at` updates go through `POST /msg/<id>/ack` endpoint.
- **No force-push to main (L3):** rebase + standard squash-merge only.
- **Vault PR for `wiki/research/2026-05-02-multi-agent-war-stories.md` §1/§3/§4/§5 corrections** is queued as separate scope (AH1 owns); coordinate before/at merge — don't block on it during build.

## ETA

~2.5–3 weeks total per spec §8 (3–4 days bus + 3–5 days Component 6 + 1–2h Hermes + hardening + /security-review + Component 6 UI). Calibrate on first push if your read of complexity differs.

## Coordination

- Branch: `b4/brisen-lab-v2-bridge-1`
- Heartbeat: update `last_heartbeat` in this mailbox file every ~4h while in-flight
- Blocker: surface to AH1 via `blocker_question` field; do not stall silently
- PR opens against `main`; AH1 + `/security-review` both required reviewers per Lesson #52

## Reference (this clone)

- AI Head autonomy charter: `_ops/processes/ai-head-autonomy-charter.md`
- B-code dispatch coordination: `_ops/processes/b-code-dispatch-coordination.md`
- Lessons (read #44 + #52 minimum): `tasks/lessons.md`

## UPDATE 2026-05-05 — AH2 review verdict + 4 fixes (post `88bf7ad`)

**Status:** REQUEST_CHANGES. Static audit clean on A21/A2/M5/A14/A8 cores. 4 actionable fixes required before live test pass.

**Fixes (file:line + description):**

1. **[HIGH]** `tests/test_a3_a8_a9_bus.py:65` — A5 test topic `capital-call/oskolkov/q3` doesn't match YAML pattern `cortex/*/capital-call/`. Falls to default tier B → no tier-below rejection → test will FAIL live. Fix: change topic to `cortex/oskolkov/capital-call/q3`.

2. **[MEDIUM]** `tests/conftest.py:29,39` — Reads `TEST_DATABASE_URL` only. AH1-Terminal provisioned DSN as `TEST_DATABASE_URL_BRISEN_LAB`. Tests will skip rather than run. Fix: `os.environ.get("TEST_DATABASE_URL") or os.environ.get("TEST_DATABASE_URL_BRISEN_LAB")` at both sites.

3. **[MEDIUM]** `db.py:21-30` — `_get_pool()` not thread-safe. Two FastAPI threadpool workers can both pass `if _pool is None` → orphan pool → connection leak (Neon limit risk per existing comment). Fix: threading.Lock double-checked, OR force pool init in `app.py:_startup()` (bootstrap() at L80 already triggers DB hit — pre-warm there closes the race). Error path on missing DATABASE_URL is correct (L26-28 RuntimeError); no change there.

4. **[MEDIUM]** `bus.py:470,429,386,600,640` — Freeze gate (per brief §5: "every wake-mechanism call site") not enforced on:
   - POST /msg/<id>/ratify_decision **(load-bearing — INSERTs bus row during freeze; minimum required fix)**
   - POST /msg/<id>/ack
   - DELETE /msg/<id>
   - POST /auth/register-session-pubkey
   - POST /auth/human-confirmation
   Fix: add `if not freeze.is_v2_enabled(): raise HTTPException(503, "lab_frozen")` at top of each (or shared dependency).

**Brief V0.3.6 amendment landed same push:** drops test (g) NC2 unreachability (AH2 issue 5). No B4 action required — already correctly skipped.

**Path forward:**
1. Apply fixes 1-4 on b4 branch.
2. Re-run live pytest (DSN is `TEST_DATABASE_URL_BRISEN_LAB` per CODE_4_PENDING.md UNBLOCK above).
3. Ship via PL paste-block per SKILL.md §"PL ship-report contract".
4. AH1-App or AH2 runs `/security-review` against diff (Lesson #52 hard gate).
5. Cross-repo merge order: brisen-lab FIRST, then baker-master MCP-tools side.

**Heartbeat:** continue 12h cadence per binding (2026-05-05 ratified). Two consecutive 12h misses → AH1-App auto-surfaces.

**Coverage gaps noted (not change-blocking, follow-up):**
- A2 schema test missing index assertions for idx_msg_thread / idx_session_keys_worker_active / idx_msg_to_terminals (NM1 broad GIN). Coverage gap, not correctness gap.
- `test_a14g_atomic_h_a4` `time.sleep(0.5)` is overkill but harmless.

## UPDATE 2026-05-05 — code-reviewer REQUEST_CHANGES (post-13212ff)

**Status:** REQUEST_CHANGES. feature-dev:code-reviewer pass on `13212ff` returned 1 HIGH + 3 MEDIUM. **These are findings prior gates (static, security, architect) all missed.** Path A: fold all 4 into one fix-up commit on b4 branch.

### Fix 1 [HIGH] — nonce consumed before signature verified
**File:** `bus.py` (~lines 677-708 at HEAD 13212ff; lines may shift, locate by function — the handler that calls both `consume_nonce()` and `verify_ed25519_signature()`; per code-reviewer this is in the auth chain leading to ratify_decision / human-confirmation flow).

**Bug:** `consume_nonce(nonce)` runs BEFORE `verify_ed25519_signature(...)`. On verify-fail (transient: clock drift at 60s boundary; or attacker replaying with forged sig), nonce is already burned. Legitimate caller locked out for remainder of 60s window; attacker can selectively DoS legit nonces.

**Fix:** invert order — verify signature first, then `consume_nonce` ONLY on verify-success. Single critical section: signature-OK-then-burn, atomic.

**Tests to add:**
- `valid_sig + replayed_nonce → 403 nonce_replayed` (existing or extend)
- `invalid_sig + valid_nonce → 403 sig_invalid AND same nonce STILL VALID on retry within 60s` (new — this is the regression guard)

### Fix 2 [MEDIUM] — event-loop block on freeze flip
**File:** `app.py:179-207` (`_emit_freeze_broadcast`)

**Bug:** sync function calling blocking psycopg2 `_do()` directly from `_freeze_flag_watch_loop` (an `async def` on event loop). Contradicts codebase design (line 233-236 comment: "Handlers that touch the blocking psycopg2 pool are wrapped via asyncio.to_thread"). Will block SSE clients at exact moment freeze fires (worst possible time).

**Fix:** wrap `_do()` in `await asyncio.to_thread(_do)` from inside `_freeze_flag_watch_loop` (cleanest — keeps `_emit_freeze_broadcast` sync). Alternative: convert `_emit_freeze_broadcast` to `async def` and `await` it. `_broadcast()` is queue-based — leave alone.

**Test:** assert `_freeze_flag_watch_loop` doesn't block event loop for >50ms during freeze flip (or unit-level: mock `_do` to assert it's called via `to_thread`).

### Fix 3 [MEDIUM] — _flows registry leak
**File:** `lifecycle.py:91, 279-296` (`confirm_idle`)

**Bug:** `confirm_idle` sets `flow.confirmed = True` and cancels `timer_task` but never removes entry from `_flows` dict. Render service uptime is weeks → entries accumulate per worker per restart event.

**Fix:** add `_flows.pop(worker_slug, None)` after `timer_task.cancel()` in `confirm_idle`. The existing trigger-skip-if-confirmed guard at lines 226-232 already handles concurrent reads (lookup returns None → caller's None-path).

**Test:** unit — call `confirm_idle(slug)` on a registered flow → assert `_flows.get(slug) is None`.

### Fix 4 [MEDIUM] — KeyError on unknown tier
**File:** `tier_classification.py:170-173` (`tier_priority`); call site at `bus.py:558` (`_do_decision`)

**Bug:** `_TIER_ORDER[tier]` raises unhandled KeyError on out-of-enum tier values. DB CHECK constraint is primary mitigation but partial (data pre-dating constraint, or raw-SQL writes). Surfaces as opaque 500.

**Fix:** `_TIER_ORDER.get(tier)` with None-guard. In `_do_decision`, on None return `{"err": "unknown_tier", "tier": tier}` consistent with other error paths.

**Test:** unit — `_do_decision` with parent.tier_required="invalid" → returns err structure, no exception.

### Architect nits (LOW — confirmed by code-reviewer, no fix in this PR)
- forge-agent SPOF on kill path → architectural property, captured in follow-ups
- /lifecycle/status unauth read → accepted by design, captured
- session_keys accumulation across soft restarts → confirmed real, captured for follow-up brief

### Path forward
1. Apply 4 fixes on b4 branch + add new tests
2. Re-run live pytest — GREEN required (literal output, no by-inspection)
3. Ship via PL paste-block per SKILL.md §"PL ship-report contract"
4. **Re-review chain** (focused, not full re-audit):
   - AH2 static re-audit on diff vs 13212ff
   - AH2 /security-review on diff vs 13212ff (Issue 1 is auth-adjacent)
   - Architect spot-check (Issues 1 + 2 — auth ordering + async correctness)
5. Then merge: brisen-lab #1 → baker-master MCP-tools → BRISEN_LAB_V2_ENABLED=true cutover

### Heartbeat
Continue 12h cadence.

## UPDATE 2026-05-05 — §Consumer-side build (post brisen-lab PR #1 merge `e5a6617`)

**Status:** UNBLOCK + extend. Brisen-lab side merged + smoke green; consumer-side (baker-master) is the next critical-path build. Single PR on existing branch `b4/brisen-lab-v2-bridge-1` (baker-master).

### 5 surfaces to ship

| # | Surface | Path | Notes |
|---|---|---|---|
| 1 | `baker_inbox_post` + `baker_inbox_read` MCP tools (A7) | `baker_mcp/baker_mcp_server.py` | Consumes brisen-lab `POST /msg/<terminal>` + `GET /msg/`. Fail-open to AC6 paste-block fallback when V2 endpoints return 503 (flag-off state). |
| 2 | SessionStart hook — ed25519 keygen + `POST /auth/register-session-pubkey` (H7/NC2) | extend `.claude/hooks/session-start-role.sh` OR new sibling Python hook | Fresh keypair per session; private key in process-memory only (NEVER on disk). Re-fire on Hermes-pattern restart per A14 (force_fresh_context broadcast). |
| 3 | UserPromptSubmit hook — sign `{worker_slug, session_id, prompt_hash, ts, nonce}` + exchange for JWT via `POST /auth/human-confirmation` (H7/NC2) | NEW hook: `.claude/hooks/user-prompt-submit-confirm.{sh,py}` | Replay-protection via nonce; worker_slug binding correctness is load-bearing (wrong slug → 403 token_worker_mismatch, loud-and-recoverable). |
| 4 | A14 Hermes-restart re-keygen wiring | same SessionStart extension | Fresh keypair + re-register on every SessionStart fire including force_fresh_context-triggered restart. |
| 5 | Drain wiring | UserPromptSubmit hook (drain side) | Drain inbox each turn boundary; `POST /msg/<id>/ack` per consumed msg. Cowork auto-read: session-init hook calls `baker_inbox_read(since_ts=last_seen)` on first tool-use. |

### Hook impl path — Python recommended, B4 override OK

Hooks need ed25519 crypto (PyNaCl / cryptography). Two paths:

- **(a) Bash + Python shell-out** — extend existing `session-start-role.sh`; shell-out to one-shot Python for keygen + sign. Faster (~2-4h saved) but creates dual-language hook surface.
- **(b) Port hook to Python** — clean single-language hook. AH2 recommendation, AH1-App agrees. B4 final call.

Default: **(b) Python port** unless B4 surfaces a concrete reason to do (a).

### Pre-flag-flip safety (mandatory)

`BRISEN_LAB_V2_ENABLED=false` stays until consumer-side ships + cuts over. While off:
- All V2 endpoints return 503 → MCP tools must **fail open** to AC6 paste-block fallback
- Hooks must `exit 0` on EVERY error path (PR #149 fail-open discipline). **Hook bug = terminal-startup hazard** — non-negotiable.

### Tests

- MCP tool unit tests (mock daemon, no live HTTP)
- Hook unit tests — 4-way matrix per role per PR #149 pattern (lead / deputy / AH1 / AH2 etc.)
- Manual integration smoke once `BRISEN_LAB_V2_ENABLED=true` flips post-merge
- Ship gate: live pytest GREEN — literal output, no by-inspection (Lesson #52)

### Re-review chain (lighter than brisen-lab side, but mandatory)

Per V0.3.6 §0 line 112: "MCP-tool-only — lighter review acceptable." Still required:
1. Live pytest GREEN
2. AH2 `/security-review` — focus on hook fail-open discipline + ed25519 keypair lifetime (process-memory-only) + worker_slug binding + no terminal-key leak in MCP tool error paths
3. Architect spot-check on auth-adjacent surfaces (hooks + MCP tools touching auth = Trigger 1+3 of new §Code-reviewer 2nd-pass Protocol)
4. `feature-dev:code-reviewer` 2nd-pass per new §Code-reviewer 2nd-pass Protocol (auth-touching = mandatory trigger)

### After ship

- AH1-App authorizes Tier-B `BRISEN_LAB_V2_ENABLED=true` env-var flip on brisen-lab daemon (env-flip on Render, no code merge)
- Post-cutover: AC6 paste-block-via-Director fallback retired

### Heartbeat

Continue 12h cadence per binding 2026-05-05.

### Anchor

AH2 scope memo 2026-05-05 (chat) + V0.3.6 §0 lines 107-112 cross-repo split + §4 lines 323-324 auth endpoints + §5 lines 408-410 wake mechanism + §6 lines 540-571 H7 hook primitives + §7 A7+A14.
