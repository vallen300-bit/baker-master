---
status: PENDING
brief: briefs/BRIEF_GROK_API_HARDENING_1.md
brief_id: GROK_API_HARDENING_1
target_branch: b3/grok-api-hardening-1
matter_slug: baker-internal
cross_matter_usage: [ao, mo-vie-am, hagenauer-rg7, cupial, brisen, oskolkov, baden-baden-desk, baker-internal, theailogy]
dispatched_at: 2026-05-17T20:05:00Z
dispatched_by: lead
director_auth: 2026-05-17 chat — "ratified" (post GROK_API_HARDENING_1 brief review + recommendation)
trigger_class: MEDIUM (DB schema change via CHECK constraint → 2nd-pass code-reviewer MANDATORY per SKILL.md trigger #2)
prior_brief_complete: |
  RENDER_ENV_WRITE_GUARD_1 shipped as PR #216 (merge_commit ee61271,
  2026-05-17). This dispatch overwrites the mailbox slot with the new brief.
---

# Dispatch: GROK_API_HARDENING_1

B3 — full brief at `briefs/BRIEF_GROK_API_HARDENING_1.md`.

**TL;DR:** Close 5 nits left over from PR #214 (`GROK_API_CAPABILITY_1`) gate chain. Functional capability is healthy in prod (€0.018 of €250 burned); this is quality-of-implementation work.

- **M1** — rename `_reset_client_for_tests` → `reset_client_cache` in `tools/grok.py` + keep alias + key-rotation docstring + paragraph in `.claude/docs/baker-mcp-api.md`.
- **M3** — per-call `timeout_seconds` arg threaded through `dispatch_grok` → client `ask` / `x_search` / `web_search` → `_request` → `httpx`; validate at dispatcher (positive, ≤ 300); add to 3 inputSchemas.
- **M4** — new migration `migrations/20260518_capability_sets_archive_no_trigger_patterns.sql` that UPDATEs existing archive rows (`grok_realtime` + `claimsmax_archive`) to `trigger_patterns=[]` AND adds CHECK constraint. Matching bootstrap update in `memory/store_back.py:_ensure_capability_sets_table` (~line 2842 per Lesson #50 migration-vs-bootstrap drift).
- **MED** — citation extraction merge: existing top-level `payload["citations"]` + new inline `output[*].content[*].annotations` extraction in `kbl/grok_client.py:_shape_search_response`; dedup by URL; preserve first-seen order.
- **LOW** — BTC smoke probabilistic-failure inline comment in `tests/test_grok_client.py` + paragraph in `.claude/docs/baker-mcp-api.md`.

**Working dir:** `~/bm-b3`
**Branch:** `b3/grok-api-hardening-1` off `main` (already created — head at `640bc35`).
**Estimated time:** ~3-4h.
**Complexity:** Medium (M4 migration ordering is the trickiest; brief specifies UPDATE before CHECK).

## Reply target

Per BUS_REPLY_TO_SENDER_RULE_1 (baker-vault `9562cad`): bus-post `lead` on PR open (topic `pr-open/grok-api-hardening-1`) and again on ship (topic `ship/grok-api-hardening-1`). `dispatched_by: lead` in this mailbox file.

## Ship gate

- Literal `pytest tests/test_grok_client.py tests/test_capability_sets_constraints.py -v` green (no "by inspection").
- All 28 existing Grok tests preserved.
- 11 new tests passing (2 M1 + 4 M3 + 3 MED + 2 M4).
- Apply migration to a copy-of-prod test DB locally; confirm UPDATE clears the 2 archive rows AND CHECK constraint applies cleanly.
- Compile-clean check on `kbl/grok_client.py`, `tools/grok.py`, `memory/store_back.py`.

## Gate chain on PR open

1. AH2 static lane (cross-lane review).
2. AH2 `/security-review`.
3. `code-architecture-reviewer`.
4. `feature-dev:code-reviewer` 2nd-pass — **MANDATORY** per SKILL.md §Code-reviewer 2nd-pass Protocol trigger #2 (DB schema change).

All four must clear before merge. Bus-post `lead` on PR open and the verdicts will route back via `lead`.

## Key constraints (mirrored from brief — read brief for full detail)

- Do NOT edit `migrations/20260517_grok_capability_set.sql` (already applied).
- Do NOT edit `migrations/20260517_claimsmax_capability_set.sql` (ditto; new migration handles its archive row too).
- Do NOT touch `_ops/skills/ai-head/SKILL.md` or any matter desk `LONGTERM.md` (already updated in baker-vault `704495b` this session).
- Do NOT touch `tasks/lessons.md` (append-only; nothing to add here).
- Do NOT alter `capability_type='archive'` on the `grok_realtime` row.
- Do NOT change the lazy `_CLIENT` cache pattern in `tools/grok.py` — keep the double-checked-lock + `httpx.Client` reuse.

## Standing rules to confirm before first commit

- Read `~/baker-vault/_ops/agents/b3/orientation.md` (your role orientation).
- Read this CODE_3_PENDING.md (you're already here).
- Confirm via first-message phrase: `"B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md."`
