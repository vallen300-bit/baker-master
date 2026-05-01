---
brief: BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1
trigger_class: LOW
tier: B
target_file: baker_mcp/vault_write.py
authored_by: AI Head A
created: 2026-05-01
companion_pr: 141 (BAKER_VAULT_WRITE_1, merged 2026-05-01)
---

# BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1 — architect nits from PR #141

## Why

`/architect-review` on PR #141 returned APPROVE WITH NITS — 2 MEDIUM follow-ups
that don't produce exploit primitives but harden contract integrity:

- **F1 (trailing-newline path bypass):** `validate_path()` rejects `..`, `\\`,
  leading `/`, but does NOT reject `\n`, `\r`, `\x00`. A path like
  `wiki/matters/oskolkov/_session-state.md\nX-Injected: yes` would pass
  validation; `httpx`'s h11 layer raises `LocalProtocolError` at transport
  time so it fails safe in practice — but the failure mode is opaque
  ("LocalProtocolError" instead of "VaultWriteError: path contains control
  chars"). Caller sees a transport stack trace, audit row never gets the
  reject classification, and contract says we reject malformed paths early.
  Fix: reject control characters in `validate_path()` before any other check.

- **F2 (root-path defense-in-depth gap):** `_BLOCKED_PATTERNS` has
  `^wiki/.*gold\.md$` and `^wiki/.*_priorities\.yml$`. These do NOT match
  root-level `gold.md` or `_priorities.yml` (no `wiki/` prefix). In practice
  the allow-pattern fall-through still rejects them ("path does not match
  any allowed pattern"), but the brief's stated invariant is "hard-block
  these names anywhere in the tree." Fix: change patterns to optional-prefix
  form `^(wiki/)?.*gold\.md$` and `^(wiki/)?.*_priorities\.yml$` so the
  blocker actually fires on root-level placements (still not allow-listed,
  just rejected by the blocker first — defense-in-depth, what the comment
  on line 51-53 already promises).

Architect explicitly said "merge now, file a follow-up commit" — matches the
PR #125→#127 + PR #129→#132 pattern. Tier B (autonomous merge on green).

## Scope (do exactly this)

**Files touched: 2.**

### File 1: `baker_mcp/vault_write.py`

**Change 1 (F1):** at the top of `validate_path()` after the empty-string
check (currently lines 113-114), insert:

```python
    if any(c in path for c in "\n\r\x00"):
        raise VaultWriteError(f"path contains control characters: {path!r}")
```

Place it BEFORE the existing traversal rejection at line 115 so control-char
paths get the most specific error message.

**Change 2 (F2):** in `_BLOCKED_PATTERNS` (lines 54-61), update two entries:

```python
    r"^wiki/.*gold\.md$",            →  r"^(wiki/)?.*gold\.md$",
    r"^wiki/.*_priorities\.yml$",    →  r"^(wiki/)?.*_priorities\.yml$",
```

Update the inline comment on each line if needed to reflect "anywhere in the
tree, including root."

**Critical: do NOT touch the `proposed-gold.md` whitelist** at line 67
(`_PROPOSED_GOLD_RE`). It runs FIRST in `validate_path()` (line 119) so the
broadened blocker still won't catch legitimate `wiki/matters/<slug>/proposed-gold.md`.

### File 2: `tests/test_baker_vault_write.py`

Add 4 tests (or extend existing R-class set):

1. **F1.a:** `validate_path("wiki/matters/x/_session-state.md\nX:Y", "overwrite")`
   raises `VaultWriteError` matching `/control characters/`.
2. **F1.b:** `validate_path("wiki/matters/x/_session-state.md\r\n", "overwrite")`
   raises `VaultWriteError`.
3. **F2.a:** `validate_path("gold.md", "append")` raises `VaultWriteError`
   matching `/hard-blocked/` (NOT `/does not match any allowed pattern/`).
4. **F2.b:** `validate_path("_priorities.yml", "append")` raises
   `VaultWriteError` matching `/hard-blocked/`.

Existing 41 tests must stay green byte-for-byte (regression guard).

## Quality checkpoints

```bash
cd ~/bm-b3
git checkout main && git pull --ff-only origin main
git checkout -b b3/vault-write-followup-nits-1

# implement per Scope above
pytest tests/test_baker_vault_write.py -v   # expect 45/45 (41 prior + 4 new)
python3 -c "import py_compile; py_compile.compile('baker_mcp/vault_write.py', doraise=True)"
bash scripts/check_singletons.sh

git add baker_mcp/vault_write.py tests/test_baker_vault_write.py
git commit -m "fix(vault): harden validate_path control chars + broaden gold/_priorities blockers (architect nits from #141)"
git push -u origin b3/vault-write-followup-nits-1
gh pr create --title "fix(vault): vault_write.py architect-nit followup (control chars + root-path blockers) (BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1)" \
  --body "$(cat <<'EOF'
Follow-up to PR #141 (BAKER_VAULT_WRITE_1, merged 2026-05-01).

Architect-review on #141 returned APPROVE WITH NITS — 2 MEDIUM correctness
follow-ups, both filtered as non-exploitable by /security-review. Architect
explicitly recommended a follow-up commit.

## F1 — trailing newline / control char in path

Added explicit rejection in validate_path() for \\n, \\r, \\x00 before
traversal checks. Prior behavior: httpx h11 LocalProtocolError at transport
(fails safe but emits opaque error + skips audit reject classification).

## F2 — root-path defense-in-depth gap

Tightened gold.md + _priorities.yml hard-block patterns from
^wiki/.* to ^(wiki/)?.* — now catches root-level placements explicitly via
the blocker (prior fall-through still rejected via allow-pattern miss, just
with the wrong error message).

## Tests

4 new (F1.a/b + F2.a/b); 41 prior remain green byte-for-byte.

Tier B — autonomous merge on green per ai-head-autonomy-charter.md §3 and
the LOW classification on the brief.

Brief: briefs/BRIEF_VAULT_WRITE_FOLLOWUP_NITS_1.md

Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-authored-by: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Done when

- 4 new tests pass (F1.a/b + F2.a/b).
- 41 prior tests pass byte-for-byte.
- PR opened with brief link in body.
- AI Head A merges on green; reports back via `briefs/_reports/B3_vault_write_followup_nits_1_<date>.md`.

## Out of scope (do NOT do)

- Don't touch `_PROPOSED_GOLD_RE` (line 67).
- Don't touch `_ALLOWED_PATTERNS` (lines 28-48).
- Don't refactor `_BLOCKED_PATTERNS` order or structure beyond the 2-line edit.
- Don't change `validate_path()` argument signature, return type, or class
  values.
- No changes to `baker_mcp/baker_mcp_server.py` — no API surface change.
- No changes to `outputs/dashboard.py`.
