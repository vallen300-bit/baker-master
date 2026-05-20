# BRIEF: RENDER_ENV_WIPE_PRECOMMIT_GUARD_1 — pre-commit hook (Part 4) blocking the 2026-05-17 wipe pattern at git time

## Context

The 2026-05-17 Render env-var wipe (`srv-d6dgsbctgctc73f55730`, ~30 secret-class vars destroyed, 3-day silent degradation, full restoration 2026-05-20) was caused by a raw array-form `PUT /v1/services/{id}/env-vars` call that REPLACED the full env set instead of merging a single key.

`tools/render_env_guard.safe_env_put()` shipped 2026-05-17 (BRIEF_RENDER_ENV_WRITE_GUARD_1, B3) blocks the wipe pattern at the Python-import level. But the original brief explicitly carved out two non-goals:
- "Does NOT block bash/curl invocations directly"
- "Does NOT introduce a server-side audit hook"

Result: any committed Python file that does `httpx.put(...)` or `requests.put(...)` to `/env-vars` directly (without importing the wrapper), or any committed bash/curl that does `curl -X PUT .../env-vars` with a JSON array body, can still wipe the env on next run. The 1Password manifest + restoration playbook (2026-05-20) is the recovery contract; this brief is the prevention contract.

Director-ratified 2026-05-20 ("go" after reviewing the partial-coverage gap).

### Surface contract: N/A — pure backend git hook + Python tests. No clickable surface, no frontend, no Slack/email/Block-Kit, no dashboard route. Bypass mechanism is the standard `git commit --no-verify` (no UI involvement).

## Estimated time: ~45-60 builder-minutes
## Complexity: Low
## Prerequisites
- `.githooks/pre-commit` already exists with Parts 1-3 (migration / subagent-location / retired-model-IDs).
- `git config core.hooksPath .githooks` already standard in this repo (per repo CLAUDE.md).
- `tools/render_env_guard.py` + `tests/test_render_env_guard.py` already shipped 2026-05-17 (BRIEF_RENDER_ENV_WRITE_GUARD_1, B3).

## API version / deprecation / fallback
- **Render API endpoint contracts:** verified live 2026-05-20.
  - PUT `/v1/services/{id}/env-vars` (array body `[{...}, ...]`) → REPLACES entire env set (foot-cannon).
  - PUT `/v1/services/{id}/env-vars/{KEY}` (object body `{"value": "..."}`) → MERGES single key (safe).
  - 2026-05-20 restoration used 27 successful single-key PUTs with zero collateral damage as live proof the safe path works.
- **Vendor deprecation:** none announced. Endpoint shape stable since Render API v1.
- **Fallback if hook misfires on legit code:** `git commit --no-verify` (same escape hatch as Parts 1-3). Document the bypass path in the error message.

---

## Fix/Feature 1: Pre-commit Part 4 — render env-var wipe-pattern detection

### Problem
Today's protection layers leave a gap:

| Layer | Catches | Misses |
|---|---|---|
| `safe_env_put()` runtime wrapper (Python) | Python code that imports the wrapper | Python code that bypasses the wrapper; ANY bash/curl |
| `.claude/rules/python-backend.md` rule | Future Claude sessions that read the rule | Sessions that don't read the rule; non-Python code |
| 1P manifest + restoration playbook | Recovery after a wipe | Prevention of the next wipe |

A pre-commit hook closes the gap by scanning EVERY staged diff (Python, bash, anything) for the dangerous URL pattern. This is layered prevention, not a replacement for the runtime guard.

### Current state
`.githooks/pre-commit` exists with three parts:
- **Part 2** (lines ~28-37): subagent location enforcement (NO BYPASS).
- **Part 3** (lines ~41-65): retired Anthropic model ID enforcement (NO BYPASS).
- **Part 1** (lines ~68-78): migration immutability — uses `exec` to hand control to `scripts/check_applied_migrations.sh`, so anything after Part 1 never runs.

**Insertion point: AFTER Part 3, BEFORE Part 1's `exec`.** Otherwise Part 4 never fires.

### Implementation

**A. Add Part 4 to `.githooks/pre-commit`** between Part 3's `fi` (line ~65) and Part 1's header comment (line ~67):

