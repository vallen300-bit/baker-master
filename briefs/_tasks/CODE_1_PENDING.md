---
status: CLAIMED
claimed_at: 2026-05-16T09:00:00Z
claimed_by: b1
branch: b1/ao-pm-read-curated-wiki-1
brief: briefs/BRIEF_AO_PM_READ_CURATED_WIKI_1.md
brief_id: AO_PM_READ_CURATED_WIKI_1
trigger_class: MEDIUM (capability read-path; /security-review required due to slug-input filesystem read)
dispatched_at: 2026-05-16T08:50:00Z
dispatched_by: ai-head-2 (AH2) — Director redirect "use b1 or b4"
target: b1
prior_brief_parked: |
  WORKER_SELFWAKE_PHASE_1 was the prior CODE_1_PENDING dispatch; Director
  parked it 2026-05-15. Parked content preserved at
  briefs/_tasks/CODE_1_PARKED_WORKER_SELFWAKE.md — pickup that one once
  this brief ships and Director re-authorizes worker-selfwake.
context: |
  Director caught a Baker stale-answer bug 2026-05-16 ~07:57Z: meeting-prep
  briefing said "AO is late on EUR 2.5M April capital transfer" while
  curated wiki (wiki/matters/capital-call/curated/02_money.md, last curated
  2026-05-01) records Drawdown #1 RECEIVED 24-28 Apr 2026 (€700K AO Swiss
  CBH + €1.8M Bank of Cyprus).

  Root cause: AO-PM capability reads only pm_project_state.ao_pm.state_json
  (DB structured row). The capital_calls field there has been byte-identical
  across versions 1-139 — never updated for the Q2-2026 cycle. Curated wiki
  is invisible to AO-PM's read path. Class bug across all per-matter PMs.

  This brief implements Option B (additive context-builder injection — no
  schema change). Recommended over Option A (heavy pipeline) and Option C
  (schema-shaping). Sister brief PM_STATE_UPDATE_PATCH_NOT_PARALLEL_1 is
  going to B4 in parallel; independent merge.
review_chain:
  - AH2 cross-lane review (read-side architectural change)
  - /security-review (slug-input filesystem read; constrain matter slug
    to ^[a-z0-9-]+$ from slugs.yml allow-list; no path traversal)
  - AH1 final sign-off (Cortex Design boundary per autonomy charter §4)
ship_gate: see brief §"Ship gate"
acceptance: see brief §"Acceptance criteria"
estimated: medium · ~3-5 hours · 1 PR · Tier-B
branch_suggestion: b1/ao-pm-read-curated-wiki-1
