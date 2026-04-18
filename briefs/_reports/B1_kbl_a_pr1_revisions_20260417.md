# KBL-A PR #1 Revisions — Code Brisen #1 Report

**From:** Code Brisen #1
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_1_PENDING.md`](../_tasks/CODE_1_PENDING.md) @ `699c05f`
**PR:** https://github.com/vallen300-bit/baker-master/pull/1 (branch `kbl-a-impl` @ `f34fdef`)
**Revises:** [`briefs/_reports/B2_pr1_review_20260417.md`](B2_pr1_review_20260417.md) @ `f7402c9`
**Date:** 2026-04-17

---

## TL;DR

**10 commits on top of Phase 8 head.** All 10 items in task scope addressed: 1 BLOCKER + 5 SHOULD-FIX + 4 NICE. N5 (brief doc drift) is AI Head's; N6 (venv check) explicitly deferred. No regressions against R1/R2's 25 checkpoints. Full local sweep still green. ~60 min wall clock (inside the 60-90 window). Ready for B2 narrow re-review.

---

## Commits (one per item, semantic messages)

| # | SHA | Item |
|---|---|---|
| 1 | `a1e0792` | `fix(kbl-a): B2.B1 — LaunchAgent env-file plumbing (load ~/.kbl.env)` |
| 2 | `d444d74` | `fix(kbl-a): B2.S1 — gold drain: single tx for lock + commit + push` |
| 3 | `515288e` | `fix(kbl-a): B2.S2 — cost alert dedupe key uses UTC date` |
| 4 | `0547354` | `fix(kbl-a): B2.S3 — gemma retry short-circuit when qwen active + recovery probe` |
| 5 | `80a4217` | `fix(kbl-a): B2.S4 — git subprocess errors caught in gold drain` |
| 6 | `0157a49` | `fix(kbl-a): B2.S5 — circuit health-check model configurable via env` |
| 7 | `efe87a3` | `fix(kbl-a): B2.N1 — anthropic-circuit-open log dedupe` |
| 8 | `037098c` | `fix(kbl-a): B2.N2 — gold drain refuses headerless files` |
| 9 | `1ff2134` | `fix(kbl-a): B2.N3 — vault branch configurable via env` |
| 10 | `f34fdef` | `fix(kbl-a): B2.N4 — was_inserted strict True check` |

Each commit body has a root-cause paragraph + the fix + the verified test. Walk-through-friendly for B2.

---

## Per-item summary

### BLOCKER — B2.B1

`launchd` does NOT source `~/.zshrc`, and the plists only set `PATH`. First Python invocation after `KBL_FLAGS_PIPELINE_ENABLED=true` would `KeyError` on `os.environ["DATABASE_URL"]`.

**Fix (option 1 per B2):** dedicated `~/.kbl.env` (chmod 600). All 4 wrappers source it with `[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"`. Install script creates a template with 5 blank exports (`DATABASE_URL`, `ANTHROPIC_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `VOYAGE_API_KEY`) and prints a prominent "EDIT BEFORE ENABLING PIPELINE" banner. Re-runs re-enforce mode 600 without clobbering a populated file.

**Survivable-before-secrets:** the yml guard + pipeline-flag guard both short-circuit before any Python import touches the env, so an empty `.kbl.env` on day-one install still logs cleanly.

### SHOULD-FIX

- **B2.S1** — `drain_queue` now single-transaction: `FOR UPDATE SKIP LOCKED` holds locks through filesystem + commit + push + UPDATE; one final `conn.commit()` closes the transaction. Push failure rolls back filesystem AND the PG transaction, so rows go back to pending — no drift window possible. Concurrent ad-hoc drainer's SKIP LOCKED sees claimed rows as locked and skips them cleanly.
- **B2.S2** — `kbl/cost.py:_maybe_alert_cost_threshold` dedupe key now uses `datetime.now(timezone.utc).date().isoformat()` (aligned to `NOW()::date` used by `today_spent_usd`). Closes the local-vs-UTC midnight divergence window.
- **B2.S3** — `call_gemma_with_retry` short-circuits attempts 1-3 when `qwen_active=true`. Every Nth signal (configurable `KBL_PIPELINE_QWEN_RECOVERY_PROBE_EVERY`, default 5) probes Gemma attempt 1 to detect natural recovery; success triggers inline recovery (`_inline_gemma_recovery` clears `qwen_active`, `qwen_active_since`, counters). Ladder extracted to a for-loop over 3 `(prompt_fn, temp)` tuples — same semantics, cleaner diff. `_qwen_attempt` extracted as a shared helper.
- **B2.S4** — `_commit_and_push` now wraps `git add`/`git commit` in a try that re-raises `CalledProcessError` as `GitPushFailed`. `drain_queue`'s single `except GitPushFailed:` branch now uniformly handles add/commit/push failures with atomic rollback.
- **B2.S5** — `check_and_clear_anthropic_circuit` reads model via `cfg("circuit_health_model", "claude-haiku-4-5")`. Added to `env.mac-mini.yml.example` under `pipeline:` section. Default is versioned (not bare family alias) per CLAUDE.md's Haiku 4.5 reference.

### NICE-TO-HAVE

- **B2.N1** — Extracted `check_alert_dedupe(component, message, bucket_minutes)` from `emit_critical_alert`'s inline dedupe logic. Returns True iff the alert is fresh within its bucket. `pipeline_tick.py` now routes the `"Anthropic circuit open"` WARN through this helper with a 15-min bucket: always logs locally, only writes to `kbl_log` once per bucket. `emit_critical_alert` refactored to delegate to the same helper — no copy-paste.
- **B2.N2** — `promote_one` checks for `---\n...\n---\n` envelope BEFORE `_parse_frontmatter`. Headerless files return `"error:no_frontmatter"` (mirrors `error:file_not_found` idiom). `_parse_frontmatter` itself unchanged — other callers keep its tolerant-to-missing semantics. 4-case temp-vault smoke test passes.
- **B2.N3** — `_commit_and_push` reads `cfg("gold_promote_vault_branch", "main")`. Added to `env.mac-mini.yml.example` under `gold_promote:` section (clean yq-path mapping).
- **B2.N4** — `was_inserted = cur.fetchone()[0] is True` (identity check, not `bool(...)`) in `check_alert_dedupe`. Defends against the `bool('f') == True` trap if a psycopg2 adapter is ever reconfigured to return strings.

---

## Local sweep (post-revision)

| Check | Result |
|---|---|
| `py_compile` on all 11 `kbl/*.py` | ✅ |
| `bash -n` on all 6 `scripts/kbl-*.sh` + `install_kbl_mac_mini.sh` | ✅ |
| `plutil -lint` on all 4 `launchd/*.plist` | ✅ |
| Full `from kbl import ...` sweep | ✅ |
| `_model_key` normalization (opus-4-7, haiku-4-5-20251001, etc.) | ✅ |
| `check_alert_dedupe` callable + `emit_critical_alert` delegates | ✅ |
| `retry._qwen_attempt` + `_inline_gemma_recovery` callable | ✅ |
| `promote_one` headerless → `error:no_frontmatter` (live temp-vault) | ✅ |
| `promote_one` missing → `error:file_not_found` | ✅ |
| `promote_one` valid → `ok`; repeat → `noop` | ✅ |

No deferred-to-deploy tests changed — still covered by Director/me at macmini install.

---

## Deviations from task file (0)

Task scope honored exactly:
- All 10 listed items committed.
- No force push.
- N5 (brief doc drift) untouched — AI Head's pass.
- N6 (venv check) deferred per task instruction.
- No "bonus fixes" added.
- Single commit per item with semantic message matching the task's template (letter-for-letter).

---

## Re-review hints for B2

Particularly worth scrutiny:
1. **B2.S1 transaction scope.** The `try: ... except: conn.rollback(); raise` wraps the entire claim → filesystem → push → update chain. Confirm that's actually what you want — alternative was a narrower try with explicit rollback in the `GitPushFailed` branch only. I chose the broader try because any unexpected exception (network, disk full, Python error in `promote_one`) should also unlock the rows and leave them pending.
2. **B2.S3 probe counter semantics.** `qwen_recovery_probe_counter` is incremented every time `call_gemma_with_retry` is called while `qwen_active=true`, and the probe fires when `counter % probe_every == 0`. So with default 5, probes fire at call #5, #10, #15, etc. during the outage. `maybe_recover_gemma`'s count/hours-trigger recovery ALSO clears the probe counter so state is consistent after either recovery path. Confirm that matches your mental model — alternative was "probe every N-th tick" using a separate ticker in `pipeline_tick`.
3. **B2.N1 local vs PG visibility.** I kept the stdlib-logger WARN on every tick so operators tailing `/var/log/kbl/pipeline.log` still see every circuit-open tick, while PG only gets one row per 15-min bucket. Alternative was "local file also deduped" — I went with louder local so first-response is faster, but can flip if preferred.

---

## Chat one-liner

```
PR #1 revisions shipped. 10 commits on kbl-a-impl @ f34fdef.
Report at briefs/_reports/B1_kbl_a_pr1_revisions_20260417.md.
Awaiting B2 narrow re-review.
```

---

*Filed by Code Brisen #1 via the `briefs/_reports/` mailbox, 2026-04-17. Branch head: `f34fdef`. 10 commits on top of Phase 8. PR #1 auto-updates on push.*
