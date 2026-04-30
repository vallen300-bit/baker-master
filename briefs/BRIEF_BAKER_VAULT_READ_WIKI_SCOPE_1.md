# BRIEF: BAKER_VAULT_READ_WIKI_SCOPE_1 — Extend vault read scope from `_ops/` to also include `wiki/`

**Estimated time:** ~1-2h (incl. tests)
**Complexity:** Low
**Trigger class:** **MEDIUM** — broadens an existing security boundary; cross-lane review pre-merge.
**Prerequisites:** none — independent of `BAKER_VAULT_WRITE_1`. Either can ship first.

---

## Context

Cowork-side scoped **Desk** agents (Director-ratified 2026-04-30, naming approved 2026-04-30) need to read per-matter dossiers from `wiki/matters/<slug>/` (e.g. `cortex-config.md`, `gold.md`, `curated/`, `red-flags.md`). Today, `vault_mirror.py:_normalize_and_resolve()` (line 283-284) hard-rejects any path not starting with `_ops/`:

```python
if not normalized.startswith(OPS_PREFIX):
    raise VaultPathError(f"path must start with '{OPS_PREFIX}'")
```

This was correct for the original SOT_OBSIDIAN_1_PHASE_D scope (Cowork reads its own canonical skill + memory files). It's now too narrow for the Desk pattern.

**Foundational research:** `wiki/research/2026-04-30-context-engineering-scoped-agents.md` §5 Filesystem-as-memory. Anthropic Just-in-Time Retrieval pattern requires reading vault paths Cortex skills wrote.

**Companion brief:** `BRIEF_BAKER_VAULT_WRITE_1` (in flight on B2) adds the write side. Both required for Desk skills to be end-to-end useful. Neither blocks the other.

---

## Problem

| Use case | Today | Blocked because |
|---|---|---|
| AO Desk reads `wiki/matters/oskolkov/cortex-config.md` for Tier 1 dossier | `baker_vault_read` returns "path must start with `_ops/`" | Read scope limited to `_ops/` |
| Hagenauer Desk reads `wiki/matters/hagenauer-rg7/gold.md` | rejected | Same |
| MOVIE Desk lists `wiki/matters/movie/curated/` files | rejected | Same |
| Brisen Desk (CEO view) reads `wiki/hot.md` for ratified priorities | rejected | Same |

Without this brief: every Desk skill is forced to either (a) duplicate vault content into `_ops/` (architectural pollution), or (b) be unable to read the matter dossier it just wrote via `baker_vault_write`.

---

## Solution

Extend `vault_mirror.py` path-safety from a single `_ops/` prefix to an allowed-prefix set: `{_ops/, wiki/}`. Same realpath/symlink/extension/size guarantees apply to both. No new endpoint surface — same `baker_vault_list` and `baker_vault_read` MCP tools, broader prefix.

**Hard-blocks remain:** `slugs.yml` (separate-repo PR only per Director rule), anything outside the allowed prefixes.

**Read-only invariant remains:** mirror still pulls only; never pushes. Write path is a separate concern handled by `BAKER_VAULT_WRITE_1`.

---

## Files to modify

1. **`vault_mirror.py`** — replace `OPS_PREFIX` with `ALLOWED_PREFIXES`, update `_normalize_and_resolve()` to test against the set, broaden the docstring + module header comment.
2. **`baker_mcp/baker_mcp_server.py`** — update Tool descriptions for `baker_vault_list` (line ~485-496) and `baker_vault_read` (line ~498-510): replace "scoped to `_ops/`" wording with "scoped to `_ops/` or `wiki/`". Description-only change; no logic change here.
3. **`tests/test_mcp_vault_tools.py`** — extend with `wiki/` happy-path + traversal-attempt tests. Existing `_ops/` tests must still pass (regression guard).

## Files NOT to touch

- Read-mirror sync logic (`ensure_mirror`, `sync_tick`, `_run_git`) — unchanged.
- Extension whitelist (`.md`, `.yml`, `.yaml`, `.txt`) — unchanged. Same caps for `wiki/`.
- 128 KB file-size cap — unchanged.
- `BAKER_VAULT_WRITE_1` files (`baker_mcp/vault_write.py` if it exists by ship time) — separate concern.

---

## Implementation

### Fix/Feature 1: `vault_mirror.py` — broaden allowed prefixes

