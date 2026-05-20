---
status: CLAIMED
claimed_at: 2026-05-21T07:00:00Z
claimed_by: b2
branch: b2/waha-outbound-capture-1
brief: briefs/BRIEF_WAHA_OUTBOUND_CAPTURE_1.md
brief_id: WAHA_OUTBOUND_CAPTURE_1
target_repo: baker-master
working_dir: ~/bm-b2
matter_slug: baker-internal
cross_matter_usage: [all-matters — WhatsApp capture-shape affects every desk that reads whatsapp_messages]
dispatched_at: 2026-05-21T06:30:00Z
dispatched_by: lead
director_auth: 2026-05-21 chat — "go ahead, draft the brief" + "go" on dispatch ratification (Phase 5 of slow-path protocol per Director directive 2026-05-20 ~16:00Z)
trigger_class: HIGH (capture-authority change — lifts the fromMe filter; downstream consumers assumed inbound-only)
gate_chain:
  gate_1_static: REQUIRED (AH2 cross-lane)
  gate_2_security_review: REQUIRED (external-surface — webhook capture semantics, RAG context shape)
  gate_3_cross_lane_architecture: REQUIRED (architect verdict locked in investigation Phase 3; gate 3 validates implementation matches the locked model)
  gate_4_2nd_pass_code_reviewer: REQUIRED per SKILL.md §Code-reviewer 2nd-pass criteria 4 (external-surface) + 7 (high-stakes judgment)
estimated_effort: 1.5-2.5h
working_branch_suggestion: b2/waha-outbound-capture-1
reply_target: lead (bus topic `ship/waha-outbound-capture-1`)
investigation_anchor: baker-vault _ops/investigations/2026-05-20-waha-capture-gaps.md (commit dcf0c2a + addendum 4562f19)
prior_mailbox_state: superseded — previous CODE_2_PENDING.md was DIRECTOR_FACING_FILTER_V1_1_PHASE_2 COMPLETE (PR #227 merged 2026-05-19T22:02:56Z). b2 idle since.
---

# CODE_2_PENDING — WAHA_OUTBOUND_CAPTURE_1 — 2026-05-21

## Brief

`briefs/BRIEF_WAHA_OUTBOUND_CAPTURE_1.md` (this repo, baker-master main).

Read end-to-end before starting. 9 Fixes (1 shared helper + webhook filter lift + chat_id normalization + Director routing discriminator + RAG direction tagging + SQL guards + endpoint exposure + one-shot data migration + tests). Slow-path investigation already ran: architect verdict locked Q1-Q4 (Q4 dropped per Director); reviewer audit found 2 HIGH (encoded as Fix 4 + Fix 5) + 4 MEDIUM (encoded as Fix 6 + Fix 7). All `file:line` citations verified at HEAD `7e5657c` by AH1 2026-05-21.

## Working branch

`b2/waha-outbound-capture-1` in baker-master (`~/bm-b2`).

## Pre-requisites

- b2 idle confirmed (CODE_2_PENDING was COMPLETE state from PR #227, merged 2026-05-19).
- Investigation report at baker-vault `_ops/investigations/2026-05-20-waha-capture-gaps.md` — READ this for full context before touching code.
- Migration script (Fix 8) runs BEFORE deploy. b2 ships PR; AH1 owns running the migration on Render shell after merge, before re-checking smoke gate.

## Open question (encoded in brief Fix 4) — STOP gate

**`BAKER_SELF_CHAT` constant.** The Director routing discriminator needs to know which `chat_id` value corresponds to "Director-to-Baker" (Baker's self-chat / Baker's bot number). If grep finds no existing constant, brief tells you to derive via the SQL query in Fix 4. **If both grep AND SQL come up empty: STOP. Surface to `lead` via bus. Do NOT guess.**

## Acceptance criteria

Per brief §Quality Checkpoints + §Ship gate:

1. `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"` clean across all 6 modified + 3 new files
2. `bash scripts/check_singletons.sh` exits 0
3. `pytest tests/test_waha_outbound_capture.py -v` — literal green; PR description includes pytest stdout
4. Full `pytest` — literal green (or pre-existing-baseline failures only, named in PR)
5. /security-review on the PR — pass / NO_FINDINGS (external-surface change — webhook capture semantics)
6. NO "pass by inspection." Literal pytest output mandatory.

## Ship gate

Per brief §Ship gate — literal `pytest` output in PR. AH1 owns the post-deploy live smoke (Quality Checkpoint #6 in brief), so b2 ships when CI is green; smoke is AH1's responsibility.

## Reporting (bus reply-to-sender — Director-ratified 2026-05-17)

On PR open, bus-post `lead` per `dispatched_by`:

```bash
BAKER_ROLE=b2 ~/bm-b2/scripts/bus_post.sh lead \
  "ship/waha-outbound-capture-1 — PR #<N> open; pytest <X/X>; BAKER_SELF_CHAT resolved as <value> via <grep|sql>; awaiting AH1+AH2 gate chain (all 4 required)." \
  ship/waha-outbound-capture-1
```

`lead` (AH1-Terminal) handles gate orchestration + merge sequence.

## Lessons from prior WAHA / DB work (apply proactively)

1. **Lesson #28 — @lid don't filter, normalize** — this brief IS the "future improvement" called for. Fix 3 closes it.
2. **Lesson #35 — migrations shipped but never applied** — Fix 8 is a Python data-patch script, NOT a SQL migration. AH1 invokes it on Render shell post-deploy. Brief explicitly encodes this in Operational handoff.
3. **Lesson #36 — schema in migrations, not Python** — Fix 8 explicitly NO `ALTER TABLE`. Data-only. Compatible with the lesson.
4. **Lesson #42 — fixture tests ≠ real schema** — Fix 9 test class 6 uses ephemeral Neon branch via CI (auto-skip when `TEST_DATABASE_URL` unset).
5. **Lesson #62 — probe third-party first** — Phase 2 of investigation did this (direct WAHA `/chats` probe). Brief encodes mock-payload tests, not real WAHA calls.
6. **Lesson #100 — compile-clean ≠ done** — Quality Checkpoint #6 in brief is a post-deploy live smoke; AH1 owns.

## Heartbeat cadence (per §B-code stall chase — Director-ratified 2026-05-05)

Minimum every 12h while actively building. Two consecutive 12h misses → `lead` auto-surfaces stall to Director. Heartbeat = (a) UPDATE entry in this mailbox file with ISO timestamp, OR (b) commit on working branch with `mailbox(b2): heartbeat <ISO> — <where>` pattern, OR (c) ship-report file write.
