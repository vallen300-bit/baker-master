---
status: COMPLETE
brief: briefs/BRIEF_CORTEX_SCAN_FLASH_ROUTE_KILL_1.md
trigger_class: COST_SAFETY_GATE
dispatched_at: 2026-05-04T06:35Z
dispatched_by: ai-head-a
claimed_at: 2026-05-04T07:05Z
claimed_by: b1
completed_at: 2026-05-04T07:30Z
verdict: PASS
ship_report: briefs/_reports/B1_cortex_scan_flash_route_kill_20260504.md
pr: 156
ah2_review_required: true
autopoll_eligible: false
---

B1 PASS — PR #156 opened. Awaiting AH2 review + AH1-Terminal merge + post-merge Render env var (A7-A8).
- Tests 9-11 PASS literally on `b1/cortex-scan-flash-route-kill-1`
- Targeted suite: 65 passed / 1 skipped / 1 pre-existing unrelated fail (Test 8, verified on pristine main)
- /security-review NO FINDINGS
- Ship report: `briefs/_reports/B1_cortex_scan_flash_route_kill_20260504.md`



B1: Scan→Cortex Flash-route kill switch.

**Spec:** add env var `CORTEX_SCAN_FLASH_ROUTE_DISABLED`. When `true`, `classify_intent` skips the Flash branch entirely and returns `{"type": "question"}`. Closes the cost-safety gap where Scan→Cortex via Flash bypasses `CORTEX_GATE_ENABLED`.

**Read first (MANDATORY):**
1. `briefs/BRIEF_CORTEX_SCAN_FLASH_ROUTE_KILL_1.md` — full spec + test code + acceptance criteria
2. `~/baker-vault/_ops/agents/b1/orientation.md` — your role
3. `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md` — canonical Baker memory

**First-message confirmation phrase (evidence-bound, exact):**
`"B1 oriented. Read: CODE_1_PENDING.md, MEMORY.md."`

**Files to modify:**
- `orchestrator/action_handler.py` — insert ~10-line gate block after line 680, before line 682 (verified line refs by AH1-Terminal Read on 2026-05-04). **`import os` is NOT currently in the file** — add it. Logger is configured (line 712 `logger.warning` confirms).
- `tests/test_scan_cortex_intent.py` — append Tests 9-11 (paste verbatim from brief).

**Do NOT touch:** `_quick_cortex_run_detect`, `_quick_capability_detect`, `_quick_email_detect`, `triggers/cortex_pipeline.py`, `triggers/cortex_pre_review_gate.py`, `outputs/dashboard.py`, `outputs/cortex_run_stream.py`, `triggers/waha_webhook.py` (intentional blast radius).

**Acceptance criteria (B1 owns A1-A6):**
- A1: Test 9 (kill-active) PASS
- A2: Test 10 (kill-default-inactive) PASS
- A3: Test 11 (regex-bypass-kill) PASS
- A4: Existing Tests 1-8 still PASS
- A5: Full pytest suite green (run literally — no "by inspection")
- A6: `/security-review` clean (Tier-B mandatory)

**A7-A8 are AH1-Terminal post-merge** — Render env-var add + smoke test. NOT B1.

**Quality checkpoints (must satisfy in ship report):**
1. Paste literal `pytest tests/test_scan_cortex_intent.py -v` output
2. Paste full pytest suite output (or relevant green summary)
3. Paste `/security-review` verdict
4. Confirm `import os` was added (was missing)

**Lane:**
- B1 builds + opens PR
- AH2 review required (cross-capability gate touch + cost-safety class)
- AH1-Terminal merges on green CI + AH2 GREEN + clean security-review
- AH1-Terminal sets Render env var post-merge + smoke tests

**PL ship-report contract:** end your chat ship report with a fenced PL paste-block per `~/baker-vault/_ops/skills/ai-head/SKILL.md` §"PL ship-report contract".
