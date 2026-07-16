# LEAD_SESSION_START_SLIM_2_1 — cut lead session-start load 11% → ~6%

dispatched_by: lead
Harness-V2: N/A — harness/config trim, no production code path; AC = measured token deltas.
priority: high

## Context

Director directive 2026-07-16: "start with 5-6% load bearing after pin; harnesses were sized for Opus, lead now runs Fable — pointers are enough." Lead measured the startup surface this session; table below is bytes-on-disk, live-verified.

## Problem (measured, bytes on disk; tokens ≈ bytes/4)

Lead session-start context ≈ 11% of the 1M window. Breakdown of the trimmable part:

| Source | Bytes | ~Tokens | Note |
|---|---|---|---|
| Skills catalog frontmatter (vault `_ops/skills`, 137 skills) | 109,150 | ~27k | ALL load into system prompt; most are desk/register skills lead never fires |
| Project CLAUDE.md (`bm-aihead1/CLAUDE.md`) | 20,703 | ~5.2k | AH1 orientation block duplicates orientation.md + tier tables |
| `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/MEMORY.md` | 26,831 | ~6.7k | OVER its own 24.4KB cap — harness truncates with warning |
| `_ops/agents/aihead1/orientation.md` (Tier-0 read) | 13,061 | ~3.3k | rules restated 3× across files |
| `_ops/skills/ai-head/SKILL.md` (Tier-0 read) | 13,334 | ~3.3k | same duplication |
| `dropbox-tier0.md` (auto-load) | 11,093 | ~2.8k | Rules 5/6 full bodies ALSO injected by lead.md hook |
| `.claude/role-context/lead.md` hook injection | 6,436+ | ~2.6k | full laconic prose; spec needs ~1KB |
| PINNED.md §A | file carries 6 dated sections | ~2.5k/read | pin discipline says delete superseded; only newest + carried-opens needed |

Fixed harness (tool schemas, deferred-tool name list, agent registry) ≈ 3% — out of scope.

## Work items

1. **Per-role skill manifest (biggest win, ~23k tokens).** Lead picker must load ONLY lead-relevant skills (~30: ai-head*, write-brief, pin-protocol, laconic, architecture/eval/model-selection family, bus/dispatch SOPs, deep-research, code-review family). All other vault skills stay installed for desks but are NOT symlinked/registered into `bm-aihead1` picker. Add ONE `skill-index` pointer skill (≤120-char description) whose body lists the full catalog + trigger map so lead can still discover+Read any de-registered skill on demand. DO NOT edit shared vault skill descriptions (other Opus agents rely on verbose triggers) — this is registration-scope only.
2. **Collapse the 3 orientation surfaces.** `orientation.md` + `ai-head/SKILL.md` + project CLAUDE.md AH1 block restate the same rules (register, tiers, hard rules, dispatch protocol). Produce ONE slim `orientation.md` ≤4KB (pointers to canonical process files, no restated bodies); shrink the project CLAUDE.md AH1 block to the read-order list + confirmation phrase; ai-head SKILL.md body → pointers into companion skills (already split — finish the job).
3. **MEMORY.md prune to <12KB.** Index lines ≤200 chars, move detail to `MEMORY_ARCHIVE.md`. It is currently over-cap and truncating.
4. **lead.md role-context hook → bare 5-block laconic spec (~1KB)** + drop the Rules 5/6 bodies (already in dropbox-tier0).
5. **dropbox-tier0 pointerize** Rules 3-6 bodies to the canonical process file (keep 1-line summaries) — CAUTION: fleet-wide file, codex gate + lead line-read mandatory before merge.
6. **PINNED §A hygiene** — lead does this himself at next pin (not this brief); note only.

## Files Modified

- `bm-aihead1` picker skill registrations (symlinks / manifest under `~/bm-aihead1/.claude/skills/`) — item 1
- NEW: `_ops/skills/skill-index/SKILL.md` (pointer skill) — item 1
- `_ops/agents/aihead1/orientation.md` — item 2 (rewrite ≤4KB)
- `_ops/skills/ai-head/SKILL.md` — item 2 (pointerize)
- `bm-aihead1/CLAUDE.md` AH1 block — item 2 (shrink)
- `~/.claude/projects/-Users-dimitry-bm-aihead1/memory/MEMORY.md` + `MEMORY_ARCHIVE.md` — item 3
- `bm-aihead1/.claude/role-context/lead.md` — item 4
- `~/.claude/dropbox-tier0.md` — item 5 (fleet-wide, gated)

## Verification

- Before/after byte table per file (script: `wc -c` sweep committed with the PR).
- Fresh lead session context-meter reading post-merge (target ≤6.5%).
- 5-skill discoverability spot-check transcript pasted in ship report.
- Per-picker registration diff (AC3) pasted in ship report.

## Acceptance criteria

- AC1: fresh lead session (post-pin-read) measured ≤6.5% of 1M. Method: sum of loaded-file bytes/4 vs before-table above, plus a live session screenshot of the context meter.
- AC2: every de-registered skill still discoverable — spot-check 5 random desk skills reachable via the skill-index pointer body.
- AC3: no other agent's picker loses a skill it had (diff each picker's registration before/after).
- AC4: zero rule-content loss — collapsed files carry pointers to every canonical process file previously restated.

## Gate plan

deputy-codex builds → codex cross-vendor gate (items 4+5 touch fleet-wide config = high-impact SOP class) → lead line-read + merge → next-session live measurement closes AC1.
