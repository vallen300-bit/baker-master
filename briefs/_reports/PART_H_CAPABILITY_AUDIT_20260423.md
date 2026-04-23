# Part H §H1 Audit — 22 capabilities — 2026-04-23

**Scope:** Retroactive Amendment H §H1 invocation-path enumeration for every
active row in `capability_sets` (22 rows as of 2026-04-23 per `SELECT COUNT(*)
FROM capability_sets WHERE active = TRUE`). Produced as BRIEF_PM_SIDEBAR_STATE_
WRITE_1 D5.

**Method:** per slug, `grep -rn "\"<slug>\"\|'<slug>'" orchestrator/ outputs/
triggers/ memory/ --include="*.py" | grep -v "_test\|_archive\|briefs/"`.
Entries then classified by surface type (sidebar / decomposer / signal /
capability-runner / agent / other) and read/write state.

---

## Summary

- **2 capabilities with live GAP (fixed in this brief):** `ao_pm`, `movie_am`.
  Pre-D2 both were written only by the capability-runner internal loop + agent
  + signal detector; sidebar + decomposer surfaces were read-only.
- **20 capabilities read-only-intentional.** 17 Pattern-2 domain + 3 meta.
  None of them own a `pm_project_state` row; they are reference-only by design.
- **0 capabilities with undocumented gaps.** The audit surfaced no third
  client_pm or meta-cap with a silent write-path hole.

`SELECT COUNT(*) FROM capability_sets WHERE active = TRUE` → **22** (matches
the audit row count below).

---

## Per-capability matrix

### Client PMs (2) — own a `pm_project_state` row; write-path must be closed.

| Slug | Type | Primary callers (file:line) | Reads state? | Writes state? |
|---|---|---|---|---|
| `ao_pm` | client_pm | `orchestrator/capability_runner.py:47` (PM_REGISTRY entry) · `orchestrator/capability_runner.py:1117` (runner auto-update call) · `orchestrator/agent.py:925,927,937,2016,2026,2031` (agent tool routes) · `orchestrator/pm_signal_detector.py:136` (email/whatsapp/meeting signal) · `outputs/dashboard.py` (sidebar fast-path + delegate-path — both wired in D2) · `scripts/backfill_pm_state.py` (new D4) | full (Layer 1 `pm_project_state`, Layer 2 view files, Layer 3 Qdrant) | **✅ (post-D2)**: `opus_auto` from runner, `sidebar`/`decomposer` from dashboard, `pm_signal_<channel>` from detector, `backfill_YYYY-MM-DD` from script |
| `movie_am` | client_pm | `orchestrator/capability_runner.py:110` (PM_REGISTRY entry) · same runner/agent/detector surfaces as `ao_pm` · `outputs/dashboard.py` sidebar (post-D2) · `scripts/backfill_pm_state.py` | full | **✅ (post-D2)**: same tag set as `ao_pm` |

### Domain capabilities (17) — reference-only, no `pm_project_state` row.

| Slug | Type | Domain | Representative caller (file:line) | Reads state? | Writes state? | Read-only reason |
|---|---|---|---|---|---|---|
| `ai_dev` | domain | projects | `outputs/dashboard.py` capability routing (registry lookup only) | n/a | ❌ | Pattern-2 domain capability — no `pm_project_state` row by design; reference-only via `capability_sets` row |
| `asset_management` | domain | projects | `orchestrator/capability_runner.py` runner loop · `outputs/dashboard.py` fast-path | n/a | ❌ | Same as above |
| `communications` | domain | chairman | `orchestrator/capability_runner.py` runner loop | n/a | ❌ | Same |
| `finance` | domain | chairman | `orchestrator/capability_runner.py` runner loop · `outputs/dashboard.py` fast-path | n/a | ❌ | Same |
| `it` | domain | projects | `orchestrator/capability_runner.py` runner loop | n/a | ❌ | Same |
| `legal` | domain | projects | `orchestrator/capability_runner.py` · `orchestrator/research_trigger.py:219,295` (suggested specialists) · `outputs/dashboard.py:10332` (default triplet) | n/a | ❌ | Same |
| `marketing` | domain | network | `orchestrator/capability_runner.py` runner loop | n/a | ❌ | Same |
| `pr_branding` | domain | network | `orchestrator/research_trigger.py:104,295` (research suggestions) | n/a | ❌ | Same |
| `profiling` | domain | chairman | `orchestrator/context_selector.py:84` · `orchestrator/research_executor.py:30` · `orchestrator/research_trigger.py:104,106,219,295` · `outputs/dashboard.py:10332` | n/a | ❌ | Pattern-2 domain capability — used by research-triplet assembly; no per-capability state row |
| `research` | domain | network | `orchestrator/research_executor.py` · `orchestrator/research_trigger.py` (24 hits — heavy use for trigger classification + specialist routing) | n/a | ❌ | Same |
| `russo_ai` | domain | chairman | PM_REGISTRY-adjacent (0 hardcoded slug literals; discovered via `capability_sets` row + DB lookup in agent) | n/a | ❌ | Russo tax capability — routes through generic domain loop |
| `russo_at` | domain | chairman | same as `russo_ai` | n/a | ❌ | Same |
| `russo_ch` | domain | chairman | same | n/a | ❌ | Same |
| `russo_cy` | domain | chairman | same | n/a | ❌ | Same |
| `russo_de` | domain | chairman | same | n/a | ❌ | Same |
| `russo_fr` | domain | chairman | same | n/a | ❌ | Same |
| `russo_lu` | domain | chairman | same | n/a | ❌ | Same |
| `sales` | domain | projects | `orchestrator/capability_runner.py` runner loop | n/a | ❌ | Pattern-2 domain |

