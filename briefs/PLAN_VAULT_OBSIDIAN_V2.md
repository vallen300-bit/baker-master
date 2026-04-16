# Plan: Baker Vault — Karpathy Vertical + CEO Horizontal

**Version:** 2.1 (12 amendments: 9 Cowork + 3 claude-obsidian patterns)
**Status:** For Director approval
**Effort:** 40-50h (revised down from 56-78h)

---

## Context

Knowledge scattered across 10+ locations. Director loses documents, has orphan files, can't find contracts. Baker processes signals but has no unified knowledge store.

**The fix:** One Obsidian vault on Mac Mini. Karpathy's three-layer vertical (raw/wiki/schema) as top-level. CEO's horizontal (matters/people/entities/research) inside the wiki layer. Same vault, two lenses.

**Architecture references:**
- `briefs/ARCHITECTURE_THREE_TIER_DRAFT.md` — 24 locked decisions
- Karpathy LLM Wiki gist — raw/wiki/schema three-layer pattern
- `claude-obsidian` by AgriciDaniel — hot cache, 8-category lint, session hooks
- `outputs/RESEARCH_DOMAIN_SLM_PERSISTENT_INFERENCE.md` — confidence scoring, forgetting curves

---

## Vault Structure

```
baker-vault/                              Git root, Mac Mini: ~/baker-vault
│
├── raw/                                  KARPATHY LAYER 1 — Immutable originals
│   │                                     A document lives here ONCE. Wiki pages link to it.
│   │                                     NEW INTAKE only. Dropbox stays as archive for existing.
│   ├── contracts/
│   ├── financials/
│   ├── correspondence/
│   ├── transcripts/
│   ├── filings/
│   ├── media/
│   └── clippings/                       Director browser clips (bookmarklet → Baker API)
│
├── wiki/                                 KARPATHY LAYER 2 — Synthesized knowledge
│   │                                     CEO HORIZONTAL lives here. Agents read this first.
│   │
│   ├── hot.md                            Hot cache — read FIRST every session
│   ├── index.md                          Master catalog of all wiki pages
│   ├── log.md                            Append-only chronological audit trail
│   ├── _inbox/                           Unrouted items (low-confidence routing)
│   │
│   ├── matters/                          HORIZONTAL: deals, projects, disputes
│   │   ├── _index.md                     All matters with status + last-touched
│   │   │                                 (includes dormant matters as rows → Dropbox archive)
│   │   ├── oskolkov/                     ACTIVE — has real content
│   │   │   ├── _index.md                 Matter sub-index
│   │   │   ├── _overview.md              Status, threads, links to raw/ + Dropbox
│   │   │   ├── agenda.md
│   │   │   ├── psychology.md
│   │   │   ├── communication-rules.md
│   │   │   ├── financing-to-completion.md
│   │   │   ├── sensitive-issues.md
│   │   │   ├── investment-channels.md
│   │   │   ├── cards/                    Enriched analysis (timestamped)
│   │   │   └── decisions/                Decision log
│   │   ├── movie/                        ACTIVE
│   │   ├── hagenauer/                    ACTIVE
│   │   ├── cupial/                       ACTIVE
│   │   ├── morv/                         ACTIVE
│   │   ├── lilienmatt/                   ACTIVE
│   │   └── ... (8-12 active matters ONLY — not 28)
│   │
│   ├── people/                           HORIZONTAL: VIP profiles
│   │   ├── _index.md
│   │   └── ... (~80 pages: Tier 1+2 + role_context)
│   │
│   ├── entities/                         HORIZONTAL: companies, funds, SPVs
│   │   ├── _index.md
│   │   └── ... (~15-20 entities)
│   │
│   └── research/                         HORIZONTAL: analysis, market intel
│       ├── _index.md
│       └── ... (~20 research reports)
│
├── schema/                               KARPATHY LAYER 3 — Templates ONLY
│   │                                     NO runtime config. Templates + rules only.
│   │                                     Runtime config stays in PostgreSQL.
│   ├── VAULT.md                          Vault-wide rules, conventions, link format
│   ├── templates/                        Page templates
│   │   ├── matter-template.md
│   │   ├── person-template.md
│   │   ├── entity-template.md
│   │   ├── card-template.md
│   │   ├── decision-template.md
│   │   └── source-summary-template.md   Every raw/ doc gets a wiki summary
│   ├── agents/                           Specialist PROMPT templates (not runtime config)
│   │   ├── specialist-ao.md
│   │   ├── specialist-movie-am.md
│   │   └── specialist-hagenauer.md
│   └── sync/                             Sync state + routing log
│       └── routing-log.md                Audit trail of all auto-routing decisions
│
└── .obsidian/                            Obsidian config
    ├── plugins/obsidian-git/             15-min auto-commit
    └── snippets/vault-colors.css         Color-code by page type
```

