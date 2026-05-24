---
brief_id: HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1
title: AND-gate overlay for matter classifier — tighten hagenauer-rg7 transcript tagging
status: PENDING
authored_by: AH1
dispatched_by: lead
dispatched_at: 2026-05-24T12:30:00Z
ratified_by: Director (chat 2026-05-24)
target: b2
target_repo: baker-master (+ baker-vault for overlay YAML)
matter_slug: hagenauer-rg7
brief_path: ~/baker-vault/_ops/briefs/BRIEF_HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1.md
brief_anchor: baker-vault 26c7439
estimated_time: ~1h
complexity: Low
gate_class: SMALL
prerequisites: none (HAG_WORKERS_PHASE_1 is unrelated codebase, no blocker)
ratification_anchor:
  - bus #831 (hag-desk → deputy, 6/33 mistags surfaced)
  - bus #839 (deputy → lead, brief-request)
  - Director chat 2026-05-24: Option (a) ratified
---

# CODE_2_PENDING — HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1

**Read the full brief first:** `~/baker-vault/_ops/briefs/BRIEF_HAG_TRANSCRIPT_CLASSIFIER_TIGHTEN_1.md` (anchor `baker-vault 26c7439`).

## TL;DR
Add per-matter YAML overlay (`baker-vault/wiki/matters/<slug>/classifier-keywords.yml`) that activates AND-gate semantics in `orchestrator/pipeline._match_matter_slug`. Ship 1 YAML + 1 migration (6 idempotent UPDATEs) + 1 test file (7 cases) + 1 code edit (~80 LOC).

## Repos touched (2)
1. **baker-master** — `orchestrator/pipeline.py` (edit) + `migrations/20260524_hagenauer_rg7_reclassify.sql` (new) + `tests/test_match_matter_slug_and_gate.py` (new) + `tasks/lessons.md` (append #71)
2. **baker-vault** — `wiki/matters/hagenauer-rg7/classifier-keywords.yml` (new)

## PR sequence
- baker-vault PR (YAML overlay) — merges first so production has the file before code change goes live
- baker-master PR (code + migration + test) — merges second

## Critical pre-flight checks (per brief Quality Checkpoints)
1. Confirm `BAKER_VAULT_PATH` env var is set on Render production. If absent, verify `/opt/render/project/src/baker-vault` default path exists in build config.
2. Confirm 4 target slugs (`ao-holding`, `brisen`, `mrci`, `lilienmatt`) are canonical + active in `baker-vault/slugs.yml`. Line-grep before applying migration. If any wrong, STOP + bus AH1.
3. Run pre-flight SELECT (in migration comment) to verify each WHERE-clause matches exactly one row. If any matches 0 or >1, STOP + bus AH1.
4. PyYAML must be in `requirements.txt`. Grep first; add only if missing.

## Ship gate
- Literal `pytest tests/test_match_matter_slug_and_gate.py -v` output in ship report (no "pass by inspection" — Lesson #8).
- Expect: 7 passed (5 AC cases + 2 regression).
- Singletons check: `bash scripts/check_singletons.sh` (no new instances expected).
- Bash syntax: `python3 -c "import py_compile; py_compile.compile('orchestrator/pipeline.py', doraise=True)"`.

## Bus-post on ship
Post to lead with:
- 2 PR numbers + URLs
- pytest output (full)
- pre-flight SELECT result (6 row hits, ID + date + new slug per row)
- BAKER_VAULT_PATH confirmation
- Quality Checkpoint 5 plan (post-merge API count smoke)

## Dispatch lane choice
b2 because b1 is mid-flight on HAG_WORKERS_PHASE_1 gate chain (3 PRs awaiting AH2). Codebases are independent so b2 has clean working tree.

End mailbox.
