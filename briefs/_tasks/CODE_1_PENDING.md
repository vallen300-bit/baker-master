# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** PR #15 STEP6-FINALIZE-IMPL merged at `4cb47e1a`. 6 of 7 pipeline steps on main.
**Task posted:** 2026-04-19 (afternoon)
**Status:** OPEN — THE LAST PIPELINE STEP

---

## Task: STEP7-COMMIT-IMPL — Vault commit + push under flock mutex

**Spec:** KBL-B brief §4.8 (lines 424-431) + §4.9 (TOAST cleanup).

### Why — plain English

Step 7 is where the pipeline actually writes to the vault. Everything before has been PG columns. Step 7 takes the `final_markdown` + cross-link stubs that Steps 5-6 produced, writes them as real Markdown files under `~/baker-vault/wiki/`, runs `git commit`, and pushes to GitHub. This is where Silver becomes **visible to Director in Obsidian / GitHub / any vault reader**. The loop closes here.

Because git push is destination-exclusive (only one machine can push cleanly at a time), Step 7 runs on Mac Mini (the always-on agent-writer host per CHANDA Inv 9 clarification). **But the code you write is deploy-agnostic** — same Python can run on your dev Mac for testing or Mac Mini in production. Env var `BAKER_VAULT_PATH` + configurable git remote + `flock` mutex handle the coordination.

### Scope

**IN**

1. **`kbl/steps/step7_commit.py`** — the committer:

   - `commit(signal_id: int, conn) -> None` — full pipeline:
     - Load `final_markdown` + `target_vault_path` from `signal_queue`
     - Load unrealized cross-link stubs: `SELECT * FROM kbl_cross_link_queue WHERE source_signal_id=%s AND realized_at IS NULL`
     - Acquire `flock` on `~/baker-vault/.lock` (env var `BAKER_VAULT_LOCK_PATH` override; default `{vault}/.lock`)
     - Inside lock:
       - `git pull --rebase origin main` (sync before write)
       - Write `final_markdown` to `{vault}/{target_vault_path}` via atomic write (`tempfile.NamedTemporaryFile(dir=vault_dir) + os.replace`)
       - For each cross-link stub: append-or-replace `stub_row` to `{vault}/wiki/{target_slug}/_links.md` via atomic write. Idempotent — if file has a stub line matching `<!-- stub:signal_id={id} -->` already, REPLACE that line; otherwise append sorted by `created` DESC (newest at top).
       - `git add <target_vault_path> wiki/<slug>/_links.md [...]`
       - `git commit` with message `Silver: {primary_matter} — {title} (sig:{short_id})` under pipeline identity
       - `git push origin main` — retry once on rebase conflict (`git pull --rebase && git push`)
     - On success (lock released): update `signal_queue` row with `state='done'`, `committed_at=NOW()`, `commit_sha=<SHA from HEAD>`; UPDATE `kbl_cross_link_queue` set `realized_at=NOW()` for the processed stubs
     - Post-commit TOAST cleanup (§4.9): in the same DB transaction, `UPDATE signal_queue SET opus_draft_markdown = NULL, final_markdown = NULL WHERE id = <signal_id> AND state = 'done'`

   - **State transitions:** `awaiting_commit` → `commit_running` → `completed` (success) OR `commit_failed` (hard failure). All in 34-value CHECK set.

   - **Failure modes:**
     - Git push fails twice (rebase retry exhausted) → `commit_failed`, WARN log, signal re-claimable by next tick
     - Filesystem write fails (disk full, permission denied) → `commit_failed`, ERROR log, do NOT commit or push
     - `flock` timeout after 60s → `commit_failed`, WARN log (another process holds the lock too long; probably stuck — operator investigates)
     - Cross-link stub write fails for one target_slug but others succeed: rollback ALL file writes in this lock window, raise `CommitError`, state → `commit_failed`. Atomic-all-or-nothing semantic.

2. **`kbl/exceptions.py`** — add `CommitError(KblError)` + `VaultLockTimeoutError(KblError)` (subclass of CommitError). Net-additive.

3. **Env vars:**
   - `BAKER_VAULT_PATH` — required; absolute path to baker-vault clone (dev Mac: `~/baker-vault`; Mac Mini prod: `~/baker-vault`)
   - `BAKER_VAULT_LOCK_PATH` — optional; default `{BAKER_VAULT_PATH}/.lock`
   - `BAKER_VAULT_FLOCK_TIMEOUT_SECONDS` — optional; default 60
   - `BAKER_VAULT_GIT_IDENTITY_NAME` — optional; default `Baker Pipeline`
   - `BAKER_VAULT_GIT_IDENTITY_EMAIL` — optional; default `pipeline@brisengroup.com`
   - `BAKER_VAULT_GIT_REMOTE` — optional; default `origin`
   - Missing required env → `RuntimeError` at module import (fail-fast)