**Before** (lines 44-46):
```python
MAX_FILE_BYTES = 128 * 1024
ALLOWED_EXTENSIONS = frozenset([".md", ".yml", ".yaml", ".txt"])
OPS_PREFIX = "_ops/"
```

**After:**
```python
MAX_FILE_BYTES = 128 * 1024
ALLOWED_EXTENSIONS = frozenset([".md", ".yml", ".yaml", ".txt"])
# Allowed read-scope prefixes. Originally `_ops/` only; extended 2026-04-30
# (BAKER_VAULT_READ_WIKI_SCOPE_1) to include `wiki/` for Desk-skill dossier reads.
# Any new prefix MUST keep realpath + symlink + extension + size invariants.
ALLOWED_PREFIXES = frozenset(["_ops/", "wiki/"])

# Back-compat alias — some imports may still reference OPS_PREFIX. Keep as a
# pointer to the canonical _ops prefix. Remove in a follow-up brief once all
# imports migrate.
OPS_PREFIX = "_ops/"
```

**Update `_normalize_and_resolve()` (lines 266-297):**

```python
def _normalize_and_resolve(rel_path: str) -> Path:
    """Validate + resolve a caller-supplied relative path.

    Invariants on return:
      * result is absolute
      * result lives strictly inside one of the ALLOWED_PREFIXES subtrees
      * no symlink escapes (`realpath` folds those)

    Raises `VaultPathError` otherwise. Does NOT require the file to
    exist — callers handle that.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise VaultPathError("path must be a non-empty string")

    normalized = rel_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        raise VaultPathError("path must be relative, not absolute")

    matched_prefix = None
    for prefix in ALLOWED_PREFIXES:
        if normalized.startswith(prefix):
            matched_prefix = prefix
            break
    if matched_prefix is None:
        raise VaultPathError(
            f"path must start with one of {sorted(ALLOWED_PREFIXES)}; got: {rel_path!r}"
        )

    root = mirror_path()
    prefix_root = (root / matched_prefix.rstrip("/")).resolve()
    resolved = (root / normalized).resolve()

    if not (resolved == prefix_root or prefix_root in resolved.parents):
        raise VaultPathError(
            f"path escapes {matched_prefix} scope: {rel_path!r}"
        )

    return resolved
```

### Fix/Feature 2: `list_ops_files()` — accept any allowed prefix

The function name is `_ops`-flavoured but the logic should handle any allowed prefix. Rename to `list_vault_files()` (with backward-compat alias) and update default-arg:

```python
def list_vault_files(prefix: str = "_ops/") -> list[str]:
    """List `.md` / `.yml` / `.yaml` / `.txt` files under prefix.

    `prefix` must start with one of ALLOWED_PREFIXES. Returns sorted relative
    paths. Empty list if prefix doesn't exist.
    """
    # ... existing body, but using _normalize_and_resolve(prefix) for safety
    # and globbing the resolved subtree

# Back-compat alias — drop in follow-up cleanup brief
list_ops_files = list_vault_files
```

Same for `read_ops_file` → `read_vault_file` with `read_ops_file` alias.

### Fix/Feature 3: MCP Tool descriptions — broaden language

In `baker_mcp/baker_mcp_server.py`, update the `baker_vault_list` Tool entry (~line 485-496):

**Before** (description excerpt):
```
"List files in the baker-vault mirror under a given prefix (scoped to `_ops/` — skills, agents, processes, briefs, registries)..."
```

**After:**
```
"List files in the baker-vault mirror under a given prefix. Allowed prefixes: `_ops/` (skills, agents, processes, briefs, registries) and `wiki/` (matter dossiers, curated knowledge, ratified priorities). Returns sorted relative paths for `.md`, `.yml`, `.yaml`, `.txt` files only."
```

And the `prefix` parameter description:

**Before:**
```
"description": "Path prefix to list under. Must start with `_ops/`. Default `_ops/`.",
```

**After:**
```
"description": "Path prefix to list under. Must start with `_ops/` or `wiki/`. Default `_ops/`.",
```

Same surgery on `baker_vault_read` Tool entry.

The dispatch handlers at lines ~1357-1379 already call into `vault_mirror` — no logic change there. The new `_normalize_and_resolve()` accepts both prefixes uniformly.

---

## Key Constraints

