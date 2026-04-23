# BRIEF: MAC_MINI_WRITER_AUDIT_1 — CHANDA #9 operational runbook + #4 hook-stage fix

## Context

Bundles two related vault-writer integrity concerns:

1. **CHANDA #9** (Mac Mini single writer) — tier `critical`, method `infra-level`, detector: *(no script — Render has no push credentials)*. Per Research matrix §Recommendation step 4: "Audit + document detector #9 in operational runbook. No code, but explicit." This brief ships the runbook.

2. **CHANDA #4 hook stage bug** (surfaced 2026-04-23 during KBL_SCHEMA_1 vault mirror; captured in `feedback_chanda_4_hook_stage_bug.md`). `author_director_guard.sh` is installed at `pre-commit` on Mac Mini, but the script reads `.git/COMMIT_EDITMSG` which git doesn't populate until AFTER pre-commit fires. Result: the marker-based gate doesn't actually gate `git commit -F` / `git commit -m` flows — AI Head's own KBL_SCHEMA_1 mirror (`07089e3`) had to temp-bypass the hook to commit. Script itself is correct; install stage is wrong.

   **Fix:** re-install as `commit-msg` hook (where `$1` IS the message-file path, which the script already handles via `${1:-.git/COMMIT_EDITMSG}` fallback — it's been forward-compatible with commit-msg stage since day one). No code change to the script.

**What this brief ships:**

1. `_ops/runbooks/mac-mini-vault-writer-audit.md` in baker-master — operational runbook for CHANDA #9 (monthly Render permission audit, Mac Mini uptime check, SSH key rotation note, escalation path).
2. `CHANDA_enforcement.md` §6 clarification: detector #4 stage renamed `pre-commit` → `commit-msg` (script path + integration-point column). Plus §7 amendment-log row.
3. pytest addition: a single test case validating the script works when invoked as a commit-msg hook (path-as-$1 with marker-containing file).

**Delivery path:** All changes in baker-master. Post-merge AI Head action on Mac Mini: `mv .git/hooks/pre-commit .git/hooks/commit-msg` (or symlink), smoke-test, clean pre-commit.

**Source artefacts:**
- Research engineering matrix: `_ops/ideas/2026-04-21-chanda-engineering-matrix.md` §6 + §Recommendation step 4
- Hook bug memory: `memory/feedback_chanda_4_hook_stage_bug.md`
- Vault-writer anchor: `memory/project_mac_mini_role.md` + CLAUDE.md §AI Agent Shadow System

## Estimated time: ~1.5h
## Complexity: Low (docs + 1 test + 1 file move — no script logic changes)
## Prerequisites: PR #49 AUTHOR_DIRECTOR_GUARD_1 merged `679a684`. PR #52 KBL_SCHEMA_1 merged `a47125c`.

---

## Fix/Feature 1: `_ops/runbooks/mac-mini-vault-writer-audit.md`

### Problem

CHANDA invariant #9 is enforced by absence (Render has no push credentials for baker-vault). No operational runbook exists to periodically verify this state or escalate if it weakens.

### Current State

- `_ops/runbooks/` directory does NOT exist in baker-master. This brief creates it.
- Mac Mini is the single known vault writer (SSH alias `macmini`, path `~/baker-vault`).
- Render service ID for Baker: per `reference_render_api_ops.md` in memory.

### Implementation

**Create** `_ops/runbooks/mac-mini-vault-writer-audit.md`:

```markdown
---
title: Mac Mini Vault Writer Audit
type: runbook
invariant: CHANDA-9
cadence: monthly
owner: AI Head
updated: 2026-04-23
---

# Mac Mini Vault Writer Audit — CHANDA #9

## Purpose

CHANDA invariant #9 (tier: critical) requires that baker-vault has **exactly one writer**: the Mac Mini at SSH alias `macmini`. Enforcement is infra-level — Render has no push credentials for the vault repo, and no other machine has `github-baker-vault:` SSH config or deploy key.

This runbook verifies the invariant monthly. If any check fails, the invariant is silently weakened and must be restored before the next pipeline write.

## Audit cadence

**Monthly** on the first Monday of the month (co-firing with `ai_head_weekly_audit` cron is acceptable; separate execution preferred).

## Checks

### 1. Mac Mini is reachable + has the vault checkout

```bash
ssh macmini 'cd ~/baker-vault && git remote -v && git rev-parse HEAD'
```

Expect:
- SSH succeeds (no password prompt, alias resolves).
- `git remote -v` lists `origin` pointing at `github-baker-vault:vallen300-bit/baker-vault.git` (or equivalent SSH URL).
- `git rev-parse HEAD` returns a SHA within 48h of the latest origin/main.

### 2. Render has NO push credentials for baker-vault

Via Render MCP or dashboard — list deploy keys + env vars for the Baker service:

```bash
# If Render MCP is available:
curl -s "https://api.render.com/v1/services/${BAKER_SVC_ID}/env-vars" \
  -H "Authorization: Bearer $RENDER_TOKEN" | jq '.[] | select(.key | test("(?i)vault|ssh|deploy"))'
```

**Reject:** any env var named like `BAKER_VAULT_SSH_KEY`, `VAULT_DEPLOY_KEY`, `GITHUB_VAULT_TOKEN` with a populated `value`. Presence of such a var is a CHANDA #9 breach in progress — investigate, rotate, remove.

Also check GitHub repo settings manually (`Settings > Deploy keys` for the vault repo) — confirm only the Mac Mini's public key is listed. Zero other keys.

### 3. No recent vault commits originating from non-Mac-Mini machines

```bash
ssh macmini 'cd ~/baker-vault && git log --format="%H %ae %s" origin/main -20'
```

Review committer emails. Expected committers:
- `dimitry.vallen@...` (Director, manual commits allowed per Inv 9: single AGENT writer, Director writes welcome from any machine)
- `ai-head@brisengroup.com` (AI Head SSH from Mac Mini — verifiable via `git log --format="%cn %ce %cD"` + machine of record)
- Pipeline-bot identities (Mac Mini-origin only)

**Reject:** any commit from an identity tagged as another agent / Render service / CI.

### 4. CHANDA #4 hook is installed + executable on Mac Mini

```bash
ssh macmini 'ls -l ~/baker-vault/.git/hooks/commit-msg ~/baker-vault/.git/hooks/pre-commit 2>/dev/null'
```

Per the 2026-04-23 hook-stage fix (MAC_MINI_WRITER_AUDIT_1 Feature 2), the hook is at `.git/hooks/commit-msg` with mode `-rwxr-xr-x` and size ~3562 bytes. `pre-commit` may exist as `.sample` or removed — either is fine.

Smoke test:

```bash
ssh macmini 'cd /tmp && rm -rf vault-smoketest && git init -q vault-smoketest && cd vault-smoketest && \
  git config user.email "test@test" && git config user.name "test" && \
  printf -- "---\nauthor: director\n---\nbody\n" > hot.md && \
  git add hot.md && git commit -qm seed && \
  printf -- "---\nauthor: director\n---\nmodified\n" > hot.md && \
  git add hot.md && \
  cp ~/baker-vault/.git/hooks/commit-msg .git/hooks/commit-msg && \
  chmod +x .git/hooks/commit-msg && \
  (git commit -m "no marker" 2>&1 || true) | tail -3'
```

Expect: "CHANDA invariant #4" rejection message. Then confirm marker-positive path:

```bash
ssh macmini 'cd /tmp/vault-smoketest && git commit -m "tweak\n\nDirector-signed: \"smoke test\"" 2>&1 | tail -2'
```

Expect: commit succeeds.

### 5. SSH key rotation stale check

```bash
ssh macmini 'stat -f %Sm ~/.ssh/id_ed25519 2>/dev/null || stat -c %y ~/.ssh/id_ed25519 2>/dev/null'
```

If key is >365 days old, note for Director — key rotation is a Director-level action (§4 #13 security policy change).

## Escalation

Any check failing → Slack DM Director at channel `D0AFY28N030` with:
- Which check failed
- Evidence (command output, file state)
- Proposed remediation (but do NOT execute without Director ratify if the fix touches §4 security-policy prerogatives)

## Lessons captured

- **2026-04-23** — Hook stage bug (CHANDA #4 was at pre-commit, needed commit-msg). Surfaced during KBL_SCHEMA_1 vault mirror. Fixed by MAC_MINI_WRITER_AUDIT_1 Feature 2. Future script deployments: test `git commit -F` flow, not only direct-arg `bash .git/hooks/<hook>` invocation.

## Amendment log

| Date | Change | Authority |
|------|--------|-----------|
| 2026-04-23 | Initial creation (MAC_MINI_WRITER_AUDIT_1) | Director "default recom is fine" (2026-04-23) |
```

### Key Constraints

- **Location:** `_ops/runbooks/` is a NEW directory in baker-master. Create it; do not place the runbook elsewhere.
- **No baker-vault writes** from this file's creation. B-code stages in baker-master only.
- **Do not check Render credentials in CI.** This is a Director-level sensitive op; runbook instructs the auditor (AI Head) to run the Render check manually per cadence.

### Verification

1. File exists at `_ops/runbooks/mac-mini-vault-writer-audit.md`.
2. YAML frontmatter parses: `python3 -c "import yaml; raw = open('_ops/runbooks/mac-mini-vault-writer-audit.md').read(); yaml.safe_load(raw.split('---')[1])"` — no errors.
3. File contains 5 numbered audit checks: `grep -c "^### [0-9]\." _ops/runbooks/mac-mini-vault-writer-audit.md` → 5.

---

## Fix/Feature 2: CHANDA_enforcement.md §6 — correct detector #4 stage

### Problem

`CHANDA_enforcement.md` §6 currently describes detector #4 as "pre-commit hook" which is where it's installed but NOT where it actually works. Text must reflect the commit-msg reality.

### Current State

Existing §6 row (after PR #49 + #51 amendments):

```
| #4 Author:director files | `invariant_checks/author_director_guard.sh` | pre-commit hook | git hook + CI |
```

### Implementation

**Step 1 — Edit `CHANDA_enforcement.md` §6 row for #4.** Replace `pre-commit hook` with `commit-msg hook`; integration-point stays `git hook + CI`.

New row text:
```
| #4 Author:director files | `invariant_checks/author_director_guard.sh` | commit-msg hook | git hook + CI |
```

**Step 2 — Append §7 amendment-log row:**

```
| 2026-04-23 | §6 detector #4 | Stage corrected: `pre-commit` → `commit-msg`. pre-commit fires BEFORE `-F`/`-m` message is written to `.git/COMMIT_EDITMSG`, making marker check unreliable. commit-msg receives message-file path as `$1` (which the existing script already handles via `${1:-.git/COMMIT_EDITMSG}` fallback — no script change required). (MAC_MINI_WRITER_AUDIT_1, PR TBD) | Hook-bug surfaced during KBL_SCHEMA_1 vault mirror 2026-04-23 |
```

### Key Constraints

- **Do not modify §4 row #4 text itself** (the invariant description is unchanged — the enforcement DETAIL changed, not the invariant).
- **Keep Markdown table alignment** — pipe separators + spacing.
- **§7 row goes at end of amendment-log table** (after the 2026-04-23 #2 LEDGER_ATOMIC_1 row).

### Verification

1. `grep "commit-msg hook" CHANDA_enforcement.md` — exactly 1 hit (the updated §6 row).
2. `grep -c "pre-commit hook" CHANDA_enforcement.md` — exactly 0 (the old text is gone).
3. `grep -c "^| 2026-04" CHANDA_enforcement.md` → 4 (2026-04-21 initial, 2026-04-23 #4 stage from PR #49, 2026-04-23 #2 from PR #51, 2026-04-23 #6 from this PR).
4. `tail -1 CHANDA_enforcement.md` → the new 2026-04-23 §6 row.

---

## Fix/Feature 3: Test case validating script works at commit-msg stage

### Problem

Existing `tests/test_author_director_guard.py` tests invoke the script via `_run_hook(repo, commit_msg)` which passes the message-file path as `$1` — exactly how commit-msg stage invokes it. Those tests already validate the commit-msg pathway.

But the tests don't explicitly DOCUMENT that they prove commit-msg-stage viability. This brief adds a single test that makes the commit-msg invocation CONVENTION explicit, so future readers know the script is stage-certified.

### Current State

`tests/test_author_director_guard.py` has 6 tests. `_run_hook()` helper writes the message to `repo/.git/COMMIT_EDITMSG` then invokes `bash HOOK_SCRIPT msg_path`. That's semantically identical to git's commit-msg invocation.

### Implementation

**Append one test** to `tests/test_author_director_guard.py`:

```python
def test_hook_works_as_commit_msg_stage_via_git_commit(tmp_path: Path):
    """Scenario 7: install the hook as .git/hooks/commit-msg and verify
    the full git-commit flow (end-to-end, no direct-arg invocation).

    This documents that the existing script is commit-msg-stage
    compatible, supporting the MAC_MINI_WRITER_AUDIT_1 install change.
    """
    repo = _init_repo(tmp_path)
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        seed body
    """).lstrip())
    _stage(repo, "hot.md")
    _commit_clean(repo, "seed hot.md")

    # Install script as commit-msg hook.
    hook_dst = repo / ".git" / "hooks" / "commit-msg"
    hook_dst.write_text(HOOK_SCRIPT.read_text())
    hook_dst.chmod(0o755)

    # Attempt commit WITHOUT marker — expect hook reject.
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        modified without marker
    """).lstrip())
    _stage(repo, "hot.md")
    result = subprocess.run(
        ["git", "commit", "-m", "no marker"],
        cwd=repo, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "CHANDA invariant #4" in (result.stdout + result.stderr)

    # Attempt commit WITH marker — expect success.
    _write(repo / "hot.md", textwrap.dedent("""
        ---
        author: director
        ---
        modified with marker
    """).lstrip())
    _stage(repo, "hot.md")
    msg = 'wiki(hot.md): tweak\n\nDirector-signed: "commit-msg stage test"\n'
    result = subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=repo, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
```

### Key Constraints

- **Append to existing test file** — do not duplicate the `_init_repo` / `_write` / `_stage` / `_commit_clean` helpers.
- **Uses `-m` flag** specifically (not `-F`) — `-m` is the most common direct-invocation path and the one most likely to regress silently. `-F` path is covered implicitly.
- **Hook installed as `commit-msg`** — not `pre-commit`. This is the test that would have caught the bug in the first place.
- **No mocks.** Real git, real hook.

### Verification

1. `pytest tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit -v` → green.
2. Full test file: `pytest tests/test_author_director_guard.py -v` → 7 passed (was 6).
3. `pytest tests/ 2>&1 | tail -3` — +1 pass from main, 0 regressions.

---

## Files Modified

- NEW directory `_ops/runbooks/`.
- NEW `_ops/runbooks/mac-mini-vault-writer-audit.md` (~120 lines).
- MODIFIED `CHANDA_enforcement.md` — 1 row updated in §6 + 1 row appended to §7.
- MODIFIED `tests/test_author_director_guard.py` — +1 test function (~45 LOC).

## Do NOT Touch

- `invariant_checks/author_director_guard.sh` — script is correct. Stage is wrong; install (AI Head post-merge) fixes that.
- Any file under `baker-vault/` or `~/baker-vault/` — Mac Mini is sole writer.
- `CHANDA.md` — directional file; paired rewrite is separate brief.
- `slugs.yml`, `people.yml`, `entities.yml`, `vault_scaffolding/` — unrelated.
- `models/cortex.py`, `memory/store_back.py`, `triggers/embedded_scheduler.py`, `invariant_checks/ledger_atomic.py` — unrelated.

## Quality Checkpoints

1. **YAML frontmatter parses:**
   ```
   python3 -c "import yaml; raw = open('_ops/runbooks/mac-mini-vault-writer-audit.md').read(); d = yaml.safe_load(raw.split('---')[1]); assert d['type'] == 'runbook' and d['invariant'] == 'CHANDA-9'"
   ```
   Expect: zero output.

2. **Runbook has 5 numbered checks:**
   ```
   grep -c "^### [0-9]\." _ops/runbooks/mac-mini-vault-writer-audit.md
   ```
   Expect: `5`.

3. **CHANDA_enforcement.md stage correction:**
   ```
   grep "commit-msg hook" CHANDA_enforcement.md    # expect 1
   grep -c "pre-commit hook" CHANDA_enforcement.md # expect 0
   grep -c "^| 2026-04" CHANDA_enforcement.md      # expect 4
   ```

4. **Test syntax clean:**
   ```
   python3 -c "import py_compile; py_compile.compile('tests/test_author_director_guard.py', doraise=True)"
   ```

5. **New test passes:**
   ```
   pytest tests/test_author_director_guard.py::test_hook_works_as_commit_msg_stage_via_git_commit -v
   ```
   Expect `1 passed`.

6. **Full GUARD_1 test file still green:**
   ```
   pytest tests/test_author_director_guard.py -v
   ```
   Expect `7 passed`.

7. **Regression delta:**
   ```
   pytest tests/ 2>&1 | tail -3
   ```
   Expect +1 pass vs main baseline at dispatch time.

8. **Singleton hook still green:**
   ```
   bash scripts/check_singletons.sh
   ```

9. **No baker-vault writes in diff:**
   ```
   git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
   ```

## Rollback

- `git revert <merge-sha>` — reverts runbook + §6 text + test.
- Vault-side hook state is untouched by this PR (AI Head does the install SSH-side post-merge). Rollback = leave pre-commit hook in place, skip the re-install.

---

## Ship shape

- **PR title:** `MAC_MINI_WRITER_AUDIT_1: CHANDA #9 runbook + #4 hook-stage correction (commit-msg)`
- **Branch:** `mac-mini-writer-audit-1`
- **Files:** 3 — 1 new (runbook) + 2 modified (CHANDA_enforcement.md + test file).
- **Commit style:** `chanda(#9+#4): vault-writer audit runbook + hook-stage correction to commit-msg`
- **Ship report:** `briefs/_reports/B1_mac_mini_writer_audit_1_20260423.md`. Include all 9 Quality Checkpoint outputs + pre-change baseline.

**Tier A auto-merge on B3 APPROVE** (standing per charter §3).

## Post-merge (AI Head, not B-code)

AI Head post-merge actions (autonomous per charter §3):

1. SSH Mac Mini. Re-install CHANDA #4 hook at commit-msg stage:
   ```
   ssh macmini
   cd ~/baker-vault
   mv .git/hooks/pre-commit .git/hooks/commit-msg
   chmod +x .git/hooks/commit-msg
   # Clean pre-commit to avoid confusion:
   ls .git/hooks/pre-commit 2>/dev/null && echo "STRAY — remove or replace"
   ```
2. Smoke-test via the runbook's check #4 commands (marker-negative rejects, marker-positive allows). Both via `git commit -m` and `git commit -F`.
3. Log AI Head action to `actions_log.md`.
4. Run the runbook's full monthly audit (checks 1-5) for the first time; record results.
5. Director-local baker-master hook install remains deferred (requires Director's laptop action).

## Timebox

**1.5h.** If >2.5h, stop and report — docs brief should not exceed this.

**Working dir:** `~/bm-b1`.
