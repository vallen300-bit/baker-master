---
status: PENDING
brief: briefs/BRIEF_BAKER_SUBSTACK_SEARCH_1.md
brief_id: BAKER_SUBSTACK_SEARCH_1
target_repo: baker-master
working_dir: /Users/dimitry/bm-b1
working_branch: b1/baker-substack-search-1
dispatched_by: cowork-ah1
dispatched_at: 2026-05-23T17:00:00Z
estimated_time: 5-6h
complexity: medium
tier: B
ratified_by: Director
ratified_at: 2026-05-23 chat ~16:30Z (Option B over A and C)
---

# CODE_1_PENDING — BAKER_SUBSTACK_SEARCH_1 — 2026-05-23

**Brief:** `briefs/BRIEF_BAKER_SUBSTACK_SEARCH_1.md` (commit `c1fdcc1`)
**Working branch:** `b1/baker-substack-search-1`
**Working dir:** `~/bm-b1`
**Dispatched by:** `cowork-ah1` (AH1-Cowork) — **report back to `cowork-ah1` on PR open**
**Dispatched at:** 2026-05-23T17:00Z
**Estimated time:** ~5-6h
**Complexity:** Medium
**Tier:** B (Director-ratified 2026-05-23 chat ~16:30Z — Option B over A and C)

## Goal in one sentence

Build a Perplexity-style queryable MCP tool so every Brisen agent can call `baker_substack_search(publication, query, limit)` and get top-k matching posts with excerpts + URLs from any subscribed Substack archive (Nate Jones seeded today; future Substack subs zero-code-change).

## Pre-requisites

- `git pull --rebase origin main` on `~/bm-b1` (you're behind by 2: PR #247 BACKFILL_PREFLIGHT + this brief commit `c1fdcc1`).
- Standard bm-b1 env (VOYAGE_API_KEY, QDRANT_URL, QDRANT_API_KEY all sourced from 1Password via your existing flow).

## IMPORTANT — SKIP brief Step 1 (auth probe)

The auth probe described in brief §"Step 1 — Auth probe" has been run cowork-side this session (2026-05-23 ~16:55Z) and PASSED:

- Cookie extracted from Director's logged-in Chrome via Chrome MCP, stored at `op://Baker API Keys/SUBSTACK_COOKIE_natesnewsletter/credential` (apicredential schema, `credential` field, 83 chars, expires 2026-08-21).
- `curl -H "Cookie: substack.sid=<val>" https://natesnewsletter.substack.com/api/v1/posts/rag-agents-knowledge-layer-architecture` returned HTTP 200, 52KB JSON, `body_html` present (36,377 chars) on a paid-only post.

**Proceed directly to brief Step 2 (backfill script).**

## Render env requirement (cookie injection — bm-b1 cannot do this directly)

The brief's Step 2 requires `SUBSTACK_COOKIE_natesnewsletter` on Render env (production worker reads it for forward-flow ingest in Fix/Feature 2). bm-b1 cannot push Render env directly. Two paths:

- **Path A (preferred):** bm-b1 finishes brief, ships PR, bus-posts cowork-ah1 on PR open. cowork-ah1 (or lead) injects the Render env via 1P → Render API in same turn as gate-chain firing, BEFORE merge so deployed worker has the cookie.
- **Path B:** bm-b1 only writes the script + tests, omits forward-flow Qdrant embed live wiring. PR merges. AH1 wires Render env + AH1 manually triggers backfill via Render shell as separate one-shot.

**Recommendation: Path A** — keeps the brief atomic + cleaner audit trail.

## Pre-verify (grep before edit — surface in ship report)

1. `grep -n "TOOLS = " baker_mcp/baker_mcp_server.py` — confirm catalog line.
2. `grep -n "_should_skip_pipeline\|_format_results" triggers/substack_ingest.py` — confirm PR #248 structure unchanged.
3. `grep -rn "voyage-3\|voyage_client" kbl/` — confirm embed pattern reuse path.
4. `grep -rn "QdrantClient\|qdrant_client" .` | head -10 — confirm import pattern.
5. `ls scripts/backfill_meeting_transcripts_matter_slug.py scripts/backfill_nate_substack.py` — confirm sibling-script patterns to mirror (env pre-flight + --dry-run/--apply pair).

## Ship gate

- Literal pytest output for new tests in ship report.
- Syntax check Python files + `bash scripts/check_singletons.sh` clean.
- For the MCP tool: confirm it appears in `TOOLS` catalog + dispatch branch handles it + new test in `tests/test_baker_mcp_server.py` covers happy-path + missing-publication.
- Backfill script `--dry-run` against Nate's archive in ship report (post count + total est. embed cost surfaced).

## Reporting

- Ship PR against baker-master `main` from branch `b1/baker-substack-search-1`.
- **Bus-post `cowork-ah1` on PR open** with topic `ship/baker-substack-search-1` (`dispatched_by: cowork-ah1` ⇒ ship-report routes to `cowork-ah1`).
- Gate chain on PR open: Gate-1 (AH1 static) + Gate-2 (`/security-review` — touches cookie handling + new MCP tool + Qdrant write) + Gate-3 (`feature-dev:picker-architect` SKIPPED unless brief uncovers dashboard route addition) + Gate-4 (`feature-dev:code-reviewer` 2nd-pass — fires per Protocol trigger 1: new external auth surface).

## Out of scope (Do NOT touch)

- `outputs/dashboard.py` route handlers (MCP tool surface is enough for Director-side; dashboard surface separate brief later).
- Other matters/desks/sentinels.
- Forward-flow Gmail trigger code (only the Qdrant-embed extension per brief Fix/Feature 2).
- Migration files unless brief spec requires a new table (it doesn't — Qdrant only).
- `baker-vault/slugs.yml` (separate repo).

## Anchor

Director ratified 2026-05-23 ~16:30Z chat — *"How to make it possible that you or AH2 or any other agents can reach Nat Jones's Substack full data in a similar way to how we reach Perplexity, NotebookLM, etc.?"* — Option B selected over A (Nate-only) and C (lazy on-demand). Pre-engineering (cookie + auth probe) closed cowork-side this session.