- **DO NOT** add a third allowed prefix in this brief. If `raw/` ever needs reading, that's a separate brief with its own threat model (raw/ holds unprocessed signals — different security stance).
- **DO NOT** change extension whitelist. `.md`/`.yml`/`.yaml`/`.txt` only.
- **DO NOT** change size cap. 128 KB stays.
- **DO NOT** change read-only invariant — `vault_mirror.py` still only `git pull`s. Write happens via `BAKER_VAULT_WRITE_1`.
- **DO NOT** rename `OPS_PREFIX` without keeping the alias — other modules / tests may import it.
- **`/security-review` skill** — recommended pre-merge (broadens an existing security boundary; cheaper than full Tier-A but worth the 5 minutes).
- **Test the regression** — existing `_ops/` tests in `tests/test_mcp_vault_tools.py` must still pass byte-for-byte.

---

## Verification

### Test matrix

| # | Path | Expected |
|---|------|----------|
| H1 | `_ops/skills/it-manager/SKILL.md` | OK (regression — pre-existing happy path) |
| H2 | `wiki/hot.md` | OK (new) |
| H3 | `wiki/matters/oskolkov/cortex-config.md` | OK (new) |
| H4 | `wiki/_priorities.yml` | OK (new — read-only, write-blocked separately by vault_write) |
| H5 | List under `wiki/matters/oskolkov/` | OK; returns `.md`/`.yml` files |
| R1 | `raw/contracts/foo.pdf` | rejected — not in allowed prefixes |
| R2 | `wiki/../etc/passwd` | rejected — escapes prefix |
| R3 | `wiki/foo.exe` | rejected — extension not allowed |
| R4 | `/etc/passwd` | rejected — absolute path |
| R5 | (empty string) | rejected — non-empty required |

### Live verification

```bash
# Tool descriptions reflect new scope
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | grep -A1 '"name":"baker_vault_read"'

# H2: read wiki/hot.md (Director-ratified priorities)
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_vault_read","arguments":{"path":"wiki/hot.md"}}}'
# Expect: hot.md content with Director-curated priorities

# H3: read AO matter cortex-config
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_vault_read","arguments":{"path":"wiki/matters/oskolkov/cortex-config.md"}}}'

# R1: traversal attempt rejected
curl -s -X POST "https://baker-master.onrender.com/mcp?key=bakerbhavanga" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"baker_vault_read","arguments":{"path":"wiki/../etc/passwd"}}}'
# Expect: error "path escapes wiki/ scope"
```

---

## Quality Checkpoints

1. ✅ `pytest tests/test_mcp_vault_tools.py -v` — all existing `_ops/` tests pass + new `wiki/` tests pass
2. ✅ `python3 -c "import py_compile; py_compile.compile('vault_mirror.py', doraise=True)"` clean
3. ✅ `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"` clean
4. ✅ Render deploy succeeds
5. ✅ Live H1 (regression) — `_ops/` reads still work
6. ✅ Live H2 + H3 — `wiki/` reads now work
7. ✅ Live R1 (traversal) — rejected with clear error
8. ✅ AI Head B cross-lane review PASS
9. ✅ `/security-review` skill recommended PASS (boundary-broadening change)

---

## Out of scope (future briefs)

- Adding `raw/` read scope — separate threat model, separate brief.
- Migrating `list_ops_files` / `read_ops_file` callers to the renamed functions — purely cosmetic; the aliases keep things working.
- Extending tool description coverage (e.g. listing all `wiki/matters/<slug>/` paths in description) — feature work, not security.

---

## Working branch (will be assigned at dispatch)

```
b{N}/baker-vault-read-wiki-scope-1
```

(Likely B1 once free; B2 is on `BAKER_VAULT_WRITE_1`. AI Head A picks at dispatch time.)

## Co-Authored-By

```
Co-authored-by: Code Brisen #{N} <b{N}@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

---

## Director-visible after merge

- Cowork-side AI Head Biz / Desk skills can read `wiki/matters/<slug>/cortex-config.md`, `gold.md`, `curated/*`, `red-flags.md`, plus `wiki/hot.md` (ratified priorities).
- Combined with `BAKER_VAULT_WRITE_1`: full Manus filesystem-as-memory loop. Desk deliberation persists, future Desk sessions read what prior sessions wrote.
- No regression in `_ops/` reads — existing skill + memory loading continues to work.
