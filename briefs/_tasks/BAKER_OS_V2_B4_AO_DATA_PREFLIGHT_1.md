# BRIEF: BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1 — AO flight data preflight (Aukera precedent)

dispatched_by: lead
reply_to: lead (bus topic `baker-os-v2/b4-ao-data-preflight`)
Harness-V2: task class = diagnostic/verification (read-only data checks) · Context Contract below · done rubric §Verification · gate plan: lead reviews findings report (no code merge expected; if a fix PR emerges, codex bus review reasoning_effort=medium → lead merge). POST_DEPLOY_AC_VERDICT: N/A — read-only preflight, no deploy.

## Context
ClickUp B4 (86cakevjb), Baker OS V2 rollout, Wave 2. Before the AO flight launches (B6), verify the AO matter's data foundation the same way the Aukera pilot's was verified — the Aukera arc surfaced a seed-window gap (your own seed-lookback fix) and subject-family blind spots only AFTER go-live. AO must not inherit that class of surprise. Roadmap §3 B4. AO project room build (B2) is running in parallel at ao-desk — coordinate via bus, do not block on it.

**Repo:** baker-master (this repo, your clone). Read-only against prod data via standard query paths.

## Estimated time: ~1 day · Complexity: Medium · Prerequisites: C5 post-deploy AC posted (finish that first)

## Scope — replicate the Aukera preflight checks for matter `oskolkov`
1. **Seed-window coverage:** for each draft AO participant (Oskolkov, Aelio counterparties, counsel — draft list per handbook Ch.3 "AO names"; Director confirms final list in the morning, re-run the delta after), verify email store coverage over the lookback window matches source mailbox reality (no silent seed-window truncation — the Aukera precedent bug).
2. **Subject-family completeness:** map AO deal subject families (Villa Gabbiano, Aelio, deal-code variants, RU/EN spellings); verify each family retrieves; flag families with zero hits that plausibly should have hits.
3. **Matter tagging:** sample AO-relevant emails/transcripts/WA — verify `matter_slug` tagging routes to the right matter; quantify mis-tags/untagged.
4. **Non-mail stores:** Plaud transcripts + WhatsApp for AO participants — confirm presence + matter-tagging (feeds C5 lane when AO widens).
5. **Watermarks:** confirm ingestion watermarks fresh for all sources touching AO data.

## Key constraints
- READ-ONLY. No backfills, no re-tags, no writes — findings report only. Any fix = separate proposal in the report, lead slices follow-up briefs.
- Draft participant list is enough to START; mark rows "pending Director confirm" and re-run the delta when the confirmed list posts.
- AO desk verifies your findings (roadmap); post the report path to ao-desk as well as lead.

## Verification (done rubric)
1. Per-check findings table: check · method · result · gap? · severity.
2. Every gap has a reproducible query/pointer (codex-verifiable, not "looked fine").
3. Explicit statement of what was NOT checked and why.
4. Report at `briefs/_reports/B1_BAKER_OS_V2_B4_AO_DATA_PREFLIGHT_1_<date>.md`, bus-post summary to lead + ao-desk.
