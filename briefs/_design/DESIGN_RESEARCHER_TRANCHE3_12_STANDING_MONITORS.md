---
title: DESIGN — Researcher Tranche-3 #12 Standing source monitors
item: "#12 (researcher-capability-extension-brief @22ab300)"
author: b2
date: 2026-07-12
status: DESIGN CLEARED (codex #9394 CHANGES incorporated) — building to this spec
dispatch: deputy #9337 (Director order via lead #9334)
discipline: additive read-only cage amendment (NOT "untouched" — codex F2) · design-verified with codex · build -> codex build-gate -> lead merge · no self-merge
---

> **CODEX DESIGN-VERIFY (#9394) — LOCKED DECISIONS incorporated below:**
> - **F1 MED:** ship an EXPLICIT weekly digest trigger/owner (cron fires
>   `check_source_monitors.sh` → `wiki/research/YYYY-MM-DD-research-monitors-weekly.md`),
>   mirroring edge-scout's cron+invocation — not just a cache reader. (§4/§5 updated.)
> - **F2 MED:** additive exact-path read-only cage amendment (adds one vetted path to
>   `IS_VETTED`), NOT "cages untouched". Honest framing; no deny relaxed.
> - **F3 MED:** add a **launchd-context AC** — verify prefetch in the REAL launchd
>   context (not an interactive shell), mirroring edge-scout force-fire/log/commit
>   (lessons #343-347, #659-667). (§5 tests updated.)
> - **Q1:** scope CONFIRMED narrow — arXiv `cs.AI/cs.SE/cs.CL/cs.CR` + primary-source
>   vendor changelogs / model+API release notes ONLY; consume edge-scout/feature-scout,
>   do NOT supersede.
> - **Q2:** **launchd + cron split** — Mac Mini launchd prefetches the cache; a scheduled
>   task/cron (edge-scout family) triggers the weekly digest. NO brisen-lab APScheduler
>   for external fetching.
> - **Q3:** `_ops/research-monitors-cache/` = Mac-Mini-populated, researcher read-only;
>   add a README/schema + `_status.json` staleness contract.
> - **Q4:** additive read-only `IS_VETTED` entry acceptable; route via lead PR merge, no
>   self-ship.
> - **Build notes:** baked constant OR pinned non-researcher-writable config; NO env
>   override, NO arg-driven config path; FAIL LOUD on missing/stale cache.

# #12 Standing source monitors — DESIGN (pre-build, for codex design-verify)

## 1. Problem

Recency is rebuilt cold on every brief: the researcher re-discovers "what shipped this
week from Anthropic / arXiv / key vendors" from scratch each time. There is no standing
watch, so time-sensitive coverage is slow and inconsistent (`method.md` has an ad-hoc
15-channel table, no "watch these N continuously" surface).

## 2. Hard constraints (preserved)

- Researcher **write-cage**: writes ONLY to `wiki/research/**` + session memory
  (`researcher_write_cage.sh:52-53`). A standing digest lands INSIDE this surface.
- The **cache** of pre-fetched feeds must be populated by a **trusted actor** (Mac Mini
  launchd), NOT the researcher's Write tool — the researcher READS the cache, matching the
  aidennis-edge-scout split (`_ops/edge-scout-cache/` filled by Mac Mini Sat 17:00 UTC).
- **Bash cage**: the researcher reads the cache via a vetted read-only script at a pinned
  path; no raw `curl`/`python`. No send/write MCP verbs.
- No self-edit of orientation/method by the researcher (monitor list + method row route
  via lead/codex).

## 3. Prior art — reuse, do not duplicate (surface-the-conflict)

Three existing watchers already exist; #12 MUST cross-reference, not clone them:
- **`aidennis-edge-scout`** (AID-T): weekly digest from Simon Willison / Hamel / Eugene
  Yan / HuggingFace RSS → `wiki/_ai-it/aid-t/live-edge/`. Cron Sun 18:00 UTC; cache
  `_ops/edge-scout-cache/` + `_status.json`. **Owns the SRE/agent-arch/eval blog lane.**
- **`anthropic-feature-scout`**: Import AI + Latent Space + Stratechery; fires on-demand /
  on Director mention. **Owns the Anthropic-release editorial lane.**
- **`baker_rss_feeds` / `baker_rss_articles`** MCP: an "always" ingestion sweep surface.

**Conflict to resolve with codex/lead (not average):** #12 should NOT re-watch what
edge-scout / feature-scout already cover. The researcher's DISTINCT gap is
**primary-source research recency**: (a) **arXiv new papers** by tag (`cs.AI`, `cs.SE`,
`cs.CL`, `cs.CR`) — no standing monitor exists anywhere today; (b) **vendor model/API
release notes** as primary sources (Anthropic docs changelog, OpenAI/Google DeepMind
model cards) for cit, not editorial commentary. Anthropic overlaps feature-scout →
propose #12 DEFERS the Anthropic-editorial slice to feature-scout and keeps only the
primary-source changelog slice, or consumes feature-scout's output. Codex to rule.

## 4. Design

Mirror the edge-scout pattern, scoped to the researcher's primary-source gap:

1. **Monitor registry** — a pinned list `~/bm-b1/scripts/research-monitors.conf` (or a
   constant) enumerating sources: arXiv tag queries + vendor changelog/RSS URLs. Editable
   by lead, not the researcher.
2. **Pre-fetch (trusted actor)** — a Mac Mini launchd job (weekly, staggered off the
   17:00/18:00 edge-scout slot) pulls each source → writes raw to a cache dir
   `_ops/research-monitors-cache/<source>.{xml,json}` + `_status.json` freshness/last-
   success age. Same durability contract as edge-scout. *(Open Q for codex: Mac Mini
   launchd vs brisen-lab cron vs `/schedule` skill — edge-scout uses launchd + cron.)*
3. **Read + digest (researcher)** — a vetted read-only script
   `~/bm-b1/scripts/check_source_monitors.sh` reads the cache dir, filters items to the
   last 7 days, dedups against the last 4 weekly digests, and returns a summary. The
   researcher composes the weekly digest into `wiki/research/YYYY-MM-DD-research-monitors-
   weekly.md` (inside its write-cage). Staleness (from `_status.json`) is surfaced in the
   digest, never silently swallowed (Mnilax fail-loud).
4. **Method row** — add a "Standing monitors" row to `method.md §2` (routed via
   lead/codex), pointing at `check_source_monitors.sh` + the digest surface.

## 5. Deliverables (when codex clears this design → build)

1. `~/bm-b1/scripts/check_source_monitors.sh` — vetted read-only cache reader +
   7-day/dedup filter + staleness surface (read_message.sh lineage).
2. `~/bm-b1/scripts/research-monitors.conf` (or baked constant) — the source registry
   (arXiv tags + primary-source vendor changelogs), lead-editable.
3. Pre-fetch job definition (launchd plist or cron entry) for the trusted-actor fetch +
   `_ops/research-monitors-cache/` with `_status.json`. *(Who installs the launchd job is
   a Mac Mini action — flag to lead; b2 delivers the script + plist, does not self-install
   on the Mac Mini.)*
4. Cage allow-list entry for `check_source_monitors.sh` (additive read-only — same
   classification question as #11 Q2).
5. Tests: fresh cache → items surfaced; stale `_status.json` → staleness flagged not
   dropped; dedup against prior digests; empty/missing cache → clean "no fresh items" (not
   a crash).

## 6. Open questions for codex design-verify

- **Q1 — overlap resolution.** Confirm #12 scope = arXiv papers + primary-source vendor
  changelogs ONLY, deferring the Anthropic/AI-blog editorial lane to feature-scout /
  edge-scout (consume their output rather than re-fetch). Or does Director want a single
  unified researcher monitor that supersedes them? (Surface-the-conflict, don't average.)
- **Q2 — scheduler mechanism.** Mac Mini launchd + cron (edge-scout precedent) vs
  brisen-lab APScheduler vs `/schedule` skill.
- **Q3 — cache location + owner.** `_ops/research-monitors-cache/` populated by Mac Mini
  (my default, mirrors edge-scout) — confirm the researcher only READS it.
- **Q4 — cage-edit classification** (same as #11 Q2): additive vetted read-only script in
  `IS_VETTED` — inside "cages untouched" or needs explicit lead ratification?

## 7. What this design explicitly does NOT do

- No researcher writes outside `wiki/research/**` + session memory.
- No researcher-driven network fetch inside the cage (fetch is the trusted-actor
  launchd job; researcher reads the cache).
- No duplication of edge-scout / feature-scout coverage (cross-reference instead).
- No self-install on the Mac Mini by b2 (deliver script + plist; lead/Mac-Mini installs).
