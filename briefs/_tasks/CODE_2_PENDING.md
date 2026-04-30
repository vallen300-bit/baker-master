# CODE_2 — PENDING (mo-vie-am curated knowledge — MATTER_KNOWLEDGE_CURATION_PATTERN_1)

**Status:** PENDING — dispatched 2026-04-30 by AI Head A (App)
**Pattern brief:** `briefs/BRIEF_MATTER_KNOWLEDGE_CURATION_PATTERN_1.md`
**Builder:** B2
**Priority:** CRITICAL (Director priority pivot 2026-04-30 — matter knowledge first)
**ETA:** end of session tonight (start small, ship a usable scaffold)

## Task summary

Author distilled knowledge for the **mo-vie-am** (Mandarin Oriental Vienna — Asset Management) matter at `baker-vault/wiki/matters/mo-vie-am/curated/`.

Read `briefs/BRIEF_MATTER_KNOWLEDGE_CURATION_PATTERN_1.md` for full pattern + canonical structure + frontmatter format + source priority order.

## Tonight's scope (3 sections, NOT all 9)

| File | Content |
|---|---|
| `00_overview.md` | 1-page summary: what mo-vie-am is, ownership structure (LCG SA → RG7 GmbH → MOVIE asset), MOHG operator role, Brisengroup CEO oversight stake, what's at stake (asset value, exit option, hotel ops quality) |
| `01_parties.md` | Anna Egger, Katja Graf, Mario Habicher, Christoph Schauer (MOHG); Robert Lyle (PRCO); contacts at TPA, Eastdeal (Laura Wenk for exit), bank counterparties; internal Brisen team (Director, Edita, Mykola/Nikolai) |
| `04_documents.md` | Pointers to canonical source docs in baker-vault + Dropbox (don't duplicate content; just paths + 1-line "this is X"). Operator agreement, performance reports, sales brochures, residence inventory. |

Skip the other 6 sections this session — pattern doc says lean over comprehensive on first pass.

## Dispatch

```
git checkout main && git pull --ff-only origin main
git checkout -b b2/mo-vie-am-curated-knowledge
mkdir -p ~/baker-vault/wiki/matters/mo-vie-am/curated
# author 3 .md files per the pattern brief
git -C ~/baker-vault add wiki/matters/mo-vie-am/curated/
git -C ~/baker-vault commit -m "matter(mo-vie-am): curated knowledge first pass (00, 01, 04)"
# push to baker-vault on a b2/ branch + open PR
```

## Quality bar reminders

- ≤ 80 lines per file. Dense. Bottom line first.
- Cite sources for non-obvious facts: `[meeting 2026-04-15]`, `[email AO 2026-04-22]`.
- Canonical slugs only (`mo-vie-am`, never `movie_am` / `movie-am` / `MO Vienna`).
- `[?] need to confirm` for unknowns — don't fabricate.
- Frontmatter on every file (see pattern brief).

## Source priority hints for mo-vie-am

1. baker-vault: existing `wiki/matters/mo-vie-am/cortex-config.md` for posture/rules.
2. Dropbox `1_ACTIVE_PROJECTS/MOVIE/`, `_02_DASHBOARDS/`, `12_PRIVATE_RE_ASSETS/` — canonical source docs.
3. Recent MOHG meetings via fireflies_search.
4. Sent emails to / from MOHG addresses (kgraf@mohg.com, mhabicher@mohg.com, etc.) via baker_search.
5. `memory/people/` files for Anna Egger / Katja Graf / Mario Habicher.

## Verdict + handoff

Surface paste-block back to AI Head A when curated/ folder is committed: list files written + line counts + any source gaps surfaced (`[?] need to confirm` items).

## Previous task (closed)

PR #114 (ROADMAP_DRIFT_CLICKUP_SENTINEL_1) merged 2026-04-30 — daily 06:00 UTC drift sentinel live.
