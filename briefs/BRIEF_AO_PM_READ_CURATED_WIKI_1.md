# BRIEF: AO_PM_READ_CURATED_WIKI_1 — AO-PM capability reads curated wiki for cycle matters (capital-call, drawdowns)

**Status:** V0.1 — ready to dispatch
**Author:** AH2 (terminal session, 2026-05-16)
**Reviewer:** AH1 cross-lane + `/security-review` (Cortex Design boundary — capability read-path touches ai-head-autonomy-charter §4)
**Target build lane:** B3 (already familiar with capability infra from BRIEF_CAPABILITY_THREADS_1) or B2 (deep PM-state context)
**Tier:** B (architectural — capability read-path)
**Branch convention:** `b<N>/ao-pm-read-curated-wiki-1`
**Trigger:** Director conversation 2026-05-16 ~07:57Z. Meeting briefing said "AO is late on EUR 2.5M April capital transfer / elephant in the room"; Director corrected at 08:12Z — Apr 2.5M was received 24-28 Apr 2026 per `wiki/matters/capital-call/curated/02_money.md` (curated 2026-05-01). Baker's AO-PM capability never saw the wiki update because it reads only the structured DB row `pm_project_state.ao_pm.state_json`, whose `capital_calls` field still says `"fully_funded — confirmed by Constantinos 03.04.2026"` (April-3 cumulative reconciliation, semantically wrong for the Apr-Jun 2026 cycle question).

---

## Problem

**Read-path gap.** AO-PM capability (`orchestrator/capability_runner.py:_auto_update_pm_state` + system-prompt injection at runtime) consumes `pm_project_state.ao_pm.state_json` as its persistent state. Curated wiki (`wiki/matters/<slug>/curated/*.md`, the canonical knowledge layer per RA-23 / Cortex 3T architecture) is invisible to this read-path.

Consequence: every fact written to curated wiki by AH1, AH2, or B-codes (Director-ratified or Cortex-curated) is dark to AO-PM until/unless the same fact independently lands in the DB state_json — which only happens via Opus extraction on a triggering signal, or a manual `_update_pm_state` agent tool call.

Empirical proof (2026-05-16 diagnosis):

| Source | Last touched | Says about Apr 2.5M tranche |
|---|---|---|
| `wiki/matters/capital-call/curated/02_money.md` | 2026-05-01 Q4-Q10 cascade | "Drawdown #1 RECEIVED at LCG CBH Switzerland 24-28 Apr 2026" + €700K + €1.8M two-leg breakdown |
| `wiki/matters/capital-call/curated/00_overview.md` | 2026-04-30 (b3) | "drawdown drafted; Edita to sign LCG `[?]` confirm wire received" (stale) |
| `pm_project_state.ao_pm.state_json.capital_calls` | byte-identical across versions 1-139 | `status: "fully_funded — confirmed by Constantinos 03.04.2026"` — answers a different question entirely (cumulative through March, not Q2-2026 cycle) |

Result: AO-PM-generated briefings systematically miss Q2-2026 cycle facts. The cycle has its own dedicated matter slug (`capital-call`), its own curated knowledge, but no read-path into AO-PM responses.

## Why this matters beyond today

This is a **class bug**, not a one-off. Any matter with cycle-state changes (capital-call drawdowns, Hagenauer court deadlines, Aukera signing gates, MOVIE WC monthly cadence) updates curated wiki on a faster cadence than the DB state_json reflects. AO-PM, MOVIE-AM, and any future per-matter PM capability will give Director stale answers on the live question until this read-path is fixed.

## Fix — three viable options, recommendation = Option B

**Option A — Pipeline curated → state_json (heavy).**
Background job (cron or Cortex Phase 2-style) reads curated wiki for each active matter and re-extracts structured state into `pm_project_state.<slug>.state_json`. Requires Opus extraction per matter per cadence. Cost: high ($ + latency + extraction-fragility risk). Out of scope here.

**Option B — RECOMMENDED. AO-PM context-builder injects curated wiki excerpts for active cycle matters.**
At AO-PM capability invocation time, the system-prompt builder (somewhere in `capability_runner.py` around `_build_system_prompt` / `_compose_context`) gains a step: for each `active_matter` referenced in AO-PM's domain (capital-call, oskolkov, hagenauer-rg7, mo-vie-am, aukera), read the matter's `curated/00_overview.md` + `curated/02_money.md` (capped to ~2K tokens each) and inject into context as `[CURATED WIKI: <slug>/02_money.md]` source-labelled block. State_json stays as one input; curated wiki becomes the second, fresher input. Conflict resolution: prompt explicitly tells Opus to prefer curated wiki when the two disagree on dated facts (cycle status, tranche receipt, deadline state).