### Meta capabilities (3) — route/aggregate, hold no state.

| Slug | Type | Primary callers (file:line) | Reads state? | Writes state? | Read-only reason |
|---|---|---|---|---|---|
| `decomposer` | meta | `orchestrator/capability_registry.py:138` (registry getter) · `orchestrator/capability_router.py:159` (Gemini decomposition cost log) · `orchestrator/capability_runner.py:986,1244` (loop guards that skip decomposer/synthesizer) · `outputs/dashboard.py:8168,8234,8250` (delegate-path guard + mutation_source tag) | n/a | ❌ (its *output* drives `decomposer` writes on delegate path, but those writes target the routed client_pm slug, not `decomposer` itself) | Meta capability — routes other caps; output is the mutation_source tag, not the pm_slug |
| `synthesizer` | meta | `orchestrator/capability_registry.py:143` · `orchestrator/capability_runner.py:986,1244` · `outputs/dashboard.py:8168` | n/a | ❌ | Meta capability — aggregates specialist output into a single answer |
| `profiling` | *(listed under domain by DB, role-wise meta-ish)* | see domain row above | n/a | ❌ | Classified in DB as domain (chairman) but used as a meta-style "people intel" triplet member by research trigger; still no `pm_project_state` row |

**Note on meta classification.** DB schema counts `decomposer` + `synthesizer`
as meta (`capability_type = 'meta'`). `profiling` is domain in DB but behaves
meta-ish as a research-triplet member (documented row above).

---

## §H2 — write-path closure verification

For every slug in PM_REGISTRY (`ao_pm`, `movie_am`), the set of meaningful
write surfaces after this brief equals: {capability-runner Opus loop,
agent.run_agent_loop, pm_signal_detector (4 channels), dashboard fast-path
sidebar, dashboard delegate-path decomposer, backfill script}. The sidebar
gap flagged by the anchor incident is closed; no other gap surfaced in the
audit.

For every slug NOT in PM_REGISTRY (20 caps), no `pm_project_state` row
exists → the write surface is empty by design. Reads go through
`capability_sets.system_prompt` + per-route tooling.

## §H3 — read-path completeness (spot-check)

Same as BRIEF_PM_SIDEBAR_STATE_WRITE_1 §Part H §H3, unchanged for non-PM
capabilities: runner `run_streaming` path reads Layer 1 + 2 + 3; sidebar +
delegate paths inherit; signal-detector reads Layer 1 partial
(`relationship_state` only); backfill reads Layer 3 only.

## §H4 — `mutation_source` tag inventory (active set)

| Surface | Tag | Status |
|---|---|---|
| Capability runner internal loop | `opus_auto` | unchanged (now delegates to module-level fn) |
| Sidebar fast-path (D2) | `sidebar` | new |
| Sidebar delegate-path (D2) | `decomposer` | new |
| Signal detector — email | `pm_signal_email` | unchanged |
| Signal detector — whatsapp | `pm_signal_whatsapp` | unchanged |
| Signal detector — whatsapp outbound | `pm_signal_whatsapp_outbound` | unchanged |
| Signal detector — meeting (D6, new call site) | `pm_signal_meeting` | new (call site; tag format pre-existed via generic `f"pm_signal_{channel}"` formatter) |
| Backfill script (D4) | `backfill_YYYY-MM-DD` | new |

No conflicting / duplicate tags. All new tags are distinct surface names per
Amendment H §H4 spirit.

## §H5 — cross-surface continuity test

Automatable subset (`test_extract_and_update_pm_state_tags_mutation_source`
in `tests/test_pm_state_write.py`) covers the round-trip tag-propagation
piece. Full 5-minute sidebar→decomposer cross-surface test is manual per
brief §H5 — scheduled for AI Head post-merge.

---

## Observations for follow-up (non-blocking)

- **`orchestrator/agent.py:2031`** calls `store.update_pm_project_state(pm_slug,
  updates, summary)` without `mutation_source=` — falls back to the default
  `'auto'`. Minor Part H §H4 tag-hygiene gap. Not in this brief's scope per
  dispatch §"Non-blocking side observation". Recommend a one-line fix in a
  follow-up: pass `mutation_source='agent_tool'` or similar.
- No other silent write-path found during the 22-cap grep pass.

— B2, 2026-04-23
