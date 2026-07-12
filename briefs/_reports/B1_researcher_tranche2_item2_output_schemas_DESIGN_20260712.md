# DESIGN — Per-type output schemas for research-fan-out (tranche-2 item #6)

**For:** codex design-gate (design-PASS required before build, Director #9255 / dispatch #9299).
**Builder:** b1. **Status:** DESIGN — no code yet. Item #5 merged (vault #175).

## Problem

`research-fan-out/SKILL.md` §5 gives **every** channel sub-agent the SAME generic output contract ("structured note with cited URLs + claims + confidence + verbatim quotes, §8 citation-slot inline"). Sub-agents run cold + independent (§5, §Constraint 6), so each returns free-prose in an idiosyncratic shape. At §6 synthesis the Opus synthesizer must reconcile N differently-shaped prose blobs → **paraphrase drift** (same fact rendered 3 ways, weak cross-comparison, degraded conflict-surfacing — which is the skill's whole point per §6 Mnilax rule).

## Fix

Replace the generic contract with a **typed, per-research-type output schema**. Each fan-out sub-agent fills the schema for the Step-0-locked research type; the synthesizer merges structurally-identical typed rows (drift-proof) and surfaces conflicts **field-by-field**.

## Design

### Base schema (all 8 fan-out-eligible types — 1,2,3,5,6,7,8,10)

Each channel sub-agent returns ONE JSON object:

```json
{
  "channel": "<channel name>",
  "research_type": "<1|2|3|5|6|7|8|10>",
  "findings": [ { "<type-specific fields>": "...", "url": "...", "pub_date": "...",
                  "byline": "...", "accessed": "...", "tier": "primary|secondary|aggregator",
                  "confidence": "HIGH|MEDIUM|LOW", "quote": "<optional verbatim>" } ],
  "coverage_note": "<what this channel could / could not cover>"
}
```

Every `findings[]` row carries the §8 citation-slot fields as **structured keys** (not prose). This keeps §8 canonical while making it machine-mergeable.

### Per-type field sets (the typed contract — 1:1 with each type's `research-types.md` "What to find")

| Type | `findings[]` type-specific keys |
|---|---|
| 1 AI Agent Blueprint | `capability, mechanism, source_role, maturity` |
| 2 Counterparty Profile | `entity, role, affiliation, behavior_note, as_of` |
| 3 Architecture Survey | `system, pattern, example, tradeoff` |
| 5 Regulatory / Standards Radar | `standard_id, body, change, effective_date` |
| 6 Practitioner Benchmark | `practitioner, org, claim, metric` |
| 7 Tooling / OSS Scavenge | `tool, repo, stars, last_release, fit` |
| 8 Curriculum Mapping | `program, institution, module, relevance` |
| 10 Market Intel Snapshot | `datapoint, value, as_of, direction` |

(Types 4 Matter Deep-Dive and 9 Anchor Verification are NOT fan-out-eligible per skill §2 — no schema; sequential path unchanged.)

### Enforcement (kills drift, not just documents it)

1. **Prompt-embedded (§5):** the sub-agent prompt embeds the exact schema for the locked type + "return ONLY this JSON object, no prose."
2. **Synthesizer-side conformance (§6):** the synthesizer rejects a channel whose output doesn't parse to the schema → treats it as a channel failure per §7 (drops to 2/3 with the verbatim caveat). This makes the schema **load-bearing**, not advisory, and preserves the existing failure-mode contract.

### Wiring (venue: baker-vault)

- Edit `_ops/skills/research-fan-out/SKILL.md` §5 "Output contract" bullet → reference the schema; add the §6 conformance-check step.
- New companion `_ops/skills/research-fan-out/output-schemas.md` — base schema + 8 per-type field sets + one JSON example each.
- `_ops/agents/researcher/method.md §10` pointer note.
- Mirror to `~/.claude/skills/research-fan-out/` (skill is dual-located, per the two identical copies observed).

## Questions for codex

1. **Granularity:** base + 8 per-type extensions (this design) vs one universal schema with a free `type_fields` map? I lean base+8 (real typing = real drift-kill).
2. **Format:** strict JSON per sub-agent (clean synthesizer merge) vs strict markdown table? I lean JSON for `findings`, synthesizer renders the human-facing table.
3. **Enforcement:** prompt-embedded only vs + synthesizer-side conformance → §7 failure (this design)? I lean the latter (load-bearing).
4. **Scope check:** this item wires INTO `research-fan-out` by editing its own SKILL.md + a companion — that is the target skill, NOT a violation of its Constraint #3 ("do NOT modify existing Researcher skills" = the OTHER referenced skills: grok/gemma/x-twitter/youtube/anthropic-feature-scout/verify-citations). Confirm editing research-fan-out itself is in-scope.
5. **Dual-location:** SKILL.md exists identically at `_ops/skills/…` (canonical) and `~/.claude/skills/…` (runtime). Edit both, or is one generated from the other?

On design-PASS I build item #6 (vault worktree) → codex build-gate → lead merge.
