# BRIEF — MATTER_KNOWLEDGE_CURATION_PATTERN_1

**Owner:** Director-ratified pattern (2026-04-30 priority pivot)
**Author:** AI Head A (App)
**Drafted:** 2026-04-30
**Priority:** CRITICAL (priority pivot — "matters knowledge + obsidian first, channels last")
**Roadmap item:** `matter-knowledge-curation-pattern` (V4 queued, NEW)

## Background

Director 2026-04-30 priority stack:
1. Matter knowledge
2. Obsidian (vault structure)
3. Learning loop
4. Analysis + reasoning
5. ~~Channel comms~~ → LAST stage

**Cortex's reasoning quality is bounded by its matter knowledge.** Today most matters in `wiki/matters/<slug>/` have only `cortex-config.md` (the matter's posture + rules) — a few dozen lines of meta. The actual knowledge of the matter (history, parties, money flows, disputes, decisions, deadlines, contracts) lives scattered across emails, files, meetings, financial data — all in raw signals (Layer 3) and unstructured Dropbox files.

Cortex Phase 2 reads `wiki/matters/<slug>/curated/*.md` (the distilled knowledge layer) when reasoning. If `curated/` is empty, Cortex reasons from raw signals — slow, expensive, error-prone.

**Filling `curated/` with high-signal distilled markdown is THE production blocker for reasoning quality.**

## Goal

Formalize the per-matter `curated/` folder structure + authoring methodology so AI Head 2 App, B-codes, and the Director can all contribute knowledge consistently.

## Canonical structure

For every matter at `baker-vault/wiki/matters/<slug>/curated/`:

```
curated/
├── 00_overview.md           # 1-page matter summary; what it is, what we want, what's at stake
├── 01_parties.md            # Counterparties, advisors, internal team, contact points
├── 02_money.md              # Financial structure, flows, exposure, fees, equity %
├── 03_timeline.md           # Date-ordered history: contracts, payments, disputes, milestones
├── 04_documents.md          # Pointers to canonical source docs in Dropbox / files; NOT duplicated
├── 05_disputes_open.md      # Active legal/commercial disputes; positions, deadlines
├── 06_decisions_log.md      # Director ratifications + reasoning for past path-choices
├── 07_open_questions.md     # What we still don't know / haven't decided
└── 99_scratchpad.md         # Free-form notes; promoted-to-canonical when relevant
```

**Not every matter needs every file.** Skip empty ones — don't create stubs. A small, lean matter (e.g. brisen-pr) might need only `00_overview.md` + `01_parties.md`. A heavy matter (hagenauer-rg7, oskolkov) needs all 9.

## Authoring methodology

### For AI Head 2 App / B-codes

Source priority order (highest signal first):
1. **Existing baker-vault content**: `wiki/matters/<slug>/`, `_ops/`, related Brisen Vienna server data via `mcp__26f35be0-*__search_files`.
2. **Recent meetings**: `mcp__67251563-*__fireflies_search` filtered by matter keywords.
3. **Recent emails**: Baker MCP `baker_search` with matter keywords.
4. **WhatsApp**: same query against WAHA-ingested messages.
5. **Existing skills/dashboards**: `_02_DASHBOARDS/`, the `rg7-hagenauer-final-account` skill, etc. — these are already-distilled knowledge, lift directly.
6. **Counterparty profiles**: `memory/people/` files in baker-vault.

Quality bar:
- **Each section: ≤ 80 lines max.** Short, dense, scannable.
- **Lead with bottom line, then evidence.** Director's preference.
- **Cite source for non-obvious facts**: `[meeting 2026-04-15]`, `[email AO 2026-04-22]`, `[contract clause 4.2]`. Future learning loop will use these to detect drift.
- **Use canonical slugs throughout.** No PM-era labels (no `Hagenauer`, no `movie_am`).
- **No fabrication.** If something's unknown, write `[?] need to confirm` — surfaces in `07_open_questions.md`.

### Frontmatter (every file)

```yaml
---
matter: <canonical-slug>
file_role: curated
section: <00_overview | 01_parties | etc>
last_curated_by: <ai-head-2-app | b1 | b2 | b3 | b4 | director>
last_curated_at: <YYYY-MM-DD>
ignore_by_pipeline: false   # curated content IS read by Cortex Phase 2
---
```

`ignore_by_pipeline: false` — these files are intentionally part of Cortex's reading scope.

## Verification (per-matter close)

Before marking a matter's curation "first pass done":
1. `00_overview.md` exists and reads cleanly cold.
2. At least one of `01_parties.md` / `02_money.md` / `03_timeline.md` is populated with > 20 lines.
3. Frontmatter present + correct.
4. Manual cortex cycle on the matter produces measurably better reasoning vs pre-curation (qualitative — Director or AI Head A judgment).

## Tonight's anchor scope

| Matter | Curator | Sections (priority order) |
|---|---|---|
| **hagenauer-rg7** | AI Head 2 App | 00_overview, 03_timeline, 05_disputes_open, 02_money — has rich source material in 14_HAGENAUER_MASTER + the rg7-hagenauer-final-account skill |
| **mo-vie-am** | B2 (idle) | 00_overview, 01_parties, 04_documents — start small, MOHG operator structure + key contacts |

NOT tonight (defer):
- Other 20-29 matters (queue for tomorrow + ongoing)
- Promotion to global ratified knowledge (drift detector wires up later)

## Done definition (this brief)

- This pattern doc lives at `baker-vault/_ops/processes/matter-knowledge-curation-pattern.md` (promote on merge).
- 2 anchor matters (hagenauer-rg7, mo-vie-am) have at minimum `00_overview.md` + 2 other sections each, by end of session tonight.
- AI Head A spot-reviews each curated/ folder + paste-block to Director with summary of what was distilled + any gaps surfaced.

## Trigger-class

Vault data writes (read-only for Cortex; not code path). Non-trigger-class for code-review purposes. AI Head A spot-reviews content quality + completeness — no second-pair-of-eyes required.