```bash
# ---------------------------------------------------------------------------
# Part 4: render env-var wipe-pattern detection (NO BYPASS except --no-verify)
# Catches the 2026-05-17 wipe pattern at commit time. Layered above
# tools/render_env_guard.safe_env_put() runtime guard — the wrapper protects
# imported-Python paths; this hook protects bash/curl/raw-httpx escape routes.
# ---------------------------------------------------------------------------
RENDER_ENV_GUARD_ALLOWLIST_RE='^(tools/render_env_guard\.py|tests/test_render_env_guard\.py|tests/test_pre_commit_env_guard\.py|briefs/.*|tasks/lessons\.md|\.claude/rules/python-backend\.md|\.githooks/pre-commit)$'

STAGED_NON_ALLOWLISTED="$(git diff --cached --name-only --diff-filter=ACMR | grep -Ev "$RENDER_ENV_GUARD_ALLOWLIST_RE" || true)"

if [ -n "$STAGED_NON_ALLOWLISTED" ]; then
  # Pattern: PUT to /env-vars NOT followed by /KEY.
  # Catches both:
  #   curl -X PUT https://api.render.com/v1/services/srv-xxx/env-vars -d '[...]'
  #   httpx.put(f".../services/{sid}/env-vars", json=[...])
  # by detecting the URL shape that ends at /env-vars (no /KEY suffix).
  OFFENDERS=""
  for f in $STAGED_NON_ALLOWLISTED; do
    if git diff --cached -- "$f" | grep -E '^\+' | grep -vE '^\+\+\+ ' | grep -qE 'services/[^/[:space:]"]+/env-vars($|[^/A-Za-z0-9_])'; then
      OFFENDERS="$OFFENDERS $f"
    fi
  done
  if [ -n "$OFFENDERS" ]; then
    echo "[pre-commit] BLOCKED (Part 4): staged diff contains a raw PUT to /env-vars (no /KEY suffix)." >&2
    echo "[pre-commit] This is the 2026-05-17 wipe pattern. Array-form PUT REPLACES the entire env set." >&2
    echo "[pre-commit] Use tools.render_env_guard.safe_env_put(service_id, KEY, value) — single-key PUT path." >&2
    echo "[pre-commit] Offending files:" >&2
    for f in $OFFENDERS; do echo "  - $f" >&2; done
    echo "[pre-commit] If you genuinely need the array form (you don't), bypass with: git commit --no-verify" >&2
    exit 1
  fi
fi
```

**B. New test file `tests/test_pre_commit_env_guard.py`** — pytest using `subprocess` to invoke the hook against fixture-staged diffs. Pattern mirrors how `tests/test_render_env_guard.py` mocks but here we drive the actual hook process:

Implementation approach: each test creates a temp git repo (`tmp_path` fixture), copies `.githooks/pre-commit` in, configures `core.hooksPath`, stages a fixture file with the target pattern, runs `git commit -m test` via `subprocess.run`, asserts exit code + stderr.

