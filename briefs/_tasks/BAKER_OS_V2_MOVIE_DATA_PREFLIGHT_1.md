# BRIEF: BAKER_OS_V2_MOVIE_DATA_PREFLIGHT_1 — MOVIE flight data preflight (AO/Aukera precedent)

dispatched_by: lead
reply_to: lead (bus topic `movie-flight/data-preflight`)
Harness-V2: task class = diagnostic/verification (read-only data checks) · Context Contract below · done rubric §Verification · gate plan: lead reviews findings report (no code merge expected; if a fix PR emerges, codex bus review reasoning_effort=medium → lead merge). POST_DEPLOY_AC_VERDICT: N/A — read-only preflight, no deploy.

## Context
Director GO 2026-07-09: MOVIE flight rollout starts (rollout order BB → AO → MOVIE; MOVIE prep runs now, launch stays behind the C3/T2 gate). Before the MOVIE flight launches, verify the MOVIE matter's data foundation exactly as the Aukera pilot's and AO's were verified (`BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1` is the direct precedent — same checks, matter `movie`). The Aukera arc surfaced a seed-window gap and subject-family blind spots only AFTER go-live; MOVIE must not inherit that class of surprise. MOVIE project-room build + manifest is running in parallel at movie-desk — coordinate via bus, do not block on it.

**Repo:** baker-master (this repo, your clone). Read-only against prod data via standard query paths.

## Problem
MOVIE has zero data-foundation verification: no `project_registry` row (BB has 21 participants registered, AO row exists), no seed-window check, no subject-family map, unknown matter-tag hygiene across the `movie` / `mo-vie-am` / `mo-vie-exit` / `hagenauer-rg7` neighbor slugs. Launching the MOVIE flight on an unverified store risks the exact post-go-live surprises the Aukera pilot hit (seed-window truncation, subject-family blind spots).

## Estimated time: ~1 day · Complexity: Medium · Prerequisites: none (draft participant list below is enough to start)

## Scope — replicate the AO preflight checks for matter `movie`
1. **Seed-window coverage:** for each draft MOVIE participant family (MOHG operating team incl. `mhabicher@mohg.com`, RG7 GmbH, LCG SA, internal principals `rolf.huebner@brisengroup.com` / Vienna office, Moravcik construction lane — draft only; movie-desk's manifest is the confirmed list, re-run the delta when it posts to `manifest/MOVIE`), verify email store coverage over the lookback window matches source mailbox reality (no silent seed-window truncation — the Aukera precedent bug).
2. **Subject-family completeness:** map MOVIE subject families (Mandarin Oriental Vienna, MO VIE, MOVIE forecast/budget, MOHG, RG7, LCG, residences/units, DE/EN spellings); verify each family retrieves; flag families with zero hits that plausibly should have hits.
3. **Matter tagging:** sample MOVIE-relevant emails/transcripts/WA — verify `matter_slug` tagging routes to `movie` (watch the known neighbor slugs: `mo-vie-am`, `mo-vie-exit`, `mo-prague`, `hagenauer-rg7` — RG7 appears in both MOVIE and Hagenauer contexts; quantify cross-tags); quantify mis-tags/untagged.
4. **Non-mail stores:** Plaud transcripts + WhatsApp for MOVIE participants — confirm presence + matter-tagging (feeds the nonmail lane when MOVIE widens).
5. **Watermarks:** confirm ingestion watermarks fresh for all sources touching MOVIE data.

## Key constraints
- READ-ONLY. No backfills, no re-tags, no writes — findings report only. Any fix = separate proposal in the report, lead slices follow-up briefs.
- Draft participant families are enough to START; mark rows "pending movie-desk manifest" and re-run the delta when the manifest posts.
- movie-desk verifies your findings; post the report path to movie-desk as well as lead.
- Every gap needs a reproducible query/pointer with LIMIT — codex-verifiable, never "looked fine".

## Verification (done rubric)
1. Per-check findings table: check · method · result · gap? · severity.
2. Every gap has a reproducible query/pointer (codex-verifiable).
3. Explicit statement of what was NOT checked and why.
4. Report at `briefs/_reports/B_BAKER_OS_V2_MOVIE_DATA_PREFLIGHT_1_<date>.md`, bus-post summary to lead + movie-desk.

## Files Modified
- None in repo (read-only preflight). Sole artifact: the findings report at `briefs/_reports/B_BAKER_OS_V2_MOVIE_DATA_PREFLIGHT_1_<date>.md`.

## Quality Checkpoints
1. All 5 scope checks run-or-explicitly-waived — no silent skips (fail loud).
2. Every query cited in the report carries a LIMIT and reruns clean.
3. Neighbor-slug cross-tag check (movie vs mo-vie-am / mo-vie-exit / hagenauer-rg7) quantified, not sampled anecdotally.
4. Delta re-run scheduled note included for when movie-desk's `manifest/MOVIE` posts.
5. Bus summary posted to lead + movie-desk with report path.
