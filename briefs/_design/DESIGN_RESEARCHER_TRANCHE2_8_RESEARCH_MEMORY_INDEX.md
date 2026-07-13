---
title: DESIGN — Researcher Tranche-2 #8 Research memory / index
item: "#8 (researcher-capability-extension-brief @22ab300)"
author: b2
date: 2026-07-12
status: DESIGN — for lead review BEFORE build (design-first per lead #9721; no codex, seats suspended #9711)
dispatch: lead #9721 (Director parallelism order) + #9894 (priority-now) ; inputs b1 store-landscape handoff (#9726/#9728)
discipline: design-first -> lead review -> build in vault worktree -> lead+deputy Claude review -> lead merge · no self-merge
---

# #8 Research memory / index — DESIGN (pre-build, for lead review)

## 1. Problem

The researcher re-runs findings cold. 60 reports sit in `wiki/research/`, but there is
**no queryable prior-report surface**: the only index, `wiki/research/_index.md`, was
seed-written once (`updated: 2026-04-14`, `updated_by: seed_migration`) and covers only the
April NVIDIA/Corinthia cluster. 55+ reports since April are invisible to it. So each brief
starts from zero instead of compounding on prior work — the exact "findings should compound"
gap item #8 names.

Goal: a **searchable, always-fresh index of prior research** the researcher can query at
Step 0 of any brief to find and reuse relevant priors, entirely within its existing cages.

## 2. Hard constraints (the cages decide the architecture)

These are not preferences — they eliminate two of the three options outright:

- **Write-cage** (`researcher_write_cage.sh`): a PreToolUse hook on `Write|Edit|MultiEdit`
  ONLY (lines 86-89). Writes are allowed only under `wiki/research/**` + the session-memory
  dir. **It does NOT see bash-spawned writes** — a `bash` command that writes a file is not a
  Write/Edit tool call, so this hook never fires on it. (This directly answers b1's cage-gotcha
  in #9728: bash-spawned writes are gated by the *bash* cage, not the write cage.)
- **Bash-cage** (`researcher_bash_cage.sh`): raw `curl`/`python`/`sed -i`/arbitrary `git`
  are DENIED; only **exact-canonical-path vetted scripts** run (e.g. `research_commit.sh`,
  `check_inbox.sh`, `bus_post.sh`). A new script the researcher runs must be added to the
  `IS_VETTED` case by an **additive lead PR** to the cage.
- **Tool-cage**: no send/write MCP verbs; **Baker WRITE / ingest is DENIED**. Researcher's
  only structured-search read today is `baker_search` (Postgres FTS, read-only). **Qdrant is
  not readable** by the researcher.

Net: any store the researcher must *populate* has to be reachable through `wiki/research/**`
(Write tool) or a vetted bash script — nothing else.

## 3. Options (surfaced, not averaged)

| Option | Store | Populate path | Verdict |
|---|---|---|---|
| **A — New dedicated store** | New Postgres table + Qdrant collection, semantic search | Needs a Baker-DB ingest write — **tool-cage DENIES it**; researcher can't read Qdrant either | **REJECT** — cage-blocked both ways; heavy infra for a 60-doc corpus |
| **C — Reuse Baker memory / `baker_search`** | Existing Baker Postgres FTS | Ingesting the 60 reports needs a Baker-DB write the researcher CANNOT make; would need a trusted-actor ingest job + pollutes the production matter store with research-doc rows/slugs | **DEFER** — viable only as a later trusted-actor pipeline; not researcher-buildable now |
| **B — Vault-wiki JSON manifest + regen + grep/jq** (b1's rec) | `wiki/research/_index.json` in the vault | Regen script parses each report's frontmatter → manifest; both the manifest path (under `wiki/research/`) and a vetted bash script are in-cage | **RECOMMEND** — fully in-cage, zero new infra, deterministic, compounds |

**Recommendation: Option B.** It is the only option the researcher can build and operate
inside its own cages, it needs no new infrastructure, and it directly reuses the surface the
researcher already writes to. Semantic search (Option A/C's only real advantage) is not worth
its cage-cost at 60 docs with structured frontmatter; revisit if the corpus crosses a few
hundred reports (see Q3).

## 4. Design — Option B

### 4.1 Manifest — `wiki/research/_index.json` (machine source of truth)
One record per `wiki/research/*.md` (excluding `_index.*`):
```json
{
  "generated": "2026-07-12T21:40:00Z",
  "count": 60,
  "reports": [
    {
      "path": "wiki/research/2026-05-02-multi-agent-fleet-architectures.md",
      "title": "Multi-agent fleet architectures — survey for Brisen Lab V2",
      "date": "2026-05-02",
      "author": "AI Head B (deputy)",
      "type": "research",
      "tags": ["brisen-lab", "multi-agent"],
      "summary": "<first ## summary line or frontmatter purpose, ≤240 chars>",
      "mtime": "2026-05-02T...",
      "flags": []
    }
  ]
}
```
- **Heterogeneous frontmatter is the norm** (58/60 have YAML; fields vary: some `title/date/author`,
  some `type/purpose/brief_from`). Extraction is **best-effort per field**, never all-or-nothing.
- **Fail-loud, not silent-drop**: the 2 reports with no frontmatter (and any malformed YAML) are
  STILL indexed (path + mtime + derived title from filename) with `flags:["no-frontmatter"]` —
  surfaced in the regen summary, never dropped. (Mirrors #12's stale-not-dropped rule.)
- Deterministic ordering: `date` desc, then `path` — so regen produces a clean, reviewable diff.

### 4.2 Regen script — `scripts/regen_research_index.sh` (baker-master; vetted, in-cage write)
- Scans `$BAKER_VAULT_PATH/wiki/research/*.md`, parses frontmatter, emits `_index.json`
  (+ optionally a regenerated human `_index.md` view — see Q2). No env-driven output path,
  no arg-driven config (same hardening as #12).
- Idempotent: re-running with no report changes produces a byte-identical manifest (modulo the
  `generated` stamp — or omit the stamp from the diff-critical body and keep it in a sidecar).
- Writes `_index.json` under `wiki/research/` → **in-cage** for both the Write tool AND a vetted
  bash script. Needs an additive `IS_VETTED` entry (exact path) so the researcher can invoke it.

### 4.3 Query reader — `scripts/search_research_index.sh` (vetted, READ-ONLY)
- `search_research_index.sh <keyword...>` → `jq`/`grep` over `_index.json`, returns matching
  `path + date + title + summary` (so the researcher opens only relevant priors, not cold-reruns).
- READ-ONLY: no writes, no ack, no arg-driven exec — same posture as `check_source_monitors.sh`
  / `read_message.sh`. Additive `IS_VETTED` exact-path entry.

### 4.4 Freshness — who regenerates
Recommend **both** (backstop pattern):
1. **Researcher-on-ship**: after writing a new report to `wiki/research/`, the researcher runs
   `regen_research_index.sh` (one more in-cage vetted-bash step) so the index is never stale by
   more than one report.
2. **Trusted-actor weekly sweep** (Mac-Mini launchd, mirror edge-scout) as a backstop if a ship
   skips regen. `generated` timestamp in the manifest is the staleness signal.

### 4.5 Cage wiring (additive, read-only — route via lead PR, no self-ship)
- `researcher_bash_cage.sh`: two additive `IS_VETTED` exact-path entries (regen + search).
- `researcher_write_cage.sh`: **no change** — `_index.json` is already under `wiki/research/`.
- Honest framing (per #12 codex F2): this is an **additive** cage amendment, not "cages untouched."

## 5. Open decisions for lead (pick one each — my recommendation attached)

1. **Regen ownership** — researcher-on-ship / trusted-actor-sweep / both. *Rec: both (§4.4).*
2. **`_index.md`** — regenerate the human Obsidian view from the manifest, or deprecate it?
   Surface-conflict rule says one source of truth. *Rec: `_index.json` canonical; regen also
   emits `_index.md` as a generated human view (single SoT, keeps Obsidian links).*
3. **Semantic search** — build now or defer? *Rec: defer; keyword + frontmatter is sufficient at
   60 docs; revisit at ~300 reports or when a trusted-actor `baker_search` ingest (Option C) is
   cheap.*

## 6. Build plan (after lead clears this design)
- New branch `b2/researcher-research-memory-index` (baker-master) for the 2 scripts + tests.
- Vault worktree branch for the cage amendment (IS_VETTED entries) + regenerated `_index.json`/`_index.md`.
- Tests: heterogeneous-frontmatter parse; no-frontmatter flagged-not-dropped; deterministic
  ordering / idempotent regen; search returns correct subset; empty-corpus clean.
- Rails: lead+deputy Claude-side review (codex suspended #9711) → lead merges → optional Mini
  launchd for the weekly sweep. No self-merge.

## 7. Cross-links
- Source brief: `wiki/research/2026-07-12-researcher-capability-extension-brief.md` @22ab300 (item #8).
- b1 store-landscape handoff #9726/#9728 (Option B origin; cage-gotcha now resolved §2).
- Prior-art patterns: `research-monitors-prefetch.sh` (f27da57, vetted trusted-actor + worktree),
  `check_source_monitors.sh` (vetted read-only reader), `research_commit.sh` (in-cage git write).