Test scenarios (acceptance criteria #4):

| ID | Fixture | Expected hook outcome |
|---|---|---|
| POSITIVE-1 | `.py` containing `httpx.put(f"https://api.render.com/v1/services/{sid}/env-vars", json=[{"key":"K","value":"V"}])` | exit 1, stderr mentions "Part 4" |
| POSITIVE-2 | `.sh` containing `curl -X PUT https://api.render.com/v1/services/srv-xxx/env-vars -d '[{"key":"K","value":"V"}]'` | exit 1, stderr mentions "Part 4" |
| NEGATIVE-1 | `.py` containing `safe_env_put(sid, "KEY", "value")` | exit 0 |
| NEGATIVE-2 | `.py` containing `httpx.put(f".../services/{sid}/env-vars/MY_KEY", json={"value":"v"})` (single-key path) | exit 0 |
| NEGATIVE-3 | `tools/render_env_guard.py` (allowlisted) containing the bare `/env-vars` URL in a docstring | exit 0 |
| NEGATIVE-4 | `briefs/BRIEF_X.md` (allowlisted) containing the pattern in prose | exit 0 |

Each test isolates via `tmp_path` so no global git state is touched. Tests must not require network — they only exercise the hook locally.

**C. Update `.claude/rules/python-backend.md`** — append to the existing Render env-vars line:

```
- Render env vars: use MCP merge mode, NEVER raw PUT. Python path: `from tools.render_env_guard import safe_env_put` (forces single-key `PUT /env-vars/{KEY}` merge-mode; rejects array-form PUT). Pre-commit hook Part 4 enforces this at git-time; bypass with --no-verify only after AH1 review. Anchor: 2026-05-17 catastrophic wipe.
```

### Key constraints

- **Do NOT touch Parts 1, 2, 3.** Only insert Part 4 between Part 3's `fi` and Part 1's header. Validate by running an existing-Parts smoke after the edit (see Verification).
- **Do NOT change `core.hooksPath`** — already `.githooks`.
- **Do NOT add new dependencies.** Pure bash + standard POSIX tools (grep, awk, sed) — same posture as Parts 1-3. Test file uses only stdlib `subprocess` + pytest.
- **Allowlist is exhaustive.** Files NOT in the allowlist are scanned; allowlisted files skip scanning entirely. The allowlist regex must NOT use partial matches that accidentally pass non-allowlisted files (use `^...$` anchors).
- **No false positives on Python comments / docstrings** — pattern matches any `+` line. If a non-allowlisted file has the URL in a comment, the hook blocks it (correct: someone should justify the reference via --no-verify OR move it to an allowlisted file). Document this in the error message.

### Verification

1. **Literal pytest run:**
   ```
   pytest tests/test_pre_commit_env_guard.py -v
   ```
   Paste full output in ship report. All 6 scenarios must pass.

2. **Existing Parts 1-3 still functional — manual smoke (B3 picks one):**
   - Stage a fake `.claude/agents/foo.md` → confirm Part 2 still blocks. Revert.
   - OR stage a `.py` containing `claude-opus-4-20250514` → confirm Part 3 still blocks. Revert.

3. **POSITIVE smoke on Part 4 itself:**
   - Create a throwaway `scratch.py` with `httpx.put("https://api.render.com/v1/services/srv-test/env-vars", json=[])`.
   - `git add scratch.py && git commit -m test` → MUST block with Part 4 message.
   - `rm scratch.py && git reset HEAD scratch.py`.

4. **`git config core.hooksPath`** still returns `.githooks` (no regression).

---

## Files Modified

- `.githooks/pre-commit` — Part 4 inserted between Part 3's `fi` and Part 1's header.
- `tests/test_pre_commit_env_guard.py` — NEW. pytest subprocess-driven tests, 6 scenarios.
- `.claude/rules/python-backend.md` — single-line append to the Render env-vars rule.

## Do NOT Touch

- `tools/render_env_guard.py` — runtime wrapper, separate layer. Stays unchanged.
- `tests/test_render_env_guard.py` — runtime wrapper's tests. Stays unchanged.
- `scripts/check_applied_migrations.sh` — Part 1's external dependency.
- Any production code (`outputs/dashboard.py`, `orchestrator/`, `triggers/`, etc.).
- 1P manifest "Baker — Render env-var map (manifest)" — separate layer, recovery contract.

## Quality Checkpoints

1. Pytest output literally pasted in ship report — no "passes by inspection".
2. Hook smoke (throwaway POSITIVE-1 fixture) blocks the commit; cleanup reverts to clean tree.
3. One existing-Part smoke passes (Part 2 OR Part 3) → no regression.
4. Diff to `.githooks/pre-commit` is purely additive (insert one block; no edits to Parts 1/2/3).
5. `.claude/rules/python-backend.md` line stays under ~250 chars (file is auto-loaded into Python-file sessions; bloat costs every session).

## Anti-pattern checks (lessons.md applied proactively)

| Anti-pattern | Applied mitigation |
|---|---|
| Function name guessing | Brief doesn't reference any external function signatures beyond the `safe_env_put(sid, KEY, value)` form that's already shipped + tested |
| Column name guessing | No DB touched |
| Already-implemented brief | Verified 2026-05-20: `.githooks/pre-commit` exists with Parts 1-3 only. No Part 4. No existing test file `tests/test_pre_commit_env_guard.py`. Brief is genuinely new |
| Untracked briefs | This brief will be `git add`'ed before commit |
| Secrets in brief | No passwords/tokens — only env-var KEY names |
| Cost impact | Zero API calls; pure local bash + pytest. Build cost: B3 dev time only |
| Render restart survival | N/A — git hook runs on dev machine, unaffected by Render |
| Brief code snippet wrong signature | The bash snippet is self-contained (no function calls). The test fixture descriptions are illustrative; B3 picks the exact `subprocess` invocation pattern |
| Blast radius | Low: false-positive blocks ONE commit, fix via --no-verify or allowlist edit. No data loss, no production impact. Can be reverted by deleting the Part 4 block |

## Branch / PR

- Branch: `b3/render-env-wipe-precommit-guard-1`
- PR title: `feat(githooks): pre-commit Part 4 — block raw /env-vars PUT (2026-05-17 wipe-pattern guard)`
- Reply target on PR open: bus-post `lead` topic `ship/render-env-wipe-precommit-guard-1`.

## Reporting

`dispatched_by: lead` — bus-post `lead` on PR open per brief-reply-to-sender rule (2026-05-17 ratification).

## Anchors

- 2026-05-17 catastrophic wipe — `tasks/lessons.md` §"Never use Render's array-form `PUT /v1/services/{id}/env-vars`".
- 2026-05-17 forensic completeness lesson — `tasks/lessons.md` §"Env-var wipe demands a forensic completeness audit".
- 2026-05-20 restoration sweep + 1P manifest creation — handover `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/session_handover_2026-05-21_dawn_aihead_a_env_restoration_plus_director_card_v1_1_dispatched.md`.
- Original runtime guard — `BRIEF_RENDER_ENV_WRITE_GUARD_1.md` + `tools/render_env_guard.py` + `tests/test_render_env_guard.py` (B3 ship 2026-05-17).
- Director ratification — 2026-05-20 chat "go" after reviewing the partial-coverage gap.
