# KBL-A PR #1 Revisions — Narrow Re-Verify

**From:** Code Brisen #2
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_2_PENDING.md`](../_tasks/CODE_2_PENDING.md) (file still stale — executed from chat instructions)
**PR:** https://github.com/vallen300-bit/baker-master/pull/1 (`kbl-a-impl` @ `f34fdef`)
**B1 revisions report:** [`briefs/_reports/B1_kbl_a_pr1_revisions_20260417.md`](B1_kbl_a_pr1_revisions_20260417.md) @ `3fa0a94`
**My prior review:** [`briefs/_reports/B2_pr1_review_20260417.md`](B2_pr1_review_20260417.md) @ `f7402c9`
**Date:** 2026-04-17

---

## TL;DR

**APPROVE.** All 10 items addressed correctly via 10 focused commits. Syntax sweep green (11 py, 6 sh, 4 plist). No regressions on the 25 R1/R2 checkpoints. Two minor observations in the appendix (neither blocks merge). Ship it.

---

## Per-item verdict

| # | Item | Verdict | One-line check |
|---|---|---|---|
| 1 | B2.B1 env-file plumbing | ✓ APPROVE | All 4 wrappers load `~/.kbl.env` conditionally; install creates chmod-600 template + banner |
| 2 | B2.S1 single-tx gold drain | ✓ APPROVE | Locks held through critical section; push-fail rolls back both fs + PG |
| 3 | B2.S2 UTC date dedupe key | ✓ APPROVE | `datetime.now(timezone.utc).date().isoformat()` aligned to `NOW()::date` |
| 4 | B2.S3 Qwen-active short-circuit + probe | ✓ APPROVE | Short-circuits attempts 1-3; probe every Nth via `qwen_recovery_probe_counter`; inline recovery clears state |
| 5 | B2.S4 git subprocess errors | ✓ APPROVE | `CalledProcessError` from add/commit wrapped as `GitPushFailed` |
| 6 | B2.S5 health-check model env | ✓ APPROVE | `cfg("circuit_health_model", "claude-haiku-4-5")` + yml example row |
| 7 | B2.N1 circuit-open log dedupe | ✓ APPROVE | `check_alert_dedupe` helper extracted; 15-min bucket on pipeline-tick WARN |
| 8 | B2.N2 headerless files rejected | ✓ APPROVE | Pre-parse envelope check; `_parse_frontmatter` untouched for other callers |
| 9 | B2.N3 vault branch configurable | ✓ APPROVE | `cfg("gold_promote_vault_branch", "main")` + yml example row |
| 10 | B2.N4 strict `was_inserted` | ✓ APPROVE | `is True` identity check, not `bool(...)` |

---

## Code-level verification (spot-checks)

### B2.B1 — env file plumbing

Verified each of the 4 wrappers now contains `[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"` near the top (grep confirmed). `install_kbl_mac_mini.sh` adds a 30-line block that:
- Creates `~/.kbl.env` with 5 blank exports (DATABASE_URL, ANTHROPIC_API_KEY, QDRANT_URL, QDRANT_API_KEY, VOYAGE_API_KEY)
- `chmod 600` on the file
- Prints a prominent "EDIT BEFORE ENABLING PIPELINE" banner
- Skips clobber on re-run

Choice of the 5 vars is correct — the first two are used directly by `kbl.db` + `kbl.retry`/`kbl.cost`; the last three are required because the `outputs.whatsapp_sender` import chain touches `config.settings` which validates QDRANT/VOYAGE at module load (I checked this by tracing the import chain earlier). Survivable-without-secrets: yml guard + flag guard both short-circuit before any Python import, so first-install with empty env still logs cleanly.

### B2.S1 — single transaction

The critical structural check: `conn.commit()` is now called ONCE at the end (line 136), not twice. The early commit after SELECT is gone. `except Exception: conn.rollback(); raise` at the bottom (lines 137-139) is broader than strictly needed, but correct — any unexpected failure (disk full, promote_one parse error, network) unwinds everything. B1's re-review hint #1 asked about this explicitly — I agree with their choice: **broad rollback is correct** because we want rows back to `processed_at IS NULL` on any unhandled failure, not just push failure.

Small forward-looking nit (NOT blocking): the PG transaction now stays open for the full `_commit_and_push` duration (up to `0+2+10+30 = 42s` of push retries). Neon's `idle_in_transaction_session_timeout` is the risk; if Neon ever sets it tighter than 60s, the whole drain fails on a slow push. Currently Neon's default is off. Noting for future awareness, not a fix to apply today.

### B2.S2 — UTC date alignment

Single-line diff (`date.today()` → `datetime.now(timezone.utc).date()`). Comment explains the prior local-vs-UTC divergence. Fix is correct — both sides of the dedupe now use UTC.

### B2.S3 — Qwen retry state machine

Non-trivial refactor; read the full diff carefully.

New structure:
1. `qwen_already_active` check at top → Qwen-active branch.
2. Qwen-active branch: increments `qwen_recovery_probe_counter` every call; probe fires on `counter % probe_every == 0` (default 5 → probes at calls #5, #10, #15…). Probe success triggers `_inline_gemma_recovery`.
3. Gemma-active branch: for-loop over 3 `(prompt_fn, temp)` tuples — cleaner than 3 copy-pasted try/excepts.
4. `_qwen_attempt` extracted; used by both the Qwen-active fast path and the ladder-exhausted fallback.
5. `_inline_gemma_recovery` clears `qwen_active`, `qwen_active_since`, `qwen_swap_count_today`, AND `qwen_recovery_probe_counter` — consistent with the count/hours recovery in `maybe_recover_gemma` (which B1 also updated to clear the probe counter, line 241).

One subtle check I wanted to do: `qwen_recovery_probe_counter` is NOT seeded in `_ensure_kbl_runtime_state`. `get_state("qwen_recovery_probe_counter")` returns empty string on first read, but the code uses `increment_state()` directly which has an INSERT-ON-CONFLICT path that creates the row with value `'1'` first time. So: call #1 creates row (value='1', `1 % 5 != 0`, no probe). Call #2 → '2'. Call #5 → '5', `5 % 5 == 0`, probe fires. ✓ Correct.

Cosmetic note: `qwen_recovery_probe_counter` could be added to `_ensure_kbl_runtime_state`'s seed list for discoverability (7 seed keys instead of 6). Not worth another commit today.

### B2.S4 — git subprocess catch

Clean. `add`/`commit` are now inside a `try` block; `CalledProcessError` converted to `GitPushFailed` with the original error chained via `from e`. `drain_queue`'s single `except GitPushFailed:` now handles all three failure modes (add, commit, push) uniformly with atomic rollback.

### B2.S5 — health-check model

One-line `model=health_model` substitution, + `health_model = cfg("circuit_health_model", "claude-haiku-4-5")` two lines up. Default is versioned (not a bare family alias) per CLAUDE.md's current Haiku 4.5 reference. yml example has the row.

### B2.N1 — dedupe helper extraction

`check_alert_dedupe(component, message, bucket_minutes) -> bool` now lives separately. `emit_critical_alert` delegates to it. `pipeline_tick` uses it with a 15-min bucket for the circuit-open WARN.

Important behavioral preservation: `check_alert_dedupe` returns `False` on DB failure (safer to suppress than spam). `emit_critical_alert`'s previous "don't send WhatsApp on dedupe failure" semantic is preserved. ✓

Alert-key namespace: pipeline_tick's component is `"pipeline_tick"`, emit_critical uses `component` from caller. No collision possible — different component prefixes + different message hashes.

### B2.N2 — headerless guard

Cheap pre-parse check (`content.startswith("---\n") and content.find("\n---\n", 4) != -1`). Returns `"error:no_frontmatter"` on fail. `_parse_frontmatter` itself is NOT modified, so any future callers keep its tolerant-to-missing semantics.

Edge case verified in B1's commit-body test list: `---\n<no closing>` → `error:no_frontmatter`. That's handled because `content.find("\n---\n", 4) == -1` returns `True` for a never-closed header.

### B2.N3 — vault branch

Single-line substitution in the push command. `cfg("gold_promote_vault_branch", "main")`. yml example has the row.

### B2.N4 — strict `is True`

One-line: `was_inserted = cur.fetchone()[0] is True`. Comment explains the `bool('f')` trap defensively.

---

## R1/R2 checkpoint regression sweep

Spot-checked the touched files (`kbl/gold_drain.py`, `kbl/retry.py`, `kbl/cost.py`, `kbl/logging.py`, `kbl/pipeline_tick.py`, `scripts/*.sh`) against the R1/R2 refs I enumerated in the prior review.

**All 25 checkpoints still present:**
- R1.B1–B6, R1.M1–M3, R1.N3–N4, R1.S1–S5, S7–S10, S12 → all references intact (no deletions)
- R2.NEW-B1, R2.NEW-S1, R2.NEW-S2, R2.NEW-S3 → all intact

The refactors preserved every invariant:
- R1.S2/S12 (INFO never to PG) — preserved; new `_local.warning` in pipeline_tick + `_inline_gemma_recovery`'s WARN emit are correct levels.
- R1.B4 (gold drain transaction invariant) — actually STRENGTHENED by S1 (now single-tx not two).
- R1.S3/S4 (specific-path add, detailed commit message) — unchanged.
- R1.S7 (heartbeat single-owner) — unchanged; no new writers to `mac_mini_heartbeat`.
- R1.B2 (ISO-8601 timestamps, never literal "NOW()") — preserved in `_qwen_attempt` extraction.
- R2.NEW-S3 (gold drain success/error log split) — preserved; error path still goes `emit_log("ERROR"...)`, success path still `_local_logger.info`.

No backsliding detected.

---

## Syntax sweep (post-revision)

| Check | Result |
|---|---|
| `ast.parse` on all 11 `kbl/*.py` | ✅ |
| `bash -n` on all 6 `scripts/kbl-*.sh` + `install_kbl_mac_mini.sh` | ✅ |
| `plutil -lint` on all 4 `launchd/*.plist` | ✅ |

---

## Observations (not blocking)

### O1 — Idle-in-transaction risk in gold drain (post-S1)

The post-S1 `drain_queue` holds an open PG transaction + row locks for the full duration of `_commit_and_push` (up to 42s of push retries). Currently fine on Neon (default `idle_in_transaction_session_timeout` is disabled), but worth knowing if Neon's defaults ever tighten. Mitigation would be a "pre-lock → filesystem → commit+push → re-lock via advisory → UPDATE" restructure, which is heavier than the benefit justifies today. Flagging for awareness, not for a fix.

### O2 — `qwen_recovery_probe_counter` not pre-seeded

`_ensure_kbl_runtime_state` seeds 6 keys; the new counter isn't one of them. Code works correctly (created lazily by first `increment_state`), but discoverability is slightly worse than the others. One-line add to the seed INSERT whenever the next schema touch happens.

### O3 — Meta: task file mailbox still stale

`briefs/_tasks/CODE_2_PENDING.md` remains the schema-FK task from earlier today. Third consecutive task from AI Head executed via chat without a corresponding mailbox file update. Mentioning so the pattern doesn't quietly drift.

---

## Verdict

**APPROVE — ready for Director ratification + merge.**

B1 landed all 10 items cleanly, used the commit-per-item cadence for surgical review, handled the subtle bits (transaction scoping, probe-counter consistency, dedupe-failure-suppression preservation) without regressions. Re-review hints 1-3 in B1's report were all answered correctly in the code.

Remaining known items from my original review: N5 (brief §14 "3 columns" vs §5 "4 columns" doc drift — AI Head's pass), N6 (venv/pip sanity check in installer — explicitly deferred). Neither blocks merge.

---

## Standing by

Per task scope: narrow verify done. Next likely paths:
- Director ratifies → merge `kbl-a-impl` → `main` → Render deploys → Director + Code SSH to macmini for install → first live tick.
- AI Head revises brief's N5 drift if desired.
- Director starts D1 eval labeling loop (independent from this merge).
