---
name: render_envvar_paginated_put_regression
description: NEVER raw PUT /v1/services/{id}/env-vars without paginating the GET. Render's GET endpoint default page size is 20; PUTting that array deletes everything beyond page 1. Use ?limit=100 OR per-key endpoint OR MCP merge mode.
type: feedback
---

**Rule:** Render env-var PUT replaces the entire array. Never PUT without first
fetching ALL pages of the GET. Default GET page size is 20 — silently
truncates the live env state.

**Why:** 2026-04-29 09:14Z, AI Head A added `SLACK_SIGNING_SECRET` via raw PUT
on Render. The GET that fed the merge returned only 20 of ~100 env vars.
Resulting PUT wiped 80 vars including `BAKER_API_KEY` (MCP auth),
`POSTGRES_PASSWORD`, `QDRANT_API_KEY`, `ANTHROPIC_API_KEY`, all `NEON_*`,
all `BAKER_*` URLs, etc. System ran on cached secrets in process memory
until next restart, which broke MCP auth + DB writes systemwide.

Recovery cost: ~45 min, regenerated 32 vars from local `.env` + 1Password +
hard-coded defaults. Some non-critical vars (cost thresholds, behavior
flags) are still operating on code-default fallbacks.

**How to apply:**
- Render env-var ops: ALWAYS use `?limit=100` on the GET (Render's max page
  size is 100), OR use the per-key endpoint `PUT /v1/services/{id}/env-vars/{key}`,
  OR use MCP merge mode per `.claude/rules/python-backend.md` (which I missed
  on 04-29 — surfaced post-incident).
- Defense in depth: before any env-var PUT, log `len(current_array)` and
  `len(merged_array)` and ABORT if `merged_count < current_count`. The PUT
  should only ever ADD or KEEP, never reduce.
- Pair with the existing `.claude/rules/python-backend.md` rule. Consider
  hard-stop hook on raw PUT to env-vars endpoint.
