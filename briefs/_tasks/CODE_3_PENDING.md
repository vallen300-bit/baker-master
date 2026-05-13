---
status: PENDING
brief: briefs/BRIEF_DEADLINE_SIGNAL_HYGIENE_1.md
brief_id: DEADLINE_SIGNAL_HYGIENE_1
trigger_class: TIER_B_CLASSIFIER_THRESHOLD_+_QUERY_HYGIENE
dispatched_at: 2026-05-13
dispatched_by: ai-head-1 (AH1)
target: b3
mandatory_2nd_pass: false
security_review_required: false
effort_estimate: ~3h
predecessor:
  brief: briefs/BRIEF_DEADLINE_MATTER_SLUG_BACKFILL_1.md
  pr: 200
  merge_commit: 761b07de0899ba48f194a5c2fca4814cbec203da
  director_apply: 918188f (19/19 applied 2026-05-13T10:31Z)
director_ratification: |
  2026-05-13 post-Triaga: "All dropped items should never be even surfaced. It
  is pure noise. Can we avoid them in the future? Also, the items that were done
  already (e.g. Cupial) — this is a closed item." Then ratified: "follow your
  recomends" + "use /write-brief sop".
scope_summary:
  scope_a: Classifier threshold raise + kbl/noise_patterns.py NEW pre-classifier filter
  scope_b: Matter-closed JOIN filter on active-deadline queries
  scope_c: One-shot cleanup of 2 stray raw matter_name rows
followup_brief: DEADLINE_FEEDBACK_LOOP_1 (dashboard UI, dispatched after this ships)
ship_gate: literal pytest -v output paste + check_singletons PASS
bus_topic: ship/DEADLINE_SIGNAL_HYGIENE_1
---

# CODE_3_PENDING — DEADLINE_SIGNAL_HYGIENE_1

Read `briefs/BRIEF_DEADLINE_SIGNAL_HYGIENE_1.md` for full spec.

## Confirmation phrase
`"B3 oriented. Read: CODE_3_PENDING.md, MEMORY.md."`

## Working dir
`~/bm-b3` — branch off `main` after `git pull --ff-only`. Suggested branch: `b3-deadline-signal-hygiene`.

## What ships
1. **Scope A** — 5 file edits + new `kbl/noise_patterns.py` + new `tests/test_deadline_noise_filter.py` (≥6 tests)
2. **Scope B** — 2 file edits (vault_scanner.py + any active-deadline dashboard queries enumerated in your recon step) + new `tests/test_deadline_matter_closed_filter.py` (≥3 tests)
3. **Scope C** — `--cleanup-strays` mode on backfill script + tests
4. **Recon paste in ship report** — Scope B query inventory (all `FROM deadlines WHERE status = 'active'` sites + your decision per site)
5. **Pattern list paste in ship report** — final `_NOISE_PATTERNS` list for Director review

## What does NOT ship (AH1 owns)
- Executing Scope C `--cleanup-strays --apply` against prod (Director-gated)
- Marking matter_registry rows inactive (Director's call)
- DEADLINE_FEEDBACK_LOOP_1 (separate dispatch after this ships)

## Bus post on ship
```bash
BAKER_ROLE=b3 ~/Desktop/baker-code/scripts/bus_post.sh lead \
  "PR #<N> OPEN — DEADLINE_SIGNAL_HYGIENE_1 (Scope A noise filter + B matter-closed + C stray cleanup). <K>/<K> tests PASS. check_singletons PASS. Threshold raised >=1 → >=3. Pattern list + query inventory + dry-run buckets in ship report." \
  ship/DEADLINE_SIGNAL_HYGIENE_1
```
