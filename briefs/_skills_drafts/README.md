---
title: Desk SKILL.md drafts — staging area
status: V1 drafts, pattern-locked 2026-04-30
authored: 2026-04-30 (AI Head A CLI)
---

# Desk SKILL.md drafts

Staging area for the 5 Cowork-side scoped Desk agents ratified 2026-04-30 (Director: Desk naming + Manus filesystem-as-memory + 6-class path whitelist + ratification-based LONGTERM update rule).

## Pattern lock (closed 2026-04-30)

| Desk | Status | File | Matter slugs |
|---|---|---|---|
| AO Desk | **DRAFT V1 (canonical)** | `AO_DESK_SKILL.md` | `oskolkov` |
| MOVIE Desk | DRAFT V1 | `MOVIE_DESK_SKILL.md` | `mo-vie-am`, `mo-vie-exit` (one Desk owns both per Director ratification) |
| Hagenauer Desk | DRAFT V1 | `HAGENAUER_DESK_SKILL.md` | `hagenauer-rg7` |
| Origination Desk | DRAFT V1 | `ORIGINATION_DESK_SKILL.md` | `nvidia-corinthia`, `kitz-kempinski`, `kitzbuhel-six-senses`, `wertheimer`, `balducci`, `philippe-soulier`, `mo-prague`, `citic`, `corinthia`, `cap-ferrat`, `bora-bora`, `minor-hotels` (one Desk per Director ratification) |
| **Brisen Desk** (interim "AI CEO" rename rejected per Director EOD 2026-04-30) | DRAFT V1 | `BRISEN_DESK_SKILL.md` | `brisen` (NEW slug added via baker-vault PR #37, slugs.yml v17 — meta-matter, cross-cutting view) |

**Authoring strategy used:** AO Desk drafted first as the canonical pattern. Director ratified pattern + naming + scope decisions 2026-04-30; sibling Desks then authored in one batch with per-matter substitutions.

## Deployment dependency chain

These skills cannot be end-to-end functional until both:
1. **Brief 1 (`BAKER_VAULT_WRITE_1`)** ships — provides `mcp__baker__baker_vault_write` MCP tool that Desks use for Tier A + B writes.
2. **Brief 2 (`BAKER_VAULT_READ_WIKI_SCOPE_1`)** ships — extends `vault_mirror.py` read scope from `_ops/` only to `wiki/` (so Desks can read curated state + cortex-config).

Per V4 roadmap: Briefs 1+2 ship Mon-Wed week of 2026-05-04. Desk skill drafts authored ahead so deployment is zero-touch when Briefs 1+2 merge.

## Authority tier model (shared across all 5 Desks)

Per Director ratification 2026-04-30 + Brief 1 path whitelist:

| Tier | Paths | Action |
|---|---|---|
| **A — Auto-execute** | `wiki/matters/<slug>/_session-state.md`, `wiki/matters/<slug>/curated/<YYYY-MM-DD>-<topic>.md`, `_inbox/handoff-<date>-<src>-to-<tgt>.md`, `wiki/matters/<slug>/red-flags.md` | Desk writes directly, audit row to `baker_actions` |
| **B — Recommend + wait** | `wiki/matters/<slug>/proposed-gold.md`, `wiki/matters/<slug>/decisions/<YYYY-MM-DD>-<topic>.md` | Desk drafts, Director ratifies, then writes |
| **C — Never (hard-block)** | `gold.md`, `slugs.yml`, `_priorities.yml`, `_ops/`, `_install/`, `_cortex/*` | Refuse + escalate |

Frontmatter discipline: `curated/` and `proposed-gold.md` writes require `source` + `confidence` + `provenance` keys (Brief 1 server-enforced).

## Memory file architecture (shared)

Every Desk has 3 files at `_ops/agents/<desk-slug>/`:

- **`OPERATING.md`** — current state, <80 lines, rewrite-style. Mandatory read at session start.
- **`LONGTERM.md`** — stable reference, <200 lines, update-style. Mid-session lookup.
- **`ARCHIVE.md`** — append-only audit trail. Past-decision tracing.

Memory pattern adapted from AI Dennis (it-manager skill) — proven 3-file architecture.

### LONGTERM.md update cadence — ratification-based rule (Director-ratified 2026-04-30)

Update LONGTERM.md immediately when a fact is **ratified** by:
- **Director-ratified** — explicit Triaga / paste-block / inline confirmation
- **Counterparty-signed** — contract executed, email confirmation arrived, court order issued
- **Data-confirmed** — bank wire received, signed PDF in vault, audited number landed

Do NOT update LONGTERM.md for unratified observations, in-flight signals, single-source claims, or speculation. Those stay in OPERATING.md (current working state) or `curated/<date>-<topic>.md` (specific deliberations) until a ratification signal arrives. Per-Desk variations in §7.2 of each SKILL.md (Hagenauer Desk extends to "Thomas Leitner-ratified" for legal facts within his scope; Brisen Desk extends to "deal-closed-elsewhere = real comparable").

## Sibling-Desk routing protocol

When a Desk discovers work in another Desk's lane: write a Tier A handoff file at `_inbox/handoff-<YYYY-MM-DD>-<src>-to-<tgt>.md` with frontmatter (`from`, `to`, `subject`, `priority`). Target Desk picks up at next session start.

NO direct cross-Desk writes. Lane discipline is the load-bearing invariant.

## Director ratifications 2026-04-30 (pattern-lock answers)

1. **Naming:** ✅ AO Desk / MOVIE Desk / Hagenauer Desk / Origination Desk / **Brisen Desk** (interim "AI CEO" rename considered, rejected EOD 2026-04-30 — cosmetic churn).
2. **MOVIE Desk scope:** ✅ ONE Desk owns BOTH `mo-vie-am` + `mo-vie-exit`.
3. **Origination Desk breadth:** ✅ ONE Desk owns all 12+ slugs (no split).
4. **Brisen Desk write surface:** ✅ Own write surface at `wiki/matters/brisen/`. Slug `brisen` added to slugs.yml v17 as meta-matter (baker-vault PR #37).
5. **LONGTERM.md cadence:** ✅ Ratification-based rule (see above).
6. **Pilot strategy:** ✅ Activate ALL 5 simultaneously when Briefs 1+2 ship.

## Slugs.yml addition (shipped — baker-vault PR #37, slugs.yml v17)

```yaml
- slug: brisen
  status: active
  description: "Brisen Desk meta-matter — portfolio synthesizer scoped agent's own write surface. Cross-cutting; reads all matter Desks (AO / MOVIE / Hagenauer / Origination), writes only here. Synthesizes portfolio-level positions, arbitrates inter-Desk conflicts, supports Director's strategic decisions on capital allocation, portfolio reweighting, kill-criteria, and acquire-vs-walk. Does not write into other matter wikis (handoff via _inbox/ only)."
  aliases: ["brisen-desk", "ceo", "ai-ceo", "brisen-ceo"]
```

(Aliases include `ai-ceo` so any historical reference to the rejected interim name still resolves to canonical `brisen`.)

## Deployment checklist (when Briefs 1+2 ship)

1. **Pre-ship:** ✅ add `brisen` slug to baker-vault `slugs.yml` (baker-vault PR #37 — open at draft-time, slugs.yml v17).
2. **Pre-ship:** create empty seed memory files `_ops/agents/{ao,movie,hagenauer,origination,brisen}-desk/{OPERATING,LONGTERM,ARCHIVE}.md` with frontmatter (Tier A path; can be Director-seeded or initial-Desk-seeded).
3. **Ship Brief 1 (vault_write MCP).**
4. **Ship Brief 2 (read scope wiki/).**
5. **Copy each `briefs/_skills_drafts/<DESK>_SKILL.md` → `~/.claude/skills/<desk-slug>/SKILL.md`** (Brisen Desk lands at `~/.claude/skills/brisen-desk/SKILL.md`).
6. **Validate:** open a Cowork session per Desk, verify session-start briefing renders correctly + memory reads work via `mcp__baker__baker_vault_read`.
7. **Pilot week:** all 5 Desks active; observe friction patterns; revise per practice.
