# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — PR #16 review (FINAL pipeline PR)

---

## Completed since last dispatch

- Task N — PR #15 STEP6-FINALIZE-IMPL (APPROVE @ `89b435b`) ✓ **MERGED `4cb47e1a`**

---

## Task O (NOW): Review PR #16 — STEP7-COMMIT-IMPL — THE LAST PIPELINE PR

**PR:** https://github.com/vallen300-bit/baker-master/pull/16
**Branch:** `step7-commit-impl`
**Head:** `79ad641`
**Tests:** 38/38 in scope (26 step7 + 12 pipeline_tick), 366 KBL subset, zero regressions
**Spec:** KBL-B brief §4.8 (commit step) + §4.9 (TOAST cleanup) + dispatch brief @ `4eef691`

### Scope — surfaces to audit

1. **`kbl/steps/step7_commit.py`** — commit + push + TOAST cleanup
2. **`kbl/exceptions.py`** — `CommitError` + `VaultLockTimeoutError` (net-additive)
3. **`kbl/_flock.py`** (or inline) — POSIX fcntl helper with 60s deadline
4. **`kbl/pipeline_tick.py`** — `_process_signal` extended to terminal state `completed`
5. **`tests/test_step7_commit.py`** — 26 new tests
6. **`tests/test_pipeline_tick.py`** — 12 extended tests including full 7-step happy path

### Specific scrutiny

#### Vault write path (Inv 9 operationalized)

1. **Positive Inv 9 test** — writes land ONLY under `{BAKER_VAULT_PATH}/wiki/`. Never outside. B1 reports: "positive test pins writes under {vault}/wiki/ only." Re-verify via the test's assertion shape.
2. **Inv 4 FS-level guard** — if `target_vault_path` exists and current file has `author: director` frontmatter, Step 7 MUST NOT overwrite. Verify: raises `CommitError` → state `commit_failed` → operator investigates. **Critical gold-protection check.**
3. **Atomic write pattern** — `tempfile.NamedTemporaryFile(dir=vault_dir) + os.replace`. Verify tempfile is in same filesystem as destination (os.replace is only atomic intra-filesystem).
4. **Unwind on failure** — `git checkout HEAD -- . && git clean -fd` on partial-write failure. Verify this is INSIDE the flock window (otherwise concurrent tick sees inconsistent state).

#### Cross-link idempotency

5. **Idempotent stub replacement** — if `_links.md` has an existing stub with same `<!-- stub:signal_id={id} -->` marker, REPLACE that line in-place. Not append. Verify regex + test.
6. **Sort order** — stubs sorted by `created` DESC (newest at top). Verify.
7. **`kbl_cross_link_queue.realized_at`** — set to `NOW()` on successful commit of those specific stubs. Only the stubs for THIS signal_id. Verify.

#### Flock + concurrency

8. **60s deadline** — `VaultLockTimeoutError` raised on timeout. Verify test uses simulated concurrent hold (not a real sleep — would slow CI).
9. **Release on exception** — flock context manager releases even if exception raised inside. Verify via `pytest.raises` nested with file lock re-acquirable after.
10. **Lock path** — `{BAKER_VAULT_PATH}/.lock` (env override `BAKER_VAULT_LOCK_PATH`). Verify lock file is NOT under `wiki/` (would confuse git).

#### Git operations

11. **Identity config** — pipeline identity `Baker Pipeline <pipeline@brisengroup.com>` set locally in vault clone (not globally). Env overridable. Verify test sets identity via git config calls, not global.
12. **Rebase retry logic** — one retry on non-fast-forward. Exhausted → `git reset --hard ORIG_HEAD` + state `commit_failed`. Verify:
    - Test: first push fails with rebase-able conflict → rebase + retry → succeeds.
    - Test: first push fails + rebase push also fails → reset + `commit_failed`.
13. **Commit message** — `Silver: {primary_matter} — {title} (sig:{short_id})`. Verify format.
14. **`commit_sha` capture** — `git rev-parse HEAD` after commit, stored in `signal_queue.commit_sha`. Verify.

#### TOAST cleanup (§4.9)

15. **Post-commit NULL-out** — `UPDATE signal_queue SET opus_draft_markdown = NULL, final_markdown = NULL WHERE id = <signal_id> AND state = 'done'`. Verify:
    - Happens in same DB transaction as the state='completed' write (atomic all-or-nothing)
    - Only fires on `state = 'done'` (or 'completed' — reconcile naming with brief §4.9; brief says 'done' but 34-value CHECK set has 'completed' as terminal)
    - Verify which value is correct: dispatched brief says `state='done'` per §4.9 quote, but KBL-B terminal is `'completed'` per §3.2. Flag if there's a naming drift.

#### Mock-mode

16. **`BAKER_VAULT_DISABLE_PUSH=true`** — commit happens locally, push skipped. Verify test asserts `git push` NOT called in mock-mode, `git commit` IS called.
17. **Default OFF** — production (Render / Mac Mini) pushes normally. Verify env parsing defaults to false on unset.

#### State machine + pipeline_tick

18. **State transitions:** `awaiting_commit` → `commit_running` → `completed` (success) OR `commit_failed`. All in 34-value CHECK set. Verify.
19. **Terminal state** — after `completed`, signal not re-claimable. Verify `_process_signal` stops after Step 7 success.
20. **`finalize_failed` gated out** — `_process_signal` does NOT call Step 7 on `finalize_failed` signals (they're routed to inbox per §4.7). Verify test.
21. **`_process_signal` full 7-step happy path** — one test that walks a signal from `pending` → `completed` touching all 7 step functions in order. Verify.

#### Failure modes (per brief)

22. **Filesystem write failure** (disk full, permission) → `commit_failed`, ERROR log, unwound. Verify.
23. **Atomic-all-or-nothing for cross-links** — if one cross-link write fails, ALL writes in this lock window rollback (git reset + clean). Verify test.
24. **Flock timeout** — `VaultLockTimeoutError` → `commit_failed`, WARN log. Verify.

#### CHANDA

25. **Q1 Loop Test** — Step 7 is the Leg 1 *producer* (writes files that future signals read as Gold). No Leg READ in Step 7. Verify cited.
26. **Q2 Wish Test** — Step 7 closes the loop — Silver becomes vault-visible. Wish-aligned.
27. **Inv 4** — FS-level guard verified (scrutiny item 2).
28. **Inv 6** — Step 7 is terminal; Step 6 was mandatory upstream. Structural.
29. **Inv 8** — Pydantic already enforced at Step 6; Step 7 doesn't re-validate.
30. **Inv 9** — operationalized. Positive test.
31. **Inv 10** — no prompts.

### Format

`briefs/_reports/B2_pr16_review_20260419.md`
Verdict: APPROVE / REDIRECT / BLOCK

### Timeline

~60-90 min. Biggest moving-parts surface (filesystem + git + flock + multi-file atomicity + TOAST). Review rigorously — post-merge this code runs against real Director vault.

### Dispatch back

> B2 PR #16 review done — `briefs/_reports/B2_pr16_review_20260419.md`, commit `<SHA>`. Verdict: <...>.

On APPROVE: I auto-merge PR #16. **7 of 7 pipeline steps on main. Cortex T3 Phase 1 SHIPPED.**

---

## Working-tree reminder

Work in `~/bm-b2` (never /tmp). **After this review: quit the Terminal tab** — memory hygiene.

---

*Posted 2026-04-19 by AI Head. Final pipeline PR. Review pushes us from 6/7 → 7/7 → Phase 1 complete.*
