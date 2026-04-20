# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (fresh terminal tab)
**Task posted:** 2026-04-20 (afternoon, post-bridge-merge + post-Phase-B-symlink-flip)
**Status:** OPEN — SOT Phase D (vault-read MCP tools for Cowork)

---

## Task: SOT_OBSIDIAN_1_PHASE_D_VAULT_READ — equip Cowork-side AI Dennis from the vault

Brief: `briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md` (this commit). Read end-to-end — self-contained spec with mirror strategy, tool shapes, safety constraints, tests, and Day 1 protocol.

**Target PR:** against `baker-master`. Branch: `sot-obsidian-1-phase-d-vault-read`. Base: `main`. Reviewer: B2.

### Why this matters now

Phase B completed earlier today — local Claude App (Director's Mac) now reads AI Dennis's skill + memory from the canonical vault copy via symlink. But Cowork runs cloud-side, has no local filesystem, and can't see the symlink. Today she's still reading a cloud-delivered registry copy that will drift from the vault over time.

The existing Baker MCP at `https://baker-master.onrender.com/mcp` is already registered with Cowork. Adding two small tools (`baker_vault_read`, `baker_vault_list`) to it is the simplest transport — no new server, no new auth, no new client config.

### Scope summary (full detail in brief)

- Vault mirror at `/opt/render/project/src/baker-vault-mirror/` populated at startup (git clone) and refreshed every 5 min (APScheduler job `vault_sync_tick`, env `VAULT_SYNC_INTERVAL_SECONDS` default 300, floor 60).
- Two new MCP tools registered on existing Baker MCP: `baker_vault_list(prefix)` + `baker_vault_read(path)`. Both scoped to `_ops/**`, `.md` + registry files only, 128KB cap, path-traversal safe.
- `/health` extended with `vault_mirror_last_pull` + `vault_mirror_commit_sha`.
- Tests: happy path + traversal + out-of-scope + nonexistent + binary + list. Integration via `needs_vault_mirror` fixture (local temp git repo).
- Append Cowork-consumption section to `_ops/agents/ai-dennis/OPERATING.md` (part of this PR) documenting the new call pattern.

### Key constraints

- **Mirror is read-only.** Never `git push` from Render. Pull only.
- **Path safety is load-bearing.** Traversal regression = arbitrary file read on Render container. Tests must cover.
- **No secrets in vault.** Audit `grep -r -iE "(api[_-]?key|password|token|secret)" baker-vault/_ops/` — zero hits or docs-only. Flag to B2 if surprising.
- **No schema changes.** DB untouched.

### Paper trail

- Baker decision already stored upstream: SOT parent brief at `11922`. This sub-brief ratified in chat; commit it + log a decision via `mcp__baker__baker_store_decision` in your ship report.
- Commit message cites `SOT_OBSIDIAN_1_PHASE_D_VAULT_READ` + `Co-Authored-By: AI Head <ai-head@brisengroup.com>` + your own line.

Report to `briefs/_reports/B1_sot_phase_d_ship_<YYYYMMDD>.md` on baker-master when shipped. B2 reviews per normal flow. AI Head auto-merges on APPROVE per Tier A.

### After this (Day 1 protocol)

Once merged + Render redeploys:
1. AI Head tests both new tools from a Cowork-invoked AI Dennis session.
2. Confirms Cowork can read her own canonical files through the MCP.
3. If verification succeeds, Phase D done; Phase E (CHANDA Inv 9 refinement) is the final SOT piece — Tier B, Director auth required before you touch CHANDA.md.

Close tab after ship.
