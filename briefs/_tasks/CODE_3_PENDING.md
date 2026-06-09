---
status: PENDING
brief_id: BAKER_SEARCH_MCP_LOOPBACK_DIAGNOSE_1
dispatch: BAKER_SEARCH_MCP_LOOPBACK_DIAGNOSE_1
to: b3
dispatched_by: lead
priority: MEDIUM
supersedes: M365_QDRANT_EMBED_GAP_DIAGNOSE_1 (COMPLETE — PRIMARY env fix shipped + verified PASS 2026-06-09, bus #2668)
Harness-V2: applies (MCP tool surface) — Context Contract + task class + done rubric + gate plan below
---

# BAKER_SEARCH_MCP_LOOPBACK_DIAGNOSE_1 — baker_search/health/scan MCP tools unreachable from non-colocated sessions

## Context (Context Contract)

Surfaced during the M365 arc (your PRIMARY + deputy's #343 verification, both 2026-06-09). The Baker MCP tools `baker_search`, `baker_health`, `baker_scan` return `[Errno 111] Connection refused` from any Claude Code session NOT colocated with the running prod dashboard — reproduced by b2 (Phase 1 #2623), codex (#2627: "handler loopbacks to localhost:8080"), AND lead's own session today. Other MCP tools (Postgres-backed: baker_raw_query, baker_email_search, etc.) reach prod fine. So this is specific to the handlers that call back to `localhost:8080` instead of the configured baker-master URL.

**Impact:** agents (AH1, AH2, B-codes) calling `baker_search` for semantic fact-finding get a hard Errno 111, not results. Director's own surfaces (dashboard Cockpit, Clerk, in-prod agents) are colocated and unaffected — this is an agent-tooling gap, not a Director-facing outage. Pre-existing (predates today's PRs); NOT introduced by #342/#343.

## Problem

The `baker_search` / `baker_health` / `baker_scan` MCP tool handlers target `localhost:8080`, which only resolves when the MCP server runs on the same host as the dashboard. From a remote/local Claude Code session the dashboard isn't on localhost → connection refused. Make these tools reach the live baker-master surface like the other HTTP-backed tools do.

## Phase 1 — DIAGNOSIS (read-only, NO code changes, report first)

1. Confirm the exact loopback: in `baker_mcp/baker_mcp_server.py`, find the `baker_search` / `baker_health` / `baker_scan` handlers and confirm they call `http://localhost:8080/...` (or `127.0.0.1:8080`) rather than a configured base URL. Cite file:line.
2. Compare with a WORKING HTTP-backed MCP tool (e.g. how `baker_email_search` or any tool that reaches prod resolves its base URL) — what config/env does the working path use (BAKER_API_URL / baker-master.onrender.com + X-Baker-Key)?
3. Confirm the prod endpoints these tools need actually exist + work (you already proved `/api/search` + `/api/search/unified` live today): so the fix is purely pointing the handler at the right base URL + auth, not building an endpoint.
4. Identify every handler with the localhost:8080 assumption (don't fix only the 3 named ones if others share it).

**STOP after Phase 1.** Bus-post `lead` the file:line list + the smallest fix (point handlers at the configured base URL + key, with localhost as a fallback only when colocated). Do NOT implement until lead greenlights.

## Current State

Established by Phase 1 — diagnosis-first. Reproduce the Errno 111, then locate the hardcoded localhost.

## Phase 2 — FIX (only on lead greenlight)

Point the affected handlers at the configured baker-master base URL (env-driven, e.g. BAKER_API_URL / the same source the working HTTP tools use) + X-Baker-Key, falling back to localhost only when genuinely colocated. Tests first (mock the base-URL resolution; assert no hardcoded localhost). Keep behavior identical when colocated (prod must not regress).

## Files to touch (Phase 2, expected — confirm in Phase 1)

- `baker_mcp/baker_mcp_server.py` — the search/health/scan handlers + base-URL resolution

## Do NOT Touch

- The Postgres-backed MCP tools that already reach prod — they work; don't refactor them.
- The dashboard endpoints themselves — they're live; this is client-side base-URL wiring only.

## Verification (done rubric — task class: MCP tooling bugfix)

NOT "tests pass". Done =
1. `baker_search` from a NON-colocated session (a B-code / AH session) returns results for a known query (e.g. Spanyi), not Errno 111.
2. `baker_health` + `baker_scan` likewise reachable.
3. Colocated/prod path unchanged (no regression).
4. POST_DEPLOY_AC_VERDICT v1 with a live non-colocated `baker_search` result pasted.

## Quality Checkpoints

1. AC1: Phase 1 file:line diagnosis on bus with the localhost evidence.
2. AC2: live non-colocated baker_search returns results post-fix.
3. AC3: no hardcoded localhost remains in the affected handlers (test asserts).
4. AC4: prod colocated behavior unchanged.

## Gate plan

G0 codex on diagnosis + fix plan → lead reviews Phase 1 → G2 /security-review (touches the MCP surface + auth/base-URL) → G3 codex on diff → lead merges → POST_DEPLOY_AC live-verified from a non-colocated session.

## Escalation

- If the base URL / key the MCP tools should use isn't already in env → prepare the exact env addition + flag to lead (Tier-B).