---

## Three-Layer Mapping

| Karpathy Layer | Baker Location | What Lives There |
|---|---|---|
| **raw/** | `raw/contracts/`, `raw/financials/`, etc. | Immutable originals. One copy each. New intake only. Existing stay in Dropbox. |
| **wiki/** | `wiki/matters/`, `wiki/people/`, `wiki/entities/`, `wiki/research/` | Synthesized knowledge. CEO horizontal. Agents read this first. |
| **schema/** | `schema/templates/`, `schema/agents/` | Templates + prompt templates ONLY. No runtime config. |

### Changes from Karpathy Default → Baker

| Layer | Karpathy Default | Baker Change |
|---|---|---|
| **raw/** | articles/, papers/, repos/ | contracts/, financials/, filings/, correspondence/, transcripts/, media/ |
| **wiki/** | concepts/, entities/, sources/ | matters/, people/, entities/, research/ (CEO mental model) |
| **schema/** | Just CLAUDE.md | + templates/, agents/ (prompt templates), sync/ (routing log) |

---

## Amendments from Cowork Review

### Amendment 1: Active matters only — no empty skeletons

**Only create folders for matters with activity in last 30 days** (8-12 matters). Dormant matters get a single row in `wiki/matters/_index.md` pointing to their Dropbox archive path.

**Rule:** No empty folders. No stub pages. A folder exists when it has real content.

### Amendment 2: Explicit MacBook write policy

**MacBook writes allowed with discipline:**
- `git pull --rebase` before every Tier 3 session
- `git push` after session ends
- Pre-commit hook: blocks push if Mac Mini has newer commits on the SAME FILE
- Conflict policy: Mac Mini wins on auto-resolvable. Halt + WhatsApp Director on true conflict.

### Amendment 3: Routing confidence + _inbox/

- Every routing decision carries a confidence score (0.0-1.0)
- Routes below 0.7 → `wiki/_inbox/` for human review, NOT into a random matter
- ALL routing decisions logged to `schema/sync/routing-log.md`
- Weekly review of _inbox/ items and routing-log misses

### Amendment 4: Phase 4 deferred — Dropbox stays as raw archive

**Dropbox stays as source for existing originals.** Vault `raw/` is for new intake only. Wiki pages can link to either location. Replace Phase 4 with Phase 3.5 observation period.

### Amendment 5: Concurrency safety in Phase 3

- File locking around vault writer daemon (`fcntl.flock()`)
- Atomic writes: write to `.tmp`, then `os.rename()` to final path
- Conflict policy: Mac Mini wins auto-resolvable, halt + WhatsApp Director on conflict

### Amendment 6: schema/ is templates only — no runtime config

schema/ contains templates and prompt templates ONLY. Feature flags stay in `cortex_config` PG table. API keys in env vars. Runtime agent state in PostgreSQL. One source of truth per item.

### Amendment 7: Confidence field wired to decay

Include `confidence: high|medium|low` in frontmatter. Wire Ebbinghaus decay into Phase 3 nightly consolidation (`e^(-t/stability)`, stability increases on access). A stale `confidence: high` from January is worse than no field — so decay is mandatory, not optional.

### Amendment 8: wiki_pages consumer audit before Phase 3

Before flipping `wiki_pages` to read cache: grep codebase for all readers/writers. Any Tier 1 agent that writes to `wiki_pages` → rewire to `wiki_staging`. Prerequisite for Phase 3.

### Amendment 9: Dry-run before Phase 2 cross-links

Run link generator against vault COPY first. Script verifies all `[[links]]` resolve. Flag pages with >50 outbound links. Only then run against live vault.

### Amendment 10: Source summaries as first-class pages (Karpathy pattern)

Every document ingested into `raw/` MUST have a companion summary page in `wiki/`. The raw file is the immutable original; the summary is the wiki entry with key takeaways, entities mentioned, cross-links. Template: `schema/templates/source-summary-template.md`. This is how agents discover documents — they read the summary, not the raw PDF.

### Amendment 11: Contradiction callouts (claude-obsidian lint pattern)

When lint or any agent finds conflicting data between pages, insert Obsidian's native callout:
```
> [!contradiction]
> This page says AO's share is EUR 6.9M but [[financing-to-completion]]
> says EUR 6.0M. Needs Director resolution.
```
Renders as colored warning box. Searchable via `grep "[!contradiction]"`. Never silently overwrite — flag and wait for Director.

### Amendment 12: 8-category vault lint (expanded from 4)

Replace our 4-category lint with full 8-category suite:
1. Orphan pages (no incoming links)
2. Dead links (references to non-existent pages)
3. Gap detection (missing cross-references between related matters)
4. Stale claims / contradictions (insert `[!contradiction]` callouts)
5. Source attribution (facts not linked to a source in `raw/` or Dropbox)
6. Title consistency (duplicate or ambiguous page names)
7. Index coherence (`index.md` catalog vs actual vault files)
8. Graph fragmentation (disconnected clusters in the link graph)

Runs nightly in Phase 3 consolidation job.

---

## Page Frontmatter Standard

```yaml
---
title: Page Title
type: matter | person | entity | card | decision | research | source_summary
confidence: high | medium | low
sources:
  - "[[raw/contracts/participation-agreement.pdf]]"
  - "email from AO 2026-04-13"
  - "Dropbox: Baker-Project/01_Projects/Oskolkov/03_Source_Of_Truth/"
related:
  - "[[wiki/matters/oskolkov/_overview]]"
  - "[[wiki/people/andrey-oskolkov]]"
created: 2026-04-14
updated: 2026-04-14
updated_by: seed_migration | vault_daemon | director
---
```

### Context Loading Hierarchy (agents follow this order)

1. Read `wiki/hot.md` — what's happening NOW
2. Read `wiki/index.md` — what exists in the vault
3. Read `wiki/matters/{matter}/_index.md` — matter sub-index
4. Read specific pages as needed

---

## Implementation Phases

### Phase 1: Schema First + Real Content (8-10h)

**Schema first, then migrate into it.**

1. Create `~/baker-vault/` on Mac Mini with directory tree
2. `git init`, private GitHub repo, `.gitignore`
3. **Write schema/VAULT.md** — vault rules, link conventions, frontmatter spec
4. **Write all templates** in `schema/templates/`
5. **Write agent prompt templates** in `schema/agents/`
6. Migrate `data/ao_pm/*.md` → `wiki/matters/oskolkov/` (7 files + frontmatter per template)
7. Migrate `data/movie_am/*.md` → `wiki/matters/movie/` (6 files + frontmatter)
8. Write `_overview.md` for both matters with `[[links]]`
9. Migrate ~20 research .md files from `outputs/` → `wiki/research/`
10. Create `wiki/matters/_index.md` — 8-12 active matters with folders, rest as Dropbox pointers
11. Create matter folders ONLY for active matters with real content
12. Write `wiki/hot.md`, `wiki/index.md`, `wiki/log.md`
13. Install Obsidian on Mac Mini, open vault, install Obsidian Git plugin (15-min auto-commit)
14. First commit + push

**Exit:** 50+ files. Schema templates exist FIRST. Two fully-populated matters. Active matter folders have real content. No empty skeletons.

### Phase 2: People + Entities + Cross-Links (10-14h)

1. **Audit wiki_pages consumers** — grep codebase, list all readers/writers
2. Script generates ~80 people pages from VIP contacts
3. Script generates ~15-20 entity pages
4. **DRY-RUN:** Run cross-link generator against vault copy, verify all links resolve
5. Add `[[wiki links]]` cross-references to all matter `_overview.md`
6. Export top decisions per active matter → `decisions/`
7. Export ~20 key deep analyses as cards → `cards/`
8. Link key Dropbox documents from matter overviews (links to Dropbox paths, NOT copied)

**Exit:** 80+ people pages, 15+ entity pages, cross-links verified. Graph view shows clusters.

### Phase 3: Baker Write Pipeline + Concurrency (18-22h)

1. **Rewire wiki_pages writers** → write to `wiki_staging` instead (prerequisite from Phase 2 audit)
2. `wiki_staging` PostgreSQL table
3. Vault writer daemon on Mac Mini (15-min cron):
   - File locking (`fcntl.flock()`)
   - Routes with confidence score; <0.7 → `wiki/_inbox/`
   - Logs ALL routing decisions to `schema/sync/routing-log.md`
   - Atomic writes (`.tmp` → `os.rename()`)
4. Vault → PG one-way sync (`wiki_pages` becomes read cache)
5. Card writer: enriched analysis → `wiki/matters/{matter}/cards/`
6. `wiki/hot.md` auto-update after each signal processing cycle
7. **Nightly consolidation** (02:00 UTC):
   - Cluster cortex_events → update wiki pages
   - Decay confidence on untouched pages (Ebbinghaus)
   - Flag contradictions with `[!contradiction]` callouts
   - Push to remote
8. MacBook pre-commit hook
9. Conflict policy: Mac Mini wins auto-resolvable, halt + WhatsApp on conflict

**Exit:** New knowledge auto-files. _inbox/ catches low-confidence routing. Routing log auditable. Confidence decays.

### Phase 3.5: Observation + Course Correct (4h, after 2 weeks of Phase 3)

1. Review `schema/sync/routing-log.md` — routing accuracy
2. Review `wiki/_inbox/` — what's stuck?
3. Review confidence decay — appropriate?
4. Review MacBook write conflicts — how many?
5. **Decide:** What from Dropbox is worth migrating to `raw/`?

**Exit:** Data-driven decision on any Dropbox migration. Routing accuracy measured.

---

## What Stays Outside the Vault

| Location | What | Why |
|---|---|---|
| `baker-code` git repo | Code, briefs, docs-site HTML | Engineering artifacts |
| PostgreSQL | Emails, WhatsApp, meetings, feature flags, runtime config | Operational data + config |
| Qdrant | Vector embeddings | Search infrastructure |
| Render | Dashboard, API | Tier 1 delivery |
| Dropbox | Existing originals (contracts, filings, financials) | Layer 1 archive — link, don't copy |

---

## Sync Architecture

```
Tier 1 (Render)           Tier 2 (Mac Mini)              Tier 3 (MacBook)
──────────────────        ───────────────────             ─────────────────
wiki_staging (PG)  ───→   cron daemon (locked)       ←── git pull --rebase
signal_queue (PG)  ───→   routes w/ confidence            Director writes
                          writes to wiki/ + raw/           git push (hooked)
                          vault → wiki_pages (PG)          Pre-commit: block if
                          15-min auto-commit               Mini has newer on
                          Nightly push 02:00 UTC           same file
```

---

## Effort Summary

| Phase | Description | Hours | Dependencies |
|---|---|---|---|
| 1 | Schema first + real content | 8-10h | None |
| 2 | People + entities + cross-links | 10-14h | Phase 1 |
| 3 | Baker write pipeline + concurrency | 18-22h | Phase 1, mostly Phase 2 |
| 3.5 | Observation + course correct | 4h | Phase 3 running 2 weeks |
| **Total** | | **40-50h** | |

Phase 4 (Dropbox bulk migration) **deferred** — data-driven after Phase 3.5.

---

## Verification

**After Phase 1:**
- `ssh macmini "ls ~/baker-vault/wiki/matters/"` → 8-12 active matter folders
- `ssh macmini "cat ~/baker-vault/schema/templates/matter-template.md"` → template exists FIRST
- `ssh macmini "cat ~/baker-vault/wiki/matters/oskolkov/_overview.md"` → follows template
- Obsidian open, graph view shows connected pages

**After Phase 2:**
- Dry-run link check: 0 broken links
- `ssh macmini "ls ~/baker-vault/wiki/people/ | wc -l"` → ~80
- Graph view: clusters per matter, bridged by shared people

**After Phase 3:**
- Send test email → routed correctly or in _inbox/ with logged reason
- `cat schema/sync/routing-log.md` → confidence scores visible
- `wiki_pages` PG cache populated
- Confidence field on untouched page → decayed after 7 days

**After Phase 3.5:**
- Routing accuracy >85%
- _inbox/ queue < 10 items
- Zero unresolved git conflicts
