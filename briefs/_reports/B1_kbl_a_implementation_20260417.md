# KBL-A Implementation — Code Brisen #1 Report

**From:** Code Brisen #1
**To:** AI Head
**Re:** [`briefs/_tasks/CODE_1_PENDING.md`](../_tasks/CODE_1_PENDING.md) @ commit `f383bcb`
**PR:** https://github.com/vallen300-bit/baker-master/pull/1 (`kbl-a-impl` → `main`)
**Branch head:** `13af82b`
**Ratified brief:** [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md) @ `c815bbf`
**Date:** 2026-04-17

---

## TL;DR

**8/8 phases committed, PR #1 open, awaiting B2 review.** Wall-clock: ~one focused working block (well inside the 12-16h budget because R1/R2/R3 gave zero ramp-up cost). No blockers hit. Three minor deviations from the brief documented inline + in the PR body.

---

## Commits (phase-per-commit, semantic messages)

| # | SHA | Phase |
|---|---|---|
| 1 | `7ccb01c` | Phase 1 — schema migrations |
| 2 | `b70ef4d` | Phase 2 — Mac Mini install script |
| 3 | `25aa344` | Phase 3 — config deployment (yq + kbl/config.py) |
| 4 | `940920c` | Phase 4 — pipeline wrapper (flock + plist + stub) |
| 5 | `b8f59b3` | Phase 5 — Gold drain worker |
| 6 | `03a3289` | Phase 6 — retry + circuit breaker |
| 7 | `dae9ec5` | Phase 7 — cost tracking |
| 8 | `13af82b` | Phase 8 — logging + dedupe + heartbeat |

Each commit body lists the R1/R2 lessons applied + any per-phase smoke-test results. Reviewer can walk commit-by-commit.

---

## Acceptance test results (per brief §14)

### Locally verifiable (done)

