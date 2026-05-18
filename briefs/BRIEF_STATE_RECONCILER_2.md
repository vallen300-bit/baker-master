# BRIEF: STATE_RECONCILER_2 — Phase 1 follow-up cleanup

## Context

STATE_RECONCILER_1 shipped 2026-05-18 (baker-vault PR #96 merged `e289ff4` + follow-up PR #97 merged `6ef117e`). 4-gate chain cleared PASS-WITH-NITS across two rounds. Three Gate-3 / re-fire findings were explicitly deferred to STATE_RECONCILER_2 at round-1 dispatch (bus #419) on the grounds that none blocked first-fire and the round-1 fold was already 12-finding-deep. First nightly cron fires 2026-05-19 02:30 UTC; this brief lands those three deferred items as a tight follow-up before drift accumulates.

## Estimated time: ~1 builder-day
## Complexity: Low
## Target: b3 (lane owner — STATE_RECONCILER_1 builder, context warm)
## Target repo: baker-vault
## Matter slug: baker-internal
## Trigger class: LOW (touches shipped reconciler internals; no new external surface, no schema change, no auth/DB; ≤45 LOC delta expected)

## Prerequisites
- STATE_RECONCILER_1 (PR #96 + #97) merged on baker-vault main — confirmed.
- First nightly cron fire is scheduled but NOT yet observed (02:30 UTC tomorrow); land this PR before or shortly after first fire to avoid stacking changes on partial observation.

---

## Items

### F1 — schema_version regex re-application cleanup (gate-3 M2)

**Where:** `_ops/reconciler/state_reconciler.py` `update_frontmatter()` lines ~336-340.

**Symptom:** when `schema_version:` is absent from frontmatter, the insert path re-applies `UPDATED_FIELD_RE.sub(new_updated_line + "\nschema_version: v1", new_fm, count=1)` — a second regex substitution that depends on the first sub having already produced `new_updated_line` literally in `new_fm`. This works but is brittle (couples insert-logic to the prior overwrite-logic) and reads as a confusing pattern in code review.

**Fix:** replace the conditional insert with a direct string operation — locate the `updated:` line in `new_fm` after the first sub, append `\nschema_version: v1` immediately after it. No second regex pass. Behavior must remain byte-identical for both branches (present + absent).

**Tests to add (in `tests/test_state_reconciler.py::TestUpdateFrontmatter`):**
- `test_schema_version_inserted_when_absent_byte_identical_to_old_path` — feed a frontmatter without `schema_version:` to BOTH the prior-shipped and the cleaned implementation; assert output bytes match.
- `test_schema_version_inserted_only_once_on_repeated_runs` — already covered indirectly by idempotency tests; add an explicit assertion on second run.

---

### F2 — STATE_RECONCILER_SKIP bypass audit trail (gate-3 M5)

**Where:** `.githooks/state_reconciler_pre_commit.sh` lines ~22-25 (env-var bypass branch).

**Symptom:** today the bypass emits a `WARN [state-reconciler]: STATE_RECONCILER_SKIP=1 — skipping regeneration.` line to stderr and exits 0. No persistent record of WHO bypassed WHEN, on WHICH commit, against WHICH staged decision-log changes. Bypass is a legitimate emergency mechanism (precedent #3 in `_ops/processes/director-comm-rules.md`) but unaudited it is also a silent drift source — anyone (or any agent) can `STATE_RECONCILER_SKIP=1 git commit` and leave cortex-config snapshots stale without trace.

**Fix:** in the bypass branch, append a structured JSON line to `_ops/agents/_scanner-state/reconciler-bypass-log.jsonl` BEFORE returning 0. Schema:

```json
{"ts": "<ISO-8601 UTC>", "git_user": "<git config user.email>", "branch": "<current HEAD ref>", "staged_decision_logs": ["wiki/matters/<slug>/curated/06_decisions_log.md", ...], "commit_msg_excerpt": "<first 80 chars of $(git log --format=%s -1 HEAD) — N/A on commit-not-yet-created>"}
```

`_ops/agents/_scanner-state/reconciler-bypass-log.jsonl` MUST be added to baker-vault `.gitignore` alongside the existing `reconciler-*.json` entries — same ownership model (cron / hook owns; never committed).

Surfacing: nightly cron reads the bypass-log; if any entries with `ts > last_nightly_fire_ts` exist, emit a bus-post to `lead` with topic `bypass-detected/state-reconciler` summarizing count + git_user + branches. No alert if zero entries since last fire (the common case).

**Tests to add (in a new `tests/test_state_reconciler_bypass.py` — bash-mock + Python integration):**
- `test_bypass_appends_jsonl_entry_with_required_fields` — invoke the hook with `STATE_RECONCILER_SKIP=1` via subprocess in an isolated tmp repo with staged decision-log changes; assert the JSONL line exists with all 5 keys.
- `test_bypass_jsonl_grows_append_only` — invoke twice; assert 2 lines, first preserved byte-for-byte.
- `test_bypass_log_in_gitignore` — `git check-ignore _ops/agents/_scanner-state/reconciler-bypass-log.jsonl` returns 0 (the path IS ignored).
- `test_nightly_cron_bus_posts_on_bypass_since_last_fire` — seed bypass-log with a recent ts; run `nightly_cron.sh` in dry-mode; assert bus_post.sh was invoked with topic `bypass-detected/state-reconciler` (mock bus_post.sh to echo args).

---

### F3 — `reconcile_matter` post-write error path (gate-3 re-fire M)

**Where:** `_ops/reconciler/state_reconciler.py` `reconcile_matter()` lines ~510-515.

**Symptom:** today the function does `_atomic_write(cortex_config, cc_text_new)` (line 510) THEN `_save_state(...)` (511) + `_append_skip_log(...)` (515). Read-side OSError already returns `error_io_read` (M1 gate4, round-1 fold). Write-side coverage is asymmetric: if either `_save_state` or `_append_skip_log` raises OSError AFTER the cortex-config is already written, the function propagates the exception with the visible side-effect already on disk and the state-files inconsistent. Next nightly fire compares inputs_hash against a stale state-file and may re-write needlessly OR (worse) skip-as-noop incorrectly.

**Fix:** wrap lines 511-515 (`_save_state` + `_append_skip_log`) in a single `try/except OSError`. On failure, return:

```python
{"slug": slug, "status": "error_io_postwrite", "error": str(e), "cortex_config_written": True}
```

Symmetric `error_io_read` status name for callers. The `cortex_config_written: True` flag signals to nightly cron + Layer C audit that the visible side-effect landed but state-tracking is corrupt — next-fire re-render is safe (idempotent) and will refresh state-files. Bus-post on this status by `nightly_cron.sh` (extend the existing STATUS-mutating trap arms).

**Tests to add (in `tests/test_state_reconciler.py::TestReconcileMatter`):**
- `test_postwrite_save_state_raises_returns_error_io_postwrite` — monkeypatch `_save_state` to raise `OSError("disk full")`; assert return dict matches the contract above AND cortex-config IS written on disk.
- `test_postwrite_append_skip_raises_returns_error_io_postwrite` — same for `_append_skip_log`.
- `test_next_run_recovers_after_error_io_postwrite` — first run with `_save_state` patched to raise; second run unpatched; assert idempotent settle (cortex-config unchanged, state-file written cleanly).

---

## Acceptance criteria

1. F1 + F2 + F3 implemented per the contracts above.
2. All STATE_RECONCILER_1 tests still pass (45 currently). Net test count after this brief: 45 + ~9 = ~54 minimum.
3. Live dry-run against vault root (`python3 _ops/reconciler/state_reconciler.py --vault-root . --dry-run`) returns 8 matters all `noop_identical`, zero `error_*` (regression check).
4. `STATE_RECONCILER_SKIP=1 git commit ...` smoke on the 9th matter (not in PHASE_1_RATIFIED_MATTERS — any cortex-config not in the 8) writes one JSONL line to the bypass-log + exits 0.
5. `_ops/agents/_scanner-state/reconciler-bypass-log.jsonl` is in `.gitignore` (verified via `git check-ignore`).
6. `_ops/reconciler/README.md` updated: test count bumped to actual final count + one paragraph on the bypass-audit-trail + post-write error path additions.

## Ship gate

- PR opened against baker-vault main from branch `b3/state-reconciler-2`.
- Trigger class LOW → AH2 Gate 1 + Gate 2 (`/security-review`) required; Gate 3 (picker-architect) + Gate 4 (2nd-pass code-reviewer) NOT required (no new external surface, no auth/DB, ≤45 LOC delta, all changes inside already-reviewed reconciler internals).
- Commit identity: Code Brisen #3 <b3@brisengroup.com> (matches STATE_RECONCILER_1 fold commits).
- Same atomicity rules as STATE_RECONCILER_1 — never bypass hooks with `--no-verify`.

## Out of scope (do NOT include in this PR)

- Decision-log heading canonicalization (separate brief; surfaces from Tier-3 parser-skip log once nightly cron has observation data).
- Phase 2 cycle-register reconciler (gated on Phase 1 observation period — 2 weeks per RA-23 spec).
- Layer C audit changes beyond the single bus-post on `bypass-detected` + `error_io_postwrite`.

---

**Anchor:** Director ratification 2026-05-18 chat — "go" on AH1 recommendation to draft STATE_RECONCILER_2 follow-up brief as first task of this session. Items pre-itemized in CODE_3_PENDING.md `deferred_to_state_reconciler_2:` block + bus thread #419 / #420 / #422 / #425.
