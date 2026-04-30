# CODE_4 — DISPATCH (BAKER_VAULT_READ_WIKI_SCOPE_1)

**Status:** PENDING — 2026-05-01 by AI Head A (Director-cleared after pre-dispatch B4 coordination handshake)
**Brief:** `briefs/BRIEF_BAKER_VAULT_READ_WIKI_SCOPE_1.md` (286 lines, MEDIUM trigger class, ~1-2h)
**Builder:** B4 (confirmed green, clean working tree, no Brief-3-leftovers)
**Branch:** `b4/baker-vault-read-wiki-scope-1` (cut off latest main — includes PR #136 + #137 BRISEN_LAB_1 brief + B5 dispatch)
**Tier:** Tier B (autonomous merge on green per AI Head A autonomy charter §3) — brief itself flags MEDIUM with cross-lane review pre-merge + `/security-review` recommended (boundary-broadening change)
**autopoll_eligible:** false — paste-block dispatch; cold-start required

## Task summary

Extend Cowork-side vault read scope from `_ops/` only to `_ops/` + `wiki/`. Three files touched:

1. `vault_mirror.py` — replace `OPS_PREFIX` constant with `ALLOWED_PREFIXES` frozenset (keep back-compat `OPS_PREFIX` alias); update `_normalize_and_resolve()` (lines 266-297) to test against the set; rename `list_ops_files` → `list_vault_files` (with alias); same for `read_ops_file` → `read_vault_file`.
2. `baker_mcp/baker_mcp_server.py` — broaden Tool descriptions for `baker_vault_list` (~line 485-496) and `baker_vault_read` (~line 498-510): replace "scoped to `_ops/`" wording with allowed-prefix list. No logic change here — dispatch handlers already call into `vault_mirror`.
3. `tests/test_mcp_vault_tools.py` — extend with `wiki/` happy-path + traversal-attempt tests. Existing `_ops/` tests must stay green byte-for-byte (regression guard).

Read the brief in full before starting — full spec including before/after code blocks for `_normalize_and_resolve()`, complete test matrix (5 happy / 5 reject), live-verification curl recipes, and the explicit do-not-touch list.

## Context updates (vs. brief text — written before Wave 2/3 close)

1. Brief §Companion section says `BRIEF_BAKER_VAULT_WRITE_1` is "in flight on B2." **Stale** — neither brief is in flight as of 2026-05-01 dispatch. Brief 1 awaits separate dispatch from AI Head A pending Director consult on Tier A trigger class (see §Coordination note below).
2. Brief §Working branch suggests "B1 once free." Reassigned to B4 — confirmed green via pre-dispatch handshake; freshest Cortex/vault context from Brief 3+4 ship 2026-04-30.

## Pre-flight checks (already confirmed in handshake)

- B4 confirmed: branch `b4/cortex-phase6-reflector-orderby-fix` (clean, no uncommitted), local mailbox stale, will `git checkout main && git pull` before cutting `b4/baker-vault-read-wiki-scope-1`.
- No open PR conflicts on master (PR #135 brief-only, PR #137 just merged).
- `gh pr list --state open --limit 20` clean as of dispatch.

## Dispatch steps

```bash
cd ~/bm-b4
git checkout main && git pull --ff-only origin main
git checkout -b b4/baker-vault-read-wiki-scope-1

# Read brief in full
cat briefs/BRIEF_BAKER_VAULT_READ_WIKI_SCOPE_1.md

# Implement per brief §Implementation (3 files)
# Run pytest after each file change to catch regressions early

# Quality checkpoints (brief §Quality Checkpoints):
pytest tests/test_mcp_vault_tools.py -v
python3 -c "import py_compile; py_compile.compile('vault_mirror.py', doraise=True)"
python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"
bash scripts/check_singletons.sh

# Push + open PR
git push -u origin b4/baker-vault-read-wiki-scope-1
gh pr create --title "feat(vault): extend read scope from _ops/ to {_ops/, wiki/} (BAKER_VAULT_READ_WIKI_SCOPE_1)" \
  --body "...per brief..."
```

## Acceptance criteria

Per brief §Quality Checkpoints (1-9):
- All existing `_ops/` tests in `tests/test_mcp_vault_tools.py` pass (regression)
- New `wiki/` happy-path + traversal-attempt tests pass
- `vault_mirror.py` + `baker_mcp/baker_mcp_server.py` compile clean
- Render deploy succeeds (auto on push to main after merge)
- Live H1 (regression `_ops/` read) + H2 (`wiki/hot.md` read) + H3 (`wiki/matters/oskolkov/cortex-config.md` read) + R1 (`wiki/../etc/passwd` traversal rejected) all verify
- AI Head A invokes `code-architecture-reviewer` + `/security-review` skill on the build PR (Lesson #52 + brief §Quality Checkpoints 8-9)

## Architect-review checkpoints (per Lessons #52 + #54)

When PR opens, AI Head A runs:
1. `code-architecture-reviewer` subagent — particular focus on (a) realpath/symlink invariants preserved across both prefixes, (b) extension-allowlist + size-cap unchanged, (c) regression coverage for `OPS_PREFIX` consumers via the back-compat alias, (d) MCP tool description correctness in `baker_mcp_server.py`.
2. `/security-review` skill — boundary-broadening change; specifically check path-escape vectors, symlink-traversal edge cases, prefix-collision handling (e.g. is `_ops/foo` mistakenly accepted under `wiki/` matching?).

## Verdict + handoff

Surface paste-block to AI Head A when PR opens with: PR number, file diffs summary, test counts (existing pass + new pass), Render deploy status, brief §Live verification curl results.

## Coordination note

Brief 1 (`BAKER_VAULT_WRITE_1`, TIER A) NOT dispatched in this round. Reason: TIER A trigger class warrants Director consult on dispatch timing per AI Head A autonomy charter; AI Head A is surfacing a separate paste-block on Brief 1.

## Previous task (closed)

Brief 3 (`CORTEX_PHASE6_REFLECTOR_1`) shipped via PR #129 + #132, both merged 2026-04-30. B4 idle since.
