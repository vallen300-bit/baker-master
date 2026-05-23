---
status: PENDING
brief: briefs/BRIEF_TRANSCRIPT_CURATION_PHASE_1.md
brief_id: TRANSCRIPT_CURATION_PHASE_1
target_repo: baker-master
matter_slug: baker-internal
dispatched_at: 2026-05-23T17:35:00Z
dispatched_by: lead
target: b2
working_branch: b2/transcript-curation-phase-1
working_dir: ~/bm-b2
reply_to: lead
priority: tier-b
estimated_time: 4-5h
trigger_class: MEDIUM
gate_chain:
  gate_1_architecture_review: REQUIRED (AH2 runs architecture-review)
  gate_2_code_reviewer: REQUIRED (AH2 runs feature-dev:code-reviewer)
  gate_3_security_review: REQUIRED (additive Postgres schema; NO_FINDINGS expected)
  gate_4_ah1_final: REQUIRED (AH1 final merge)
prior_mailbox_state: superseded — previous CODE_2_PENDING.md was BRISEN_LAB_DESK_CARD_VISUAL_DIFFERENTIATION_1 COMPLETE (PR #31 brisen-lab, shipped 2026-05-22T17:00:13Z). b2 idle since.
ui_surface_prebrief: brief §Surface contract = N/A (pure backend) — gate satisfied
---

# CODE_2_PENDING — TRANSCRIPT_CURATION_PHASE_1 — 2026-05-23

**Brief:** `briefs/BRIEF_TRANSCRIPT_CURATION_PHASE_1.md`
**Working branch:** `b2/transcript-curation-phase-1` (off origin/main in baker-master)
**Target repo:** `baker-master` (clone at `~/bm-b2`)
**Pre-requisites:** none

## Bottom line

Phase 1 of 4-phase TRANSCRIPT_CURATION sequence (Director-ratified split 2026-05-23 evening). Slice-level data layer in Postgres only — no slicing, no LLM, no vault writes. Stand up `transcript_slices` table with E1 extended schema + non-fatal placeholder write hook at end of `store_meeting_transcript()`. Trigger files untouched.

## Pre-flight (mandatory before edit)

1. `cd ~/bm-b2 && git fetch origin main` — sync.
2. `git status -sb`. If dirty, stash + recovery-branch. If on stale branch, `git checkout main && git pull --ff-only origin main`.
3. `git checkout -b b2/transcript-curation-phase-1`

## Scope (3 features per brief)

1. **NEW** `migrations/20260524_transcript_slices.sql` — table + 3 indexes
2. **NEW** `_ensure_transcript_slices_table()` + `store_transcript_slice_placeholder()` in `memory/store_back.py` (place after existing `_ensure_meeting_transcripts_table` and `store_meeting_transcript`); 5-line non-fatal hook at end of `store_meeting_transcript()` success path
3. **NEW** `tests/test_transcript_slices_placeholder.py` (4 tests)

## Hard constraints

- **No "by inspection"** — every AC needs literal pytest output pasted verbatim
- **Migration-vs-bootstrap drift (Lesson #7):** bootstrap CREATE TABLE byte-equivalent to migration; verify with `diff` command in brief §"Key Constraints" Feature 1
- **Trigger files (`fireflies_trigger.py`, `plaud_trigger.py`, `youtube_ingest.py`) MUST stay untouched** — single-source-of-truth hook in `store_meeting_transcript`
- **Placeholder write failure must be non-fatal** — parent transcript write commits regardless (tested explicitly in test #4)
- **`conn.rollback()` in every except block** (Lesson: PostgreSQL pool poisoning)
- **Use `SentinelStoreBack._get_global_instance()` (classmethod) — NOT module-level import** — `_get_global_instance` is a classmethod at `memory/store_back.py:114`
- **Every SQL query has a LIMIT** (Lesson: unbounded queries)

## Acceptance criteria (AC1-AC6 per brief)

- **AC1** — migration file with exact SQL; runs clean on fresh DB
- **AC2** — production verification SQL: `transcript_slices` has 22 columns + 3 named indexes + PK
- **AC3** — `pytest tests/test_transcript_slices_placeholder.py -v` produces literal pass output (4 passed or 4 skipped); paste output verbatim in ship report
- **AC4** — `pytest` full suite passes; paste tail of output in ship report
- **AC5** — `bash scripts/check_singletons.sh` exits 0
- **AC6** — post-deploy 24h placeholder/transcript count 1:1 — AH1 Tier-B smoke (out-of-scope for ship report; ship on AC1-AC5)

## Ship gate

- Literal `pytest` green in baker-master (full suite + new tests)
- `bash scripts/check_singletons.sh` exit 0
- `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"` clean
- Migration diff vs bootstrap function: byte-equivalent (run diff command in brief)

## Reporting (bus reply-to-sender)

On PR open, bus-post `lead` per `dispatched_by`:

```bash
BAKER_ROLE=b2 ~/bm-b2/scripts/bus_post.sh lead \
  "ship/transcript-curation-phase-1 — PR #<N> open in baker-master; +X LOC backend; AC1-AC5 verified literal pytest; awaiting AH2 gate chain (gates 1+2+3) then AH1 merge." \
  ship/transcript-curation-phase-1
```

`lead` (AH1-T) handles gate orchestration + merge sequence (AH2 runs gates 1+2+3, AH1 merges on AH2 PASS).

## References

- Brief: `briefs/BRIEF_TRANSCRIPT_CURATION_PHASE_1.md`
- Canonical pattern: `~/baker-vault/_ops/processes/transcript-curation-architecture-v1.md` §1 + §11
- AH2 inheritance dispatch: bus #771
- Phase split anchor: Director ratification 2026-05-23 evening (Phase 1 only tonight)

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → `lead` auto-surfaces stall to Director. Given ~4-5h scope, expect 1-2 heartbeats max.