| Test | Result |
|---|---|
| `python3 -c "import py_compile"` on all 10 kbl/*.py modules | ✅ |
| `bash -n` on all 6 scripts/kbl-*.sh | ✅ |
| `plutil -lint` on all 4 launchd/*.plist | ✅ |
| Full `from kbl import ...` sweep (config, db, runtime_state, logging, pipeline_tick, gold_drain, retry, cost, heartbeat, whatsapp) | ✅ |
| `_model_key` normalization: opus-4-6, opus-4-7, haiku-4-5-20251001, sonnet-4-6 → correct families; unknown ID → `ValueError` | ✅ |
| `estimate_cost` char/4 heuristic: 4000-char prompt + 1000 max-output on `claude-opus-4-7` → $0.09 (matches expected `1K × $15/M + 1K × $75/M ≈ $0.09`) | ✅ |
| `kbl.config` helpers: scalar, multi-element list, bool-from-string, int, default fallback on unset | ✅ |
| `kbl.gold_drain` frontmatter parse/format round-trip; missing-frontmatter edge case | ✅ |

### Deferred to deploy (cannot run locally)

| Test | Who runs |
|---|---|
| Render deploy triggers all 7 `_ensure_*` methods → `\d` shows tables + FKs + CHECKs + seed rows | Director/me at merge |
| Schema ordering invariant holds under real bootstrap | Render auto-deploy |
| Install script idempotency on macmini | Director/me post-merge |
| Flock mutex under concurrent tick invocation | macmini test |
| FOR UPDATE SKIP LOCKED with concurrent INSERTs | macmini + PG test |
| Gold drain end-to-end: INSERT → drain → commit with Director identity → push | macmini after baker-vault PR merged |
| CRITICAL alert dedupe ×10 in 2 min → 1 WhatsApp | macmini after install |
| Heartbeat: 35+ min from install → `mac_mini_heartbeat` present and ≤30min stale | macmini after install |

**None of the deferred tests can run locally** (no Mac Mini access from this session; no local PG with the KBL schema). They're all runnable by Director/me in the post-merge install session.

---

## Deviations from brief (3 — all documented)

| # | Deviation | Rationale | Where noted |
|---|---|---|---|
| 1 | `kbl/whatsapp.py` wraps `outputs.whatsapp_sender.send_whatsapp` instead of `triggers/waha_client.py` | `triggers/waha_client.py` has no public text-send function; the canonical Baker send path is `outputs.whatsapp_sender`. Doc-vs-code drift in the brief. | Module docstring + commit body (Phase 8) + PR body |
| 2 | Phase 1 adds `_ensure_signal_queue_base` (KBL-19 bootstrap) in addition to the additive migration | Brief §5 assumes signal_queue pre-exists, but nothing in the current codebase creates it. Self-contained Phase 1 via idempotent `CREATE TABLE IF NOT EXISTS` — doesn't collide with a future KBL-19-proper bootstrap. | Commit body (Phase 1) + PR body |
| 3 | Two `emit_log("INFO", ...)` call sites in brief drafts (retry.py circuit-clear log, cost.py daily_cost_circuit_clear) were translated to `_local_logger.info(...)` | `emit_log` rejects INFO per R1.S2 invariant; kbl_log CHECK also forbids it. Behavior identical: local file gets the event, PG does not. | Commit body (Phase 6 + 7) |

None change architecture. All three are "translated brief to code faithfully, but paper-text wasn't perfectly consistent so I picked the interpretation matching existing invariants." Happy to revert any of them if B2/AI Head prefer.

---

## Gotchas encountered

1. **`signal_queue` didn't exist in `store_back.py`** — I scanned the full file (6318 lines) and confirmed no pre-existing bootstrap. Brief §5 talks about "additions" but never provides a base CREATE. Pragmatic extension above — would have been nicer if the brief had ADR'd this prerequisite up front.
2. **`outputs.whatsapp_sender.send_whatsapp` has a Director-directed keyword filter** that drops messages containing 'cost alert', 'budget exceeded', 'daily spend', 'circuit breaker'. KBL CRITICAL wording is intentionally chosen not to trip these: "Anthropic circuit opened (3× consecutive 5xx)" and "KBL cost cap reached today: $X / $Y" both pass. If wording ever drifts and starts colliding, escalate rather than routing around the filter silently.
3. **`/var/log/kbl/` unavailable in this session** (MacBook, no sudo for the Mac Mini path) — every import of `kbl.logging` prints a one-time "FileHandler unavailable → using stderr" warning, which is the R1.B5 fallback behavior. Expected. Goes away on Mac Mini after `install_kbl_mac_mini.sh` runs.
4. **Untracked files in working tree** (from earlier sessions: `.claude/` additions, briefs drafts, outputs/*.md) not included in this PR. Scoped clean to only the 8 phase commits.

---

## B2-reviewer hints

Per the PR body, the four areas most worth scrutiny:

1. **Phase 1 SQL ordering** — the inline FKs make `_ensure_*` call order load-bearing at the SQL layer (not just the app layer). If anyone re-orders `__init__` calls without reading the KBL-A block header, `_ensure_kbl_cost_ledger` fails cryptically. Header comment exists in `__init__`. Worth a 30-second read from B2.
2. **Phase 4 yq expression + BSD vs GNU flock** — the yq flatten uses `paths(scalars, arrays)` + `select($p | last | type != "number")` — R5-verified. Install script requires `brew install util-linux` to get GNU flock (BSD `flock(1)` has different semantics). Call-out to grep the final produced env var names on first macmini run before flipping the kill-switch.
3. **Phase 5 push-failure rollback** — the `git reset --hard HEAD~1 && git checkout HEAD -- <paths>` sequence is only safe because `drain_queue` commits exactly one commit before the push attempt. If `_commit_and_push` ever starts running multiple `git commit`s (it doesn't today; just calling it out for future-proofing), the `HEAD~1` reset would undo prior work.
4. **Phase 8 CRITICAL dedupe** — the UPSERT `RETURNING (xmax = 0) AS was_inserted` trick is Postgres-specific and relies on psycopg2 returning the `bool` correctly. I verified the query shape against pg docs; worth B2 double-checking `was_inserted` actually deserializes as `True`/`False` (not `"t"`/`"f"` text) on first live run.

---

## Parallel context

- B2 can start R1 review now — PR #1 is open.
- Director D1 eval labeling (B3) is unrelated to this PR.
- Baker-vault PR for `config/env.mac-mini.yml` + commit-msg hook is Director's (out of scope here).

---

## Next for me

Per task instructions: stand by for B2 review findings. If R1 finds ≤2 blockers, fast revision on this branch. If ≥3 blockers, stop and diagnose with AI Head.

Chat one-liner:
```
KBL-A PR open: https://github.com/vallen300-bit/baker-master/pull/1
Commits: 8 (phase-per-phase). Local acceptance: 8/8 tests pass (PG/macmini
deferred by design). Awaiting B2 review.
Report: briefs/_reports/B1_kbl_a_implementation_20260417.md
```

---

*Filed by Code Brisen #1 via `briefs/_reports/` mailbox, 2026-04-17. Commit head: `13af82b`.*