4. **`pipeline_tick.py` wire-up** — extend `_process_signal` one more hop:
   - `awaiting_commit` → call `commit()` → `completed`
   - Update tx-boundary docstring to reflect Step 7 presence
   - The `hasattr` sentinel that B1 wrote in the previous round (per B2's note in PR #14 review) becomes obsolete once Step 7 lands — remove or replace with final-state check.

5. **`flock` helper — `kbl/_flock.py`** (or inline in step7_commit.py):
   - Cross-platform: POSIX `fcntl.flock` on Mac/Linux. Don't worry about Windows.
   - Context manager `acquire_vault_lock(lock_path: str, timeout_seconds: int) -> ContextManager[None]`
   - On timeout: raise `VaultLockTimeoutError`
   - On exit: release cleanly (even if exception raised inside)

6. **Mock-mode for local testing (critical):**
   - `BAKER_VAULT_DISABLE_PUSH=true` env var → same code path, but skips `git push origin main`. Commit still happens locally. Useful for dev Mac testing without touching GitHub.
   - **Default OFF** — on Render/Mac Mini production, push happens.

7. **Tests — `tests/test_step7_commit.py`:**
   - **Happy path:** single signal with `final_markdown` + 1 cross-link → files written, git commit happens, push mocked → success → state transitions + commit_sha + realized_at + TOAST cleanup all verified. Use a temp git repo as fixture (`tmp_path`).
   - **No cross-links:** signal with `related_matters=[]` → only main file written, no `_links.md` writes. Verify.
   - **Cross-link idempotency:** re-run same signal → second run is a no-op (nothing unrealized) OR re-emits stubs if `realized_at=NULL`. Verify.
   - **Rebase retry:** first `git push` fails (non-fast-forward), rebase retry succeeds. Verify.
   - **Rebase exhausted:** both push attempts fail → `commit_failed`, WARN log. Verify.
   - **Flock timeout:** simulated concurrent hold → `VaultLockTimeoutError` raised. Verify.
   - **Filesystem write failure:** mock `os.replace` to raise `OSError` → `commit_failed`, no partial state. Verify.
   - **Atomic-all-or-nothing:** main file succeeds, one cross-link fails → all writes rolled back (via temp → rename pattern), nothing committed, state → `commit_failed`.
   - **TOAST cleanup:** after `state='done'`, verify `opus_draft_markdown` and `final_markdown` are NULL.
   - **CHANDA Inv 9 positive test:** this is THE step that writes to vault. No assertions of "zero writes" here; instead assert writes go ONLY to `{BAKER_VAULT_PATH}/wiki/**` (never outside the vault).
   - **Mock-mode:** `BAKER_VAULT_DISABLE_PUSH=true` → push is not called but commit is. Verify.

8. **Extend `tests/test_pipeline_tick.py`:** add a test for the full 7-step happy path through `_process_signal`. End state: `completed`.

### CHANDA pre-push

- **Q1 Loop Test:** Step 7 touches **Leg 1** indirectly — the file it writes becomes the Gold-read source for future signals in the same matter. Verify: no Gold-read happens *within* Step 7 (that's Step 5's job). Pass.
- **Q2 Wish Test:** Step 7 serves wish directly — it closes the loop from Silver-draft to visible-vault-entry. Without it, the pipeline is theater.
- **Inv 4** (author-director files untouched) — Step 7 MUST NOT overwrite any file where the current content has `author: director`. **Guard test:** if `target_vault_path` exists and has `author: director` frontmatter, raise `CommitError` → `commit_failed`. Operator investigates the collision (likely a signal pointing at a promoted-Gold path — Step 6 slug collision bug upstream).
- **Inv 6** — Step 7 is terminal. After this, signal is `completed`. Pipeline never skips Step 6 — but Step 6 is upstream, so this is verified by the fact that Step 7 is only called from `_process_signal` AFTER Step 6 succeeds.
- **Inv 8** — structural enforcement already happened at Step 6 via Pydantic. Step 7 doesn't re-validate.
- **Inv 9** — Step 7 is THE Mac Mini agent-writer. This is where Inv 9 is OPERATIONALIZED, not violated. Positive test (writes land in vault) + negative test (no writes outside `{BAKER_VAULT_PATH}/wiki/`).
- **Inv 10** — no prompts.

### Branch + PR

- Branch: `step7-commit-impl`
- Base: `main`
- PR title: `STEP7-COMMIT-IMPL: kbl/steps/step7_commit.py + vault write + flock + git commit/push`
- Target PR: #16

### Reviewer

B2.

### Timeline

~90-120 min. Biggest moving-parts surface (filesystem + git + flock + multi-file atomicity + mock-mode). Flag AI Head if scope exceeds 2 hours.

### Dispatch back

> B1 STEP7-COMMIT-IMPL shipped — PR #16 open, branch `step7-commit-impl`, head `<SHA>`, <N>/<N> tests green. Mock-mode BAKER_VAULT_DISABLE_PUSH verified. pipeline_tick _process_signal extended to terminal state `completed`. Ready for B2 review.

### After this task

- B2 reviews PR #16 → auto-merge on APPROVE.
- AI Dennis completes Mac Mini infra prep (items 1-4 from `briefs/_tasks/AI_DENNIS_MAC_MINI_STEP7_PREP.md`; items 5-6 land after your code merges).
- After PR #16 merges: **7 of 7 pipeline steps on main**. Phase 1 complete. T3 pipeline ships.
- Next B1 ticket: KBL-C handler implementations (ayoniso dispatcher, WhatsApp reply handler, vault-edit watcher, dashboard feeder) — AI Head authors the KBL-C §4-10 brief + OQs resolution sequence first.
- Also track: PR #15 S2 (`_increment_retry_count` DDL in hot path) + 4 nice-to-haves (stale docstring, commit-before-raise consistency, `_inbox` special-case) — consolidate into a single Phase-1-polish PR after Step 7 ships. NOT in this dispatch scope.

---

## Working-tree reminder

**Never /tmp/** — use `~/bm-b1` or `~/Desktop/baker-code` (where you were for PR #15). Survives reboots.

**After shipping PR #16: quit your Terminal tab and start fresh** for the next task. Releases Claude Code CLI memory.

---

*Posted 2026-04-19 by AI Head. The final pipeline step. Parallel: AI Dennis doing Mac Mini infra. Code is deploy-agnostic — test on your dev Mac, deploys to Mac Mini when ready.*
