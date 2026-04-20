# BRIEF: SOT_OBSIDIAN_1_PHASE_D_VAULT_READ

**Parent brief:** `BRIEF_SOT_OBSIDIAN_UNIFICATION_1.md` (Phase D — transport for Cowork-side vault access)
**Status:** RATIFIED 2026-04-20 by Director ("go")
**Estimated effort:** 3-4h implementation + review cycle
**Assignee:** B1
**Reviewer:** B2

---

## Why

Phase A + B shipped the canonical `_ops/` subtree in baker-vault and symlinked Claude App's local skill registry to it. AI Dennis on Director's MacBook now reads her skill + memory files from the single source of truth.

**Cowork (cloud-sandboxed Claude App) has no local filesystem.** The symlink doesn't reach her. Her skill registry is cloud-delivered. To equip Cowork-side AI Dennis from the same vault, she needs to read vault files over the wire.

**Simplest transport:** the existing Baker MCP at `https://baker-master.onrender.com/mcp` — already registered with Cowork (she calls `mcp__baker__*` tools today for DB queries). Adding vault-read tools to that MCP means **zero new infrastructure, zero new auth, zero new client-side config.**

Rejected alternatives (per parent-brief §Phase D transport question):
- **Mac Mini side-car MCP.** Requires Mac Mini always-on, new MCP registration in Cowork, new auth channel. Adds failure mode without new capability.
- **Direct GitHub API reads from Cowork.** Would need GitHub token in Cowork's env; Cowork's cloud runtime doesn't have per-user secret scoping for this.
- **New standalone MCP.** Duplicates auth, hosting, and monitoring of the already-running Baker MCP.

---

## Fix / Feature

### 1. Render-side vault mirror

- New directory in baker-master repo layout: `/opt/render/project/src/baker-vault-mirror/` (NOT committed — mirror is populated at runtime).
- FastAPI lifespan hook: on startup, if `baker-vault-mirror/` does not exist or is stale (>10 min since last pull), `git clone` or `git pull` from `https://github.com/vallen300-bit/baker-vault.git`. Use existing `GITHUB_TOKEN` env var for auth (already present — reused from auto-deploy).
- APScheduler job `vault_sync_tick` every 5 minutes: `git -C baker-vault-mirror pull --ff-only origin main`. Silent on no-op. Logs on conflict (should never happen — read-only mirror).
- Env var `VAULT_SYNC_INTERVAL_SECONDS` default 300, floor 60.
- Env var `VAULT_MIRROR_PATH` default `/opt/render/project/src/baker-vault-mirror` for test override.

### 2. Two new MCP tools on existing Baker MCP

Add to `outputs/mcp_server.py` (or wherever current 25 tools are registered).

**Tool: `baker_vault_list`**

- Input: `prefix` (str, default `_ops/`) — path prefix to list under.
- Output: list of relative file paths matching prefix, scoped to `_ops/**/*.md` (plus registered INDEX.md + .yml for registries).
- Safety: `prefix` normalized + must start with `_ops/`. No path traversal.

**Tool: `baker_vault_read`**

- Input: `path` (str, required) — relative path like `_ops/skills/it-manager/SKILL.md`.
- Output: `{path, content_utf8, sha256, bytes, last_commit_sha}`. File content as utf-8 string.
- Safety:
  - Path must start with `_ops/`.
  - Resolved absolute path must be inside `baker-vault-mirror/_ops/` (prevent `../` escapes).
  - Only `.md` + specific allowlisted filenames (`INDEX.md`, `TEMPLATE.md`, `slugs.yml` if in `_ops/`) — no binary files.
  - File size cap: 128 KB. Larger files return metadata only + `truncated: true`.
- Read-only. No write/delete/move equivalents in this brief. Mirror is advisory; authoritative vault lives on GitHub + Director's Mac.

### 3. Tests

- `tests/test_mcp_vault_tools.py`:
  - Happy path: `baker_vault_read("_ops/skills/it-manager/SKILL.md")` returns 16,150-byte SKILL.md content with correct sha.
  - Path traversal: `baker_vault_read("_ops/../CHANDA.md")` → error (not allowed).
  - Outside scope: `baker_vault_read("wiki/someone.md")` → error (must start with `_ops/`).
  - Nonexistent: `baker_vault_read("_ops/skills/nonexistent/SKILL.md")` → 404-shaped error, not exception.
  - Binary: `baker_vault_read("_ops/skills/foo/image.png")` → extension-not-allowed error.
  - List: `baker_vault_list("_ops/agents/")` returns at least `ai-dennis/OPERATING.md`, `LONGTERM.md`, `ARCHIVE.md`, `INDEX.md` when vault is populated.
- Integration test (needs_live_pg not required; needs_vault_mirror fixture instead — create temp git repo + clone for test).

### 4. Cowork-side consumption doc

Append to `_ops/agents/ai-dennis/OPERATING.md` (in vault, as part of this PR) a new section titled **"Reading your canonical files (Cowork)"**:

```
Your canonical skill + memory files live in baker-vault. To read them from Cowork, call:

  mcp__baker__baker_vault_read({path: "_ops/skills/it-manager/SKILL.md"})
  mcp__baker__baker_vault_read({path: "_ops/agents/ai-dennis/OPERATING.md"})
  mcp__baker__baker_vault_read({path: "_ops/agents/ai-dennis/LONGTERM.md"})
  mcp__baker__baker_vault_read({path: "_ops/agents/ai-dennis/ARCHIVE.md"})

Mirror refreshes every 5 minutes. For files that changed in the last 5 min, call baker_vault_read again — you may see stale content briefly.
```

### 5. Health + visibility

- `/health` endpoint: add `vault_mirror_last_pull` (ISO timestamp) and `vault_mirror_commit_sha` (current HEAD). 
- No new Render env var beyond the two above.

---

## Key constraints

- **Mirror is read-only.** Never `git push` from Render. If Render's mirror drifts (unlikely — pull only), next scheduler tick corrects.
- **No secrets in vault.** Audit before merge: `grep -r -iE "(api[_-]?key|password|token|secret)" baker-vault/_ops/` should return zero (or only documentation of such concepts, not values). B2 should verify.
- **No schema changes.** DB untouched.
- **Path safety is load-bearing.** Any path-resolution regression lets Cowork read arbitrary files on Render's container. Tests must cover traversal.

---

## Out of scope

- Write tools (`baker_vault_write`). Writing to vault requires PR flow + CHANDA protection — separate brief if ever needed.
- Webhook-triggered sync (push from GitHub). Polling every 5 min is sufficient for Cowork's latency tolerance.
- Caching layer. Vault is small; disk reads are fast.
- Any changes to Claude App (local) flow — that's already symlink-equipped.

---

## Verification

Post-deploy, from a session with `mcp__baker__*` tools loaded:

```
mcp__baker__baker_vault_read({path: "_ops/skills/it-manager/SKILL.md"})
```

Expected: returns 16,150-byte SKILL.md content. Sha matches `git cat-file -p HEAD:_ops/skills/it-manager/SKILL.md | shasum -a 256`.

`/health` shows `vault_mirror_commit_sha` matching `git -C ~/baker-vault rev-parse HEAD`.

---

## Day 1 protocol (after merge)

1. AI Head calls both new tools from a Cowork session with AI Dennis skill loaded; confirms Cowork can now read her own canonical files.
2. AI Dennis (Cowork) operating-file updated (Step 4 above) so the protocol is self-documented.
3. If verification succeeds, SOT Phase D is done. Phase E (CHANDA Inv 9 refinement + pipeline frontmatter filter) is the last SOT phase — Tier B, Director auth required.
