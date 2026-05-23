---
status: pending
brief: briefs/BRIEF_BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1.md
brief_id: BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1
target_repo: baker-master
working_dir: /Users/dimitry/bm-b1
working_branch: b1/baker-vip-mcp-expose-provenance-fields-1
dispatched_by: lead
dispatched_at: 2026-05-23T13:55:00Z
estimated_time: 1-2h
complexity: low
tier: B
ratified_by: Director
ratified_at: 2026-05-23 chat (§X-26)
---

# CODE_1_PENDING — BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 — 2026-05-23

**Brief:** `briefs/BRIEF_BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1.md`
**Working branch:** `b1/baker-vip-mcp-expose-provenance-fields-1`
**Working dir:** `~/bm-b1`
**Dispatched by:** `lead` (AH1-Terminal)
**Dispatched at:** 2026-05-23T13:55Z
**Estimated time:** ~1-2h
**Complexity:** Low
**Tier:** B (Director-ratified §X-26 2026-05-23 chat)

Previous SUBSTACK_NATE_INGEST_1 dispatch → PR #248 merged eeca2e0 at 2026-05-23T13:53:27Z. Gate chain cleared, 3 nits captured to §X fast-follow (NOT this brief).

## Pre-requisites

- `git pull --rebase origin main` already done on `~/bm-b1` (you're at eeca2e0 — SUBSTACK merged + this brief committed at ee9c5e7).
- No env vars beyond what your current bm-b1 picker already has.
- `vip_contacts` table has `linkedin_url` (TEXT) + `source_of_introduction` (TEXT) columns (verified at `memory/store_back.py:2376/2383`).

## Acceptance criteria (testable)

Per the brief's full §AC list — read the full brief, not just this mailbox. Highlights:

1. `baker_mcp/baker_mcp_server.py:259` tool description rewritten to enumerate the returned provenance fields (`linkedin_url`, `source_of_introduction`).
2. `baker_mcp/baker_mcp_server.py:263` input schema `search` param description rewritten to list the additional searchable fields.
3. `baker_mcp/baker_mcp_server.py:1397` SQL WHERE clause extended: `OR linkedin_url ILIKE %s OR source_of_introduction ILIKE %s` (plus the matching param tuple).
4. 4 static-source tests in `tests/test_baker_mcp_vip_search.py`:
   - description text contains "linkedin_url" + "source_of_introduction"
   - input schema search-param description names the additional fields
   - SQL WHERE clause string contains the two new ILIKE clauses
   - param-tuple length matches the WHERE-clause `%s` count
5. `bash scripts/check_singletons.sh` clean.
6. Syntax check: `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True); print('OK')"`.

## Pre-verify (grep-verify before commit)

Per the brief — verify before editing:

1. `grep -n "name=\"baker_vip_contacts\"" baker_mcp/baker_mcp_server.py` — confirm line ~258 hasn't shifted.
2. `grep -n "WHERE name ILIKE" baker_mcp/baker_mcp_server.py` — confirm line ~1397 hasn't shifted.
3. `grep -n "ADD COLUMN IF NOT EXISTS linkedin_url\|ADD COLUMN IF NOT EXISTS source_of_introduction" memory/store_back.py` — confirm columns exist.

## Ship gate

- Literal `pytest tests/test_baker_mcp_vip_search.py -v` output in ship report. Paste in PR description. No "by inspection."
- Syntax check both modified files.
- `bash scripts/check_singletons.sh` clean.

## Reporting

- Ship PR against baker-master `main` from branch `b1/baker-vip-mcp-expose-provenance-fields-1`.
- **Bus-post `lead` on PR open** with topic `ship/baker-vip-mcp-expose-provenance-fields-1` (`dispatched_by: lead` ⇒ ship-report to `lead`).
- Gate chain on PR open per brief: Gate-1 (AH1 static) + Gate-2 (`/security-review` — SQL change touches DB read; safe but skill fires).
  - Gate-3 (picker-architect) skipped — no UI surface.
  - Gate-4 (code-reviewer 2nd-pass) skipped — internal MCP tool surface, no Director-facing endpoint, no external auth surface, no DB schema migration. If you disagree, surface in ship report.

## Out of scope (Do NOT touch)

- `vip_contacts` schema (columns already exist — no ALTER TABLE)
- `baker_upsert_vip` tool (separate symmetry brief if needed; not this one)
- Other MCP tool surfaces (deadlines / matters / scan / etc.)
- Dashboard surfaces (no UI for v1)
- Migration files (no DB change)
- `outputs/dashboard.py`

## Anchor

§X-26 — Director-ratified 2026-05-23 chat. Surfaced by cowork-ah1 on bus #732 (Phase 3 researcher live-test finding). Brief authored 2026-05-23 by `lead` (ee9c5e7).