**Option C — Switch AO-PM persistent state to a curated-wiki snapshot (heaviest).**
Replace `pm_project_state.ao_pm.state_json` semantics: state_json becomes a cached snapshot of curated wiki facts, refreshed on each AO-PM run via a "read-curated → upsert-state" pre-step. Removes the dual-source problem. Cost: schema-shaping work + every AO-PM call now does I/O. Defer to a v2 follow-up if Option B proves insufficient.

**Recommendation: Option B.** Minimal blast radius, no schema change, no extraction cost. Wiki files are filesystem-read cheap. Director's stated truth ("information is well documented and must be in AO-PM files") is the canonical layer Director already uses — capability should follow.

## Acceptance criteria

1. AO-PM capability response to "what is the status of the April 2026 EUR 2.5M tranche?" cites `wiki/matters/capital-call/curated/02_money.md` (or equivalent `00_overview.md`) and reports "RECEIVED 24-28 Apr 2026" — sourced from wiki, not DB.
2. AO-PM capability response to a question about MOVIE WC pressure pulls fresh content from `wiki/matters/mo-vie-am/curated/` if such curated files exist (graceful no-op if not).
3. Conflict case: when curated wiki and state_json disagree, Opus answer cites the wiki source AND explicitly notes the DB state is stale (e.g., "Note: pm_project_state.capital_calls field still shows fully_funded from 03 Apr baseline; wiki has the live cycle status").
4. Unit test: mock curated wiki content, mock state_json, assert wiki content appears in the prompt the runner sends to Anthropic.
5. Integration test (DB-gated): run AO-PM capability against a real capital-call question, assert response contains `2026-05-01` or `RECEIVED` or `24-28 Apr`.

## Out of scope

- MOVIE-AM read-path migration. Same class bug applies; do it in a follow-up brief once the AO-PM pattern is proven.
- Backfill into state_json — don't sync wiki content back into the DB row; let them diverge cleanly. (Optional: append a `state_json.stale_warning` field on each run noting "state_json is N days behind curated wiki" for future audit.)
- Cortex Phase 2 sense → Phase 3a meta-reasoning re-extraction of curated knowledge. That's the RA-23 Cortex 3T path; this brief is a tactical bridge until Cortex Stage 2+ owns this matter directly.
- Token budget tuning for the curated-wiki injection beyond "cap each file at ~2K tokens"; if total injection exceeds context, drop oldest curated files first (LRU by `last_curated_at` frontmatter).

## Ship gate

1. Code change passes `pytest tests/test_capability_*` (existing) + new test (per acceptance #4).
2. Manual probe via Baker dashboard: ask "AO PM — status of April 2026 tranche" — response cites wiki and says received.
3. `/security-review` clears the new filesystem-read code path (matter slug must be sanitized to prevent path traversal; constrain to `wiki/matters/[a-z0-9-]+/curated/`).
4. AH1 cross-lane review — capability read-path change touches charter §4 (cost / quality / latency triangle); AH1 sign-off required before merge.
5. Post-merge: re-run the 2026-05-16 07:57Z meeting-prep question; assert no "AO is late" wording in the output. (Director can do this verbal-probe; not blocking.)

## Files touched

**Modify (in-repo):**
- `orchestrator/capability_runner.py` — context-builder for AO-PM capability adds curated-wiki read step. Likely 30-60 lines.
- `kbl/curated_wiki_reader.py` (NEW, ~80 lines) — sanitize slug, read `wiki/matters/<slug>/curated/*.md`, return list of (path, body, last_curated_at) tuples. Slug allow-list from `slugs.yml`.
- `tests/test_capability_runner.py` or new `tests/test_ao_pm_curated_wiki.py` — unit + integration tests per acceptance criteria.

**Do NOT touch:**
- `pm_project_state` schema — no change.
- `pm_state_history` — no change.
- `extract_and_update_pm_state` — write-path unchanged (its bug, the parallel-keys issue, is the sister brief PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1).
- MOVIE-AM capability — defer to follow-up brief.
- Dashboard sidebar rendering — still reads state_json for fast paint; only Q&A answers gain wiki context.

## Estimated complexity

Medium · ~3-5 hours · 1 PR · Tier-B architectural fix · Cortex Design boundary (read-path semantics, but additive — not a removal). `/security-review` required (filesystem read with slug input).

## Sister brief

`PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1` — fixes the related write-side bug surfaced today (Baker's `_update_pm_state` tool added two NEW top-level keys `capital_call_EUR_7M` + `"AO April Capital Tranche (EUR 2.5M)"` beside the stale `capital_calls` field at 08:12Z, instead of patching the existing key). Independent merge — can ship in either order.
