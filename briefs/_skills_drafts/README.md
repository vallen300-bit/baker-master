---
title: Desk SKILL.md drafts — staging area
status: V1 drafts, pattern-lock pending
authored: 2026-04-30 (AI Head A CLI)
---

# Desk SKILL.md drafts

Staging area for the 5 Cowork-side scoped Desk agents ratified 2026-04-30 (Director: Desk naming + Manus filesystem-as-memory + 6-class path whitelist).

## Pattern lock (in progress)

| Desk | Status | File | Matter slugs |
|---|---|---|---|
| AO Desk | **DRAFT V1 (canonical)** | `AO_DESK_SKILL.md` | `oskolkov` |
| MOVIE Desk | Not yet authored | `MOVIE_DESK_SKILL.md` | `mo-vie-am`, `mo-vie-exit` |
| Hagenauer Desk | Not yet authored | `HAGENAUER_DESK_SKILL.md` | `hagenauer-rg7` |
| Origination Desk | Not yet authored | `ORIGINATION_DESK_SKILL.md` | `nvidia-corinthia`, `kitz-kempinski`, `kitzbuhel-six-senses`, `wertheimer`, `balducci`, `philippe-soulier`, `mo-prague`, `citic`, `corinthia`, `cap-ferrat`, `bora-bora`, `minor-hotels` |
| Brisen Desk | Not yet authored | `BRISEN_DESK_SKILL.md` | (cross-cutting; portfolio view) |

**Authoring strategy:** AO Desk is drafted first as the canonical pattern. Sibling Desks follow the same 11-section structure with per-matter substitutions (slug, counterparty, sibling-Desk routing map, Brisen-specific facts). If Director approves AO Desk pattern, siblings author quickly. If pattern needs revision, fix once then duplicate.

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

## Sibling-Desk routing protocol

When a Desk discovers work in another Desk's lane: write a Tier A handoff file at `_inbox/handoff-<YYYY-MM-DD>-<src>-to-<tgt>.md` with frontmatter (`from`, `to`, `subject`, `priority`). Target Desk picks up at next session start.

NO direct cross-Desk writes. Lane discipline is the load-bearing invariant.

## Open questions for Director (pattern-lock review)

1. **Naming:** AO Desk reads as informal vs. "Oskolkov Desk" formal. Director ratified "AO Desk" 2026-04-30. Confirm AO/MOVIE/Hagenauer/Origination/Brisen all use the short / matter-keyword form?
2. **MOVIE Desk scope:** does one Desk own both `mo-vie-am` (asset management) and `mo-vie-exit` (disposal track)? Or split?
3. **Origination Desk breadth:** 12+ slug list above. Is this one Desk or should it split (e.g., hotel-chains vs. residences)?
4. **Brisen Desk responsibility:** is it a portfolio synthesizer (read-only across all matters) or does it write to its own `wiki/matters/brisen/` paths?
5. **Memory consolidation cadence:** OPERATING.md rewrite-each-session is clear; LONGTERM.md update cadence less so. Per-session updates? Weekly compaction?
6. **End-to-end test plan:** when Briefs 1+2 ship, do we want a dry-run pilot on AO Desk only (1 week) before activating other 4? Or activate all 5 simultaneously?

These don't block AO Desk pattern review — flagging now to capture intent before sibling authoring.
