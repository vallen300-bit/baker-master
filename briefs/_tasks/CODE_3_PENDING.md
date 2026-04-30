# CODE_3 — DISPATCH (BAKER_VAULT_WRITE_1)

**Status:** PENDING — 2026-05-01 by AI Head A (Director-cleared after pre-dispatch B3 coordination handshake + GITHUB_TOKEN scope verification)
**Brief:** `briefs/BRIEF_BAKER_VAULT_WRITE_1.md` (763 lines, **TIER A** trigger class, ~3-4h, v2 post-review revision)
**Builder:** B3 (confirmed green, clean working tree, baker-master remote wired correctly)
**Branch:** `b3/baker-vault-write-1` (cut off latest main — includes PR #95 brief + PR #136 + #137 BRISEN_LAB_1)
**Tier:** **Tier A** — autonomous merge HELD until BOTH gates clear:
  1. **AI Head B cross-lane review** pre-merge per `_ops/processes/b-code-dispatch-coordination.md` §HIGH-class
  2. **`/security-review` skill invocation** pre-merge per Lesson #52 (Tier-A merges with new external API surface MUST run security review)
**autopoll_eligible:** false — paste-block dispatch; cold-start required

## GITHUB_TOKEN scope verification (resolved before dispatch)

Verified 2026-05-01 by AI Head A:
- Source: 1Password "Baker API Keys" → "GitHub API" entry (Director-canonical)
- Type: classic PAT (40 chars, `ghp_`-style)
- Scopes (per `X-OAuth-Scopes` header): `repo, workflow`
- Permissions on `vallen300-bit/baker-vault`: `admin: True, maintain: True, push: True, triage: True, pull: True` — full read+write
- Verdict: **GREEN** — subsumes the brief's `contents:write` requirement.

Brief assumes Render env `GITHUB_TOKEN` = the 1Password "GitHub API" token. Director confirmed this is the canonical source. If a future build run hits an auth error, re-run scope verification before troubleshooting code paths.

## Task summary

Add new MCP tool `baker_vault_write` that commits to the vault GitHub repo via REST Contents API. Bypasses the local read-only mirror; mirror picks up new commits on next sync (~5 min). Strict guardrails: 6 path-class whitelist + 5 hard-blocks + frontmatter requirement on `curated/` and `proposed-gold.md` + audit-before-attempt + audit-after-result.

Files touched (per brief §Files to modify):

1. `baker_mcp/baker_mcp_server.py` — register Tool entry (insert after `baker_vault_read` at line 511); add `_dispatch()` case (after `baker_vault_read` handler at line 1379, before `baker_scan` at line 1381)
2. **NEW** `baker_mcp/vault_write.py` — write logic module: path validation, frontmatter validation, GitHub Contents API client with sync httpx, 409-retry-once, token redaction
3. **NEW** `tests/test_baker_vault_write.py` — 6 happy paths + 4 rejection paths per brief §Verification
4. `outputs/dashboard.py` — verify MCP route at line 632 exposes new tool automatically (iterates TOOLS list — verify with `grep -n "TOOLS" outputs/dashboard.py`)

## Pre-flight checks (already confirmed in handshake)

- B3 confirmed: detached HEAD at `91cc21b`, clean working tree, remote = baker-master (NOT baker-vault). Will `git checkout main && git pull` before cutting `b3/baker-vault-write-1`.
- Brief verified on origin/main since PR #95 merge 2026-04-30T14:47:53Z (B3 saw the gap because detached HEAD predated #95 merge).
- GITHUB_TOKEN scope verified GREEN above.

## Dispatch steps

```bash
cd ~/bm-b3
git checkout main && git pull --ff-only origin main
gh pr list --state open --limit 20    # Lesson #54 precheck
git checkout -b b3/baker-vault-write-1

# Read brief in full (763 lines — full v2 spec including 11 review-finding fixes)
cat briefs/BRIEF_BAKER_VAULT_WRITE_1.md

# Implement per brief §Implementation:
#   Fix/Feature 1: Path whitelist + validation (vault_write.py)
#   Fix/Feature 2: Frontmatter validation
#   Fix/Feature 3: GitHub Contents API client + 409 retry-once + token redaction
#   Fix/Feature 4: MCP Tool registration + dispatch + audit helpers

# Quality checkpoints:
pytest tests/test_baker_vault_write.py -v
python3 -c "import py_compile; py_compile.compile('baker_mcp/vault_write.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"
bash scripts/check_singletons.sh

# Push + open PR
git push -u origin b3/baker-vault-write-1
gh pr create --title "feat(vault): MCP tool baker_vault_write — GitHub Contents API direct commit (BAKER_VAULT_WRITE_1)" \
  --body "...per brief §Solution + §Files to modify + §Verification..."
```

## Acceptance criteria

Per brief §Verification (6 happy + 4 reject paths):

**Happy paths:**
- H1: write `wiki/matters/oskolkov/_session-state.md` overwrite mode → succeeds (klass=session_state, overwrite_ok=True)
- H2: write `wiki/matters/movie/curated/2026-05-01-test-topic.md` append mode with valid frontmatter → succeeds (klass=curated, frontmatter validated)
- H3: write `wiki/_inbox/handoff-2026-05-01-ao-to-movie.md` append mode → succeeds (klass=handoff)
- H4: write `wiki/matters/hagenauer-rg7/proposed-gold.md` append mode with valid frontmatter → succeeds (klass=proposed_gold)
- H5: write `wiki/matters/oskolkov/decisions/2026-05-01-test.md` append mode → succeeds (klass=decision)
- H6: write `wiki/matters/oskolkov/red-flags.md` append mode → succeeds (klass=red_flags)

**Rejection paths:**
- R1: write `wiki/matters/oskolkov/gold.md` → rejected (hard-block, defense-in-depth)
- R2: write `wiki/matters/oskolkov/curated/2026-05-01-test.md` MISSING frontmatter source/confidence/provenance → rejected
- R3: write `_ops/processes/foo.md` → rejected (hard-block)
- R4: write `wiki/matters/oskolkov/curated/2026-05-01-test.md` overwrite mode → rejected (append-only class)

Plus all 9 brief §Quality Checkpoints (pytest, py_compile, singleton, render deploy, live H1+H2 path-class probes, R1+R2+R3 rejections, AI Head B review PASS, /security-review PASS).

## Architect-review checkpoints (TIER A — both gates MANDATORY pre-merge)

When PR opens, AI Head A runs:

1. **`code-architecture-reviewer` subagent** — particular focus on:
   - Path whitelist regex correctness (6 patterns) — alphanumeric+hyphen slug constraint, date-format anchors, no trailing slop
   - Hard-block patterns (5) — substring vs full-anchor; `gold.md` must catch alternate placements
   - Frontmatter validation: `re.escape(key)` defense, non-empty value enforcement (the v1→v2 fix), missing closing `---` handling
   - Token redaction: `_redact()` covers BOTH URL-embedded + `Bearer` formats; applied at every error→audit + error→caller path
   - Audit pattern: `_emit_vault_write_audit(audit_id, success=None)` BEFORE attempt; `_update_vault_write_audit(success=True/False)` AFTER
   - 409-retry-once: refresh sha via `_gh_get`, single retry, raise on second 409
   - Sync httpx pattern preserved (matches existing MCP dispatch convention; no async leak)
   - Append vs overwrite enforcement (`overwrite_ok` returned from `validate_path` + mode validation)
   - Newline-separator append logic (existing-content endswith \n branch)

2. **`/security-review` skill** — MANDATORY per Lesson #52. Boundary: new external write surface. Specific surfaces:
   - Path-traversal vectors: `..`, absolute paths, `\\`, double-slashes, URL-encoded variants, percent-encoded, mixed-case
   - Symlink-escape (filesystem-side N/A since GitHub API; but content payload could contain symlink instructions — confirm GitHub API doesn't follow)
   - Secret leakage in error responses: GitHub error body could echo Authorization header — confirm `_redact()` strips before audit + caller return
   - SQL injection on audit table writes (parameterized via `_write()` helper at `baker_mcp_server.py:115` — verify)
   - Audit completeness: pre-attempt row exists even on hard crashes (audit before any GitHub I/O)
   - Hard-block bypass: alternate path placements that match an allowed pattern but should be hard-blocked (e.g. `wiki/_priorities.yml` deep-nested) — defense-in-depth via regex anchor placement

Both gates clear → AI Head A merges autonomously per Tier A charter.

## Verdict + handoff

Surface paste-block to AI Head A when PR opens with:
- PR number, file diffs summary
- Test counts (6 happy + 4 reject all pass)
- pytest output for tests/test_baker_vault_write.py
- Confirm `_redact()` applied at all 3 error paths in dispatch case
- Confirm audit-before + audit-after pattern wired
- Render deploy status (auto on push to main after merge — NOT before, since merge held until both gates clear)

Once both gates clear and PR merges, run brief §Live verification curl recipes against `https://baker-master.onrender.com/mcp?key=bakerbhavanga` — H1/H2 happy + R1 reject. Send curl outputs back to AI Head A.

## Coordination note

- Brief 2 (`BAKER_VAULT_READ_WIKI_SCOPE_1`, MEDIUM) dispatched alongside to B4 in PR #138 mailbox. Independent — neither blocks the other per brief §Prerequisites. Both must ship before Desk skills are end-to-end useful.
- AI Head B coordination (cross-lane review) — App AI Head A on App-side is the canonical AI Head B today; surface PR # there once build PR opens.

## Previous task (closed)

PR #116 review of CORTEX_AUTO_TRIGGER_DISPATCH_FIX_1 merged 2026-04-30 (Step 2 — second-pair-of-eyes review for B1 builder-conflict caveat). Vault companion baker-vault PR #30 (movie_am underscore alias) also merged. B3 has been on `91cc21b` (detached HEAD) since.
