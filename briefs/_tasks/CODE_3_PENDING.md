---
status: shipped
brief: briefs/BRIEF_PLAUD_TRANSCRIPT_BY_MATTER_1.md
brief_id: PLAUD_TRANSCRIPT_BY_MATTER_1
target_repo: baker-master
working_dir: ~/bm-b3
working_branch: b3/plaud-transcript-by-matter-1
matter_slug: hagenauer-rg7
cross_matter_usage: [hagenauer-rg7 first; pattern generalizes to AO Desk + MOVIE Desk + Baden-Baden Desk later — read path is slug-scoped]
dispatched_at: 2026-05-22T12:38:00Z
dispatched_by: deputy
authored_by: deputy (AH2)
brief_commit: 57f898c (squashed into 9431e58 per AH2 #685)
director_auth: 2026-05-22 chat — "fire B3" (post recommendation accept)
estimated_effort: ~5h
complexity: Medium
priority: tier-b (HARD DEADLINE Tue 2026-05-26 — hag-desk Forderungsanmeldung filing)
reply_target: deputy (bus topic `ship/plaud-transcript-by-matter-1` → AH2 picker-architect + 2nd-pass reviewer chain)
two_reviewer_chain_status: pre-cleared by AH2 (feature-dev:code-architect CHANGES_NEEDED → folded; feature-dev:code-reviewer PASS-WITH-NITS → folded; 11 items applied)
shipped_at: 2026-05-22T12:57:34Z
shipped_pr: 242
shipped_commit: 8d5165b
ship_report: briefs/_reports/B3_PLAUD_TRANSCRIPT_BY_MATTER_1_20260522.md
bus_ship_msg_id: 694
---

# CODE_3_PENDING — PLAUD_TRANSCRIPT_BY_MATTER_1 — 2026-05-22

**Brief:** `briefs/BRIEF_PLAUD_TRANSCRIPT_BY_MATTER_1.md` (on origin/main, commit 57f898c bundled at 9431e58 per AH2 dispatch #685)
**Working branch:** `b3/plaud-transcript-by-matter-1` (off main, baker-master)
**Repo:** baker-master ONLY (no brisen-lab / baker-vault touch)
**Author:** AH2 (deputy) — full review chain pre-cleared
**Reply target on PR open + ship:** `deputy` (AH2 owns picker-architect + 2nd-pass reviewer on the implementation PR; lead is NOT in the gate chain)

## Bottom line

Add `matter_slug` column to `meeting_transcripts`, auto-populate at ingest via existing `_match_matter_slug` + new `slug_registry.normalize` pass, add `GET /api/transcripts/by-matter/{slug}` endpoint (X-Baker-Key auth, active-slugs validation, `include_body=False` default, LIMIT 200), and ship a dry-run-default backfill script.

Director ratified Option B — classifier + ratified-backfill + hag-desk gap audit. HARD DEADLINE Tue 2026-05-26 (Hagenauer-RG7 Forderungsanmeldung filing).

## Scope (per brief §Solution overview)

1. `migrations/20260522_meeting_transcripts_matter_slug.sql` — ADD COLUMN `matter_slug TEXT` + index.
2. `memory/store_back.py`:
   - bootstrap (`_ensure_meeting_transcripts_base` or equivalent) updated to include the new column for fresh DBs (migration-vs-bootstrap drift trap — verify type match with the migration).
   - `store_meeting_transcript()` auto-assigns via `_match_matter_slug` + `slug_registry.normalize`. Mirrors `create_alert()` at `memory/store_back.py:4453-4459` with the deliberate normalize divergence (read path queries canonical slug; classifier returns raw `matter_name`).
3. `outputs/dashboard.py` — new `GET /api/transcripts/by-matter/{slug}` route:
   - X-Baker-Key auth (existing pattern)
   - active-slugs validation (via `slug_registry`)
   - `include_body=False` default
   - LIMIT 200 cap
4. `scripts/backfill_meeting_transcripts_matter_slug.py` — dry-run-default modeled on `scripts/backfill_matter_slug.py`. **CRITICAL**: `meeting_transcripts.id` is `TEXT` not `INT` (per brief flag); back-fill loop must handle string IDs.
5. Tests: ~15 cases per brief.

## Pre-backfill gate (brief flag)

`slugs.yml` must have an alias entry mapping the Hagenauer matter_registry `matter_name` → `hagenauer-rg7`. If missing: separate-repo PR on baker-vault BEFORE running `--apply`. b3 verifies pre-flight via `grep -E '^  - slug: hagenauer-rg7' ~/baker-vault/slugs.yml` + alias-block check; if alias missing, surface to deputy via bus + halt before backfill apply.

## Ship gate (literal output required — no "pass by inspection")

- Bootstrap DDL grep (`grep -n 'matter_slug' memory/store_back.py | grep -i transcript`) to confirm bootstrap mirrors migration.
- Migration apply against TEST_DATABASE_URL (literal psql output or migration runner stdout).
- `pytest tests/test_meeting_transcripts_matter_slug.py -v` literal output (new test file expected).
- `pytest tests/test_api_transcripts_by_matter.py -v` literal output (new test file expected).
- Backfill script `--dry-run` execution log (no rows changed, summary table only).
- Hag-desk gap audit per brief: dry-run output proving `hagenauer-rg7` rows get tagged.

## Reporting

- Bus-post `deputy` (NOT lead) on EACH state change:
  - PR open: topic `pr-open/plaud-transcript-by-matter-1`
  - Ship complete: topic `ship/plaud-transcript-by-matter-1`
  - Blocker / pre-backfill-gate fail: topic `blocker/plaud-transcript-by-matter-1`
- Ship report: `briefs/_reports/B3_PLAUD_TRANSCRIPT_BY_MATTER_1_20260522.md`
- AH2 will run picker-architect + feature-dev:code-reviewer 2nd-pass on the implementation PR before recommending merge to lead.

## Co-Authored-By

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
