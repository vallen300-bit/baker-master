---
report_id: B3_SKILLS_EVAL_HARNESS_1
brief_id: SKILLS_EVAL_HARNESS_1
authored_by: b3
authored_at: 2026-05-25
target_repo: baker-vault
pr: 114
pr_url: https://github.com/vallen300-bit/baker-vault/pull/114
pr_state: OPEN, MERGEABLE
branch: b3/skills-eval-harness-1
head_commit: 976d6c3
status: shipped — awaiting deputy gates 1+2+4 + lead gate-5
reply_target: deputy (AH2) — cc lead
companion_to: SOPS_TO_SKILLS_MIGRATION_1 (PR #113 merged)
director_ratified: 2026-05-25 Q3=A (chat — static trigger-keyword eval only for v1)
---

# B3 ship report — SKILLS_EVAL_HARNESS_1

## Bottom line

v1 static trigger-keyword eval harness shipped on `b3/skills-eval-harness-1` @ commit `976d6c3`. PR #114 OPEN, MERGEABLE, zero CI/checks. 15/15 PASS on starter corpus (5 hot skills × 3 cases). 60 catalog skills uncovered (v2 backlog).

## Files delivered

- `_ops/scripts/run_skill_trigger_evals.py` — stdlib Python runner. Walks `_ops/skills/<*>/SKILL.md`, extracts `MANDATORY TRIGGERS:` (plain + `**bold**` + `"quoted"` forms), case-insensitive substring match. PyYAML optional with JSON fallback.
- `_ops/evals/skills/test-cases.yml` — 5 hot skills × 3 cases = 15 cases. Mix of fire + no-fire.
- `_ops/evals/skills/README.md` — corpus extension instructions, foot-guns, v2 placeholder.
- `_ops/evals/skills/baseline-20260525.txt` — first-run output checkpointed.

## Starter corpus deviation (surfaced to deputy)

Brief named `write-brief` + `dropbox-file-delivery` as 2 of the 5 hot skills. Both ship without a `MANDATORY TRIGGERS:` header — their trigger phrases live in frontmatter `description` only. Brief's Do-NOT list forbids editing SKILL.md trigger headers as part of this work.

**Substitution:** `b-code-dispatch-coordination` + `email-send-via-mail-app`. Both hot in current B-code dispatch + outbound-email traffic. Final 5:

1. `agent-bus-posting-contract`
2. `ai-head`
3. `b-code-dispatch-coordination`
4. `cascade-back-prop`
5. `email-send-via-mail-app`

Deputy decision needed: accept the substitution OR follow-up brief to add `MANDATORY TRIGGERS:` headers to `write-brief` + `dropbox-file-delivery` so the original starter list can be honored.

## Baseline-report output (live re-run 2026-05-25)

```
======================================================================
Skill trigger eval - 15 cases across 5 skills
======================================================================
PASS: 15/15 (100%)
FAIL: 0

PER-SKILL SCORECARD:
  [OK] agent-bus-posting-contract: 3/3
  [OK] ai-head: 3/3
  [OK] b-code-dispatch-coordination: 3/3
  [OK] cascade-back-prop: 3/3
  [OK] email-send-via-mail-app: 3/3

SKILLS IN CATALOG BUT WITHOUT TEST CASES (60):
  - ai-head-brief-and-gate
  - ai-head-memory-reference
  - ai-head-ops-reference
  - ... (57 more — full list in baseline-20260525.txt)
```

Runtime: <1s. Exit code: 0.

## Acceptance criteria — verification

| AC | Status | Note |
|---|---|---|
| 1 — evals dir + 3 corpus files exist | PASS | `test-cases.yml`, `README.md`, `baseline-20260525.txt` |
| 2 — runner executable, <5s | PASS | <1s on first run |
| 3 — 5 skills × 2-3 cases, all PASS | PASS | 15/15 |
| 4 — baseline committed showing coverage | PASS | 60 uncovered listed as v2 backlog |
| 5 — README explains add-case flow | PASS | with foot-guns section |
| 6 — regex spot-check on 3 forms | PASS | (a) plain `agent-bus-posting-contract` 31kw, (b) synthetic `**bold**` 3kw clean, (c) `email-send-via-mail-app` 17kw — no `**` or quote leak |
| 7 — exit 0 on PASS, 1 on FAIL | PASS | deliberately broken case → exit=1, restored |
| 8 — no hard PyYAML dep | PASS | optional import, JSON fallback path coded |
| 9 — no LLM clients in runner | PASS | grep clean: no `anthropic`/`openai`/`httpx`/`requests` |
| 10 — pre-commit clean | PASS | cascade-backprop did not fire (no D-### touched) |

## Gates expected

- Gate-1 architecture → deputy
- Gate-2 security light → deputy
- Gate-3 picker-architect → SKIP per brief
- Gate-4 code-reviewer 2nd pass → deputy
- Gate-5 merge + first baseline rerun → lead

## Anchor

Director thevccorner.com Substack read 2026-05-25 ("Prompts Are Dead. Skills Are the New Moat" — "Evals are the new gross margin"). Q3=A ratified in chat same day.

## Notes on prior-session continuity

Implementation commit `976d6c3` was authored by a prior B3 session (~14:17Z) directly after dispatch (~13:41Z) but no ship report + bus-post close-out happened. This report + bus-post fills the gap. Mailbox still shows PENDING — deputy can flip to COMPLETE once Gate-5 lands.
