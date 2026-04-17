# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous report:** [`briefs/_reports/B2_schema_fk_reconciliation_20260417.md`](../_reports/B2_schema_fk_reconciliation_20260417.md)
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: PR Review — KBL-A Implementation (PR #1)

### Authority

**PR:** https://github.com/vallen300-bit/baker-master/pull/1 (`kbl-a-impl` → `main`)
**Branch head:** `13af82b` (Phase 8) + `bbefea8` (report)
**B1 implementation report:** [`briefs/_reports/B1_kbl_a_implementation_20260417.md`](../_reports/B1_kbl_a_implementation_20260417.md)
**Ratified brief (source of truth):** [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md) @ `c815bbf`

B1 implemented KBL-A after doing R1/R2/R3 as reviewer. Your role: **independent verification at the PR layer** — you DID NOT review the brief, so you bring fresh eyes to the implementation.

### Scope

8 phase commits + 1 report commit. 2083 lines added across 25 files. ~90% new files (kbl/*, scripts/kbl-*, launchd/com.brisen.kbl.*, config/). Modifies `memory/store_back.py` for `_ensure_*` additions.

### Review Priorities (read in this order)

#### 1. B1's deviations (~10 min)

Read B1's report §"Deviations from brief (3 — all documented)". Three translation choices:

- **[DEV-1]** `kbl/whatsapp.py` wraps `outputs.whatsapp_sender.send_whatsapp` instead of brief-spec'd `triggers/waha_client.py`. Verify the wrapped function actually exists and works. Grep for `send_whatsapp` in `outputs/whatsapp_sender.py`.
- **[DEV-2]** Phase 1 adds `_ensure_signal_queue_base` that creates `signal_queue` if missing. Brief assumed it pre-existed. Verify this doesn't collide with any existing bootstrap path in `memory/store_back.py`. Verify the CREATE TABLE shape matches KBL-19 expectations per `briefs/ARCHITECTURE_CORTEX_3T_KBL_UNIFIED.md` (if readable).
- **[DEV-3]** Two `emit_log("INFO", ...)` call sites translated to `_local_logger.info(...)`. Verify consistency across ALL call sites — any `emit_log("INFO", ...)` surviving in the code would crash on the `level` CHECK constraint.

For each: ACCEPT or FLAG. If you flag, propose the right fix.

#### 2. R1/R2 lesson regressions (~15 min)

B1 claims all R1/R2 findings are applied. Verify the critical ones didn't regress:

| # | Check | Location |
|---|---|---|
| R1.B1 | `signal_queue.started_at` column exists in Phase 1 migration | `memory/store_back.py::_ensure_signal_queue_additions` |
| R1.B2 | `mac_mini_heartbeat` + `qwen_active_since` use ISO-8601, NOT literal "NOW()" | grep for `"NOW()"` in kbl/*.py — should find ZERO hits |
| R1.B3 | `__main__` dispatchers exist — no duplicates (R2.NEW-S1) | grep `if __name__` in kbl/gold_drain.py + kbl/logging.py — exactly one each; kbl/pipeline_tick.py — exactly one |
| R1.B4 | Gold drain transaction order: commit+push BEFORE marking PG done | `kbl/gold_drain.py::drain_queue` — trace the order |
| R1.B5 | `FileHandler` wrapped in try/except at import | `kbl/logging.py` module top |
| R1.B6 | `_model_key()` normalizer called at both `estimate_cost` + `log_cost_actual` | `kbl/cost.py` |
| R1.S3 | `git add <specific paths>`, NOT `-A` | `kbl/gold_drain.py::_commit_and_push` |
| R1.S4 | Commit message includes path + queue_id + wa_msg_id | `kbl/gold_drain.py::_commit_and_push` |
| R1.S6 | `git pull --rebase -X ours` (NOT `-X theirs`) | `scripts/kbl-pipeline-tick.sh` |
| R1.S7 | Heartbeat single owner — `kbl/pipeline_tick.py::main()` does NOT write `mac_mini_heartbeat` | `kbl/pipeline_tick.py` |
| R1.S8 | Qwen recovery trigger includes hours-elapsed branch | `kbl/retry.py::maybe_recover_gemma` or inline |
| R1.S9 | `_call_ollama` timeout=180s (NOT 60s) | `kbl/retry.py` |
| R1.S10 | `purge.log` entry in `config/newsyslog-kbl.conf` | `config/newsyslog-kbl.conf` |
| R1.S11 | yq expression with numeric-index filter + array-to-CSV | `scripts/kbl-pipeline-tick.sh` — search for `select($p | last | type != "number")` |
| R2.NEW-B1 | `kbl/db.py` uses direct `psycopg2.connect(DATABASE_URL)` contextmanager, NOT `SentinelStoreBack().conn` | `kbl/db.py` |
| R2.NEW-S3 | Gold drain success path uses local logger (not emit_log); error path uses emit_log("ERROR", ...) | `kbl/gold_drain.py::drain_queue` post-push block |

For each: PASS or FAIL. Every FAIL = blocker.

#### 3. Line-level review of critical modules (~30 min)

Focus on the 4 most risk-prone files:

- **`kbl/gold_drain.py` (234 lines)** — transaction semantics, rollback path, push-retry loop. One bug here corrupts vault state.
- **`kbl/retry.py` (226 lines)** — retry ladders, circuit breaker state machine, health check recursion guard
- **`kbl/cost.py` (254 lines)** — pre-call estimate, post-call actual, cap enforcement, alert dedupe
- **`memory/store_back.py` diff (329 lines added)** — 7 `_ensure_*` methods. Check SQL syntax, constraint names, index names for collisions with existing code.

Skim the rest (`kbl/logging.py`, `kbl/pipeline_tick.py`, `kbl/config.py`, `kbl/runtime_state.py`, `kbl/heartbeat.py`, `kbl/whatsapp.py`, `kbl/db.py`, all shell scripts, all plists). If something smells off, flag.

#### 4. Acceptance test logic (~10 min)

B1 ran 8 local tests ("Locally verifiable" in report) + deferred 8 to deploy ("Deferred to deploy"). Verify:

- Local tests match what's in brief §14 Acceptance Criteria
- Deferred tests are genuinely deploy-dependent (not "skipped because hard")
- No acceptance criterion from the brief is missing without explanation

### What to flag as BLOCKER vs SHOULD-FIX vs NICE

**BLOCKER:** anything that breaks invariants (data corruption, silent failures, connection pool leaks, CHECK constraint violations), OR directly contradicts a ratified decision.

**SHOULD-FIX:** anything that works but drifts from brief spec, OR subtle bugs that won't trigger in Phase 1 but will bite in Phase 2.

**NICE:** polish, comments, minor naming, imports that could be cleaner.

### Output

File report at `briefs/_reports/B2_kbl_a_pr_review_20260417.md` per mailbox pattern.

Header:
```
Re: briefs/_tasks/CODE_2_PENDING.md commit <SHA when you read this>
PR: https://github.com/vallen300-bit/baker-master/pull/1
```

Structure same as R1/R2:
```
## BLOCKERS
## SHOULD FIX
## NICE TO HAVE
## MISSING
```

Plus a summary:
- B1 deviations: accept/flag count
- R1/R2 regressions: N/M pass
- Files reviewed line-by-line
- Overall verdict: APPROVE / REQUEST CHANGES / BLOCK

Chat one-liner:
```
PR #1 review complete. Report at briefs/_reports/B2_kbl_a_pr_review_20260417.md, commit <SHA>.
TL;DR: <N>B/<M>S/<K>N/<L>M, verdict <approve|request-changes|block>.
```

### Time budget

**60-90 minutes** (full PR review — this is a 2083-line implementation across 25 files; invest appropriately).

If you finish in <30 min, you probably skimmed. If >2h, flag — scope may be creeping.

### Pass criteria

| Result | Next step |
|---|---|
| APPROVE (0 blockers) | Director merges PR → Render auto-deploys → install_kbl_mac_mini.sh on macmini |
| REQUEST CHANGES (1-3 blockers) | B1 fixes → force-push branch → you re-review narrow |
| BLOCK (≥4 blockers) | Stop, escalate — implementation may need restructure |

### Parallel context

- **B3:** running Director's D1 eval labeling session. Not your scope.
- **B1:** standing by, waiting on your verdict to either celebrate or fix.
- **Director:** labeling with B3 in parallel. May check in with you periodically.

### DO NOT

- Re-open ratified decisions (15 decisions in `DECISIONS_PRE_KBL_A_V2.md`)
- Suggest architectural changes that weren't in brief
- Request features beyond brief scope
- Block on style preferences

### DO

- Verify correctness of implementation against brief
- Catch bugs B1 missed (self-review blind spots exist — that's why you're here)
- Flag any deviation from brief not documented in B1's report

---

*Task posted by AI Head 2026-04-17. PR #1 is the deliverable; brief is the specification; your eyes are the independent check before merge.*
