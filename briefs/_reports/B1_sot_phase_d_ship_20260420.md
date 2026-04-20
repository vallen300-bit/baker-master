# B1 Ship Report — SOT_OBSIDIAN_1_PHASE_D_VAULT_READ

**Date:** 2026-04-20
**Author:** Code Brisen B1
**Reviewer:** B2
**Brief:** `briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md` @ `d6a50ef`

---

## PRs opened

1. **baker-master#28** — branch `sot-obsidian-1-phase-d-vault-read`, head `237d8c7`, MERGEABLE.
   Vault mirror module + two MCP tools (`baker_vault_list`, `baker_vault_read`) + startup hook + scheduler job + `/health` fields + 21 tests.

2. **baker-vault#6** — branch `sot-obsidian-1-phase-d-operating-append`, head `707555e`, MERGEABLE.
   Appends "Reading your canonical files (Cowork)" section to `_ops/agents/ai-dennis/OPERATING.md` so AI Dennis has a self-documented entry point for the new tools.

Both PRs must land for Phase D complete. Merge order doesn't matter.

## Scope shipped

### Render-side vault mirror (`vault_mirror.py`, new top-level module)

- `ensure_mirror()` — clone on startup if missing; `pull --ff-only origin main` if present.
- `sync_tick()` — APScheduler job body; pulls every `VAULT_SYNC_INTERVAL_SECONDS` (default 300, floor 60).
- Module-level `_git_lock` serializes startup + tick paths.
- Env overrides: `VAULT_MIRROR_PATH`, `VAULT_MIRROR_REMOTE`, `VAULT_SYNC_INTERVAL_SECONDS` (all test-friendly).
- `mirror_status()` returns `{vault_mirror_last_pull, vault_mirror_commit_sha}` for `/health`.
- Path-safe helpers `list_ops_files(prefix)` + `read_ops_file(path)` — `realpath`-based containment check, extension allowlist (`.md`/`.yml`/`.yaml`/`.txt`), 128 KB cap.

### MCP tools on `baker_mcp/baker_mcp_server.py`

- **`baker_vault_list(prefix)`** — default prefix `_ops/`. Returns sorted relative paths for allowed extensions.
- **`baker_vault_read(path)`** — returns `{path, content_utf8, sha256, bytes, last_commit_sha, truncated}`. Size > 128 KB → metadata only with empty content.
- Both wrap `VaultPathError` into user-facing "Error: ..." strings per the MCP server's existing error-handling pattern.

### FastAPI integration

- `_ensure_vault_mirror()` called between `_run_migrations()` and `_start_scheduler()`. Fatal on initial clone failure; non-fatal on pull failure (next tick retries).
- `/health` gains `vault_mirror_last_pull` (ISO timestamp) + `vault_mirror_commit_sha` (full sha).

### Scheduler job

- `vault_sync_tick` registered alongside `kbl_bridge_tick` + `kbl_pipeline_tick` in `triggers/embedded_scheduler.py`.
- 120 s misfire grace (mirror freshness is advisory; no need to chase every miss).

## Tests

**New:** `tests/test_mcp_vault_tools.py` — 21 cases, all green on py3.12 (`bm-b2-venv`).

Hermetic fixture: creates a local bare git repo, seeds `_ops/` skeleton, clones into a temp mirror path. No live GitHub calls. Key coverage:

| Case | Test |
|---|---|
| Happy read returns content + sha + commit_sha | `test_read_happy_path_returns_content_and_sha` |
| Path traversal rejected | `test_read_path_traversal_is_rejected` |
| Absolute path rejected | `test_read_absolute_path_is_rejected` |
| Out-of-scope prefix rejected | `test_read_out_of_scope_prefix_is_rejected` |
| Nonexistent → 404 dict (not exception) | `test_read_nonexistent_returns_not_found` |
| Binary extension rejected | `test_read_binary_extension_is_rejected` |
| Oversize returns metadata only | `test_read_oversize_returns_metadata_only` |
| Registry `.yml` allowed | `test_read_registry_yml_is_allowed` |
| List root + agents subdir | `test_list_ops_root_returns_all_allowed_files` + `test_list_ops_agents_subdir` |
| List out-of-scope + traversal rejected | `test_list_*_rejected` |
| Mirror status populated | `test_mirror_status_after_ensure` |
| sync_tick pulls new commit | `test_sync_tick_pulls_new_commit` |
| Interval clamp to floor / default | `test_sync_interval_*` |
| MCP dispatch registers + routes | `test_mcp_tools_registered` + `test_mcp_dispatch_*` |

**Amended regression test:** `test_migration_runner.py::test_startup_call_order` now also patches `_ensure_vault_mirror` so the call-order invariant stays hermetic on CI where `/opt` is writable.

**Regression run:** `65 passed, 2 skipped` across `test_mcp_vault_tools` + `test_bridge_alerts_to_signal` + `test_kbl_db` + `test_migration_runner`.

## Secret audit (brief §Key Constraints)

`grep -r -iE "(api[_-]?key|password|token|secret)" _ops/` in baker-vault returns 14 matches — **all concept-documentation** (password policy, "never put tokens in briefs", "API keys rotate every 90 days"). Zero actual secret values. Safe.

## Design calls worth B2 attention

1. **Single top-level `vault_mirror.py`** rather than a `baker_vault/` package. ~300 LOC of cohesive logic; splitting adds ceremony without abstraction payoff.
2. **Module-level `_git_lock`** serializes startup + tick — simpler than filesystem flock and correct for APScheduler's single-process BackgroundScheduler.
3. **Lazy imports inside dispatch/wrapper branches** — matches the `_kbl_bridge_tick_job` pattern; keeps MCP server module-load independent of git subprocess availability.

## Paper trail

Baker decision to be logged post-merge: SOT Phase D shipped as PR pair #28 / vault#6. Parent brief decision is at `11922`.

## After merge (Day 1 protocol per brief §Day 1 protocol)

AI Head owns:
1. `curl https://baker-master.onrender.com/health | jq '.vault_mirror_commit_sha'` — matches `git -C ~/baker-vault rev-parse HEAD`.
2. Cowork-invoked AI Dennis session: `mcp__baker__baker_vault_read({path: "_ops/skills/it-manager/SKILL.md"})` returns full content.
3. If verification succeeds → Phase D done. Phase E (CHANDA Inv 9 refinement + pipeline frontmatter filter) is the final SOT phase — Tier B, Director auth required before touching `CHANDA.md`.

B1 standing down after ship.
