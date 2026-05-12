---
status: PENDING
brief: briefs/BRIEF_WAHA_2026_4_UPGRADE_AND_KEY_SPLIT_1.md
trigger_class: TIER_B_AUTH_AND_EXTERNAL_PERIMETER
dispatched_at: 2026-05-12
dispatched_by: ai-head-1 (AH1)
target: b2
scope_for_b2: PHASE 2 CODE PR ONLY — the 5-file diff specified in §"Fix/Feature 2 §Implementation Step 2.3". Phase 1 (WAHA Render image bump) is an AH1-side ops action, NOT B-code work. Phase 2 env-var rotation on Render (Step 2.4) is also AH1-side post-merge.
working_branch: feat/waha-2026-4-key-split
gates_required:
  - gate_1_pytest: literal `pytest tests/test_whatsapp_sender_lid.py tests/test_hot_md_weekly_nudge.py -v` GREEN (no "pass by inspection")
  - gate_2_security_review: AH2 runs `/security-review` on diff — touches API keys + external perimeter, mandatory per SKILL.md
  - gate_3_ah2_cross_lane: AH2 static read of diff
  - gate_4_code_reviewer_2nd_pass: REQUIRED — triggers on trigger-class TIER_B_AUTH_AND_EXTERNAL_PERIMETER (auth/secrets + external-surface, per SKILL.md §Code-reviewer 2nd-pass Protocol triggers 1+4)
acceptance_criteria:
  - Five files modified per brief §Step 2.3 (config/settings.py, triggers/waha_client.py, outputs/whatsapp_sender.py, triggers/sentinel_health.py:696, scripts/extract_whatsapp.py:475-476)
  - Fallback chain present in all 3 read paths (_headers, monitor_headers, whatsapp_sender) — load-bearing for rollback
  - _assert_waha_scoped_keys() try/except wrapped, checks all 3 scoped keys including MONITOR
  - sentinel_health.py:696 call-site edited, NOT line 695 (brief explicit on this — wrong line corrupts the import)
  - monitor_headers is public (no leading underscore)
  - py_compile clean on all 5 files
  - pytest green literal output captured in ship report
ship_gate: PR opened with green pytest output literally pasted, all 4 gates flagged readiness, AH1 owns post-merge Render env-var rotation as separate Tier-B
do_not_touch:
  - triggers/waha_webhook.py (webhook auth uses WAHA_WEBHOOK_SECRET, unrelated)
  - WAHA_BASE_URL (kill-switch lever — keep clean)
  - DIRECTOR_WHATSAPP / DIRECTOR_PHONE_ROOTS (recipient resolver constants)
  - migrations/ (no schema change in this brief)
  - tasks/lessons.md existing entries (append-only)
out_of_scope_hard_no:
  - Phase 1 Render image bump (AH1 ops)
  - Phase 2 Step 2.1 key provisioning via POST /api/keys (AH1 ops)
  - Phase 2 Step 2.4 Render env-var rotation (AH1 Tier-B post-merge)
  - WAHA MCP-server adoption (Director-ratified out-of-scope)
  - Query-param auth (?x-api-key=) introduction
---

# CODE_2_PENDING — BRIEF_WAHA_2026_4_UPGRADE_AND_KEY_SPLIT_1 — DISPATCHED 2026-05-12

## What to build

Phase 2 code PR only: 5-file diff per brief §"Fix/Feature 2 → Implementation Step 2.3".

The brief is two phases, but B2's scope is Phase 2 code only. Read the brief in full to understand context, but produce ONLY the code PR — do not attempt the Render image bump (Phase 1) or the env-var rotation (Step 2.4). Those are AH1-side ops actions.

## Anchors

- Brief: `briefs/BRIEF_WAHA_2026_4_UPGRADE_AND_KEY_SPLIT_1.md`
- Reviewer + architect pre-passes already folded into the brief (PASS-WITH-NITS → all nits folded before dispatch). Notable: rollback fallback chain is now MANDATORY in `_headers()` + `monitor_headers()` + `whatsapp_sender.py`; sentinel_health.py edit is at **line 696** (the call), NOT 695 (the import).
- Lessons applied: #45 (env-var silent drop → Step 2.4 verification AH1-side), #61 (probe third-party first → AH1 pre-flight), #63 (no public surface for ad-hoc send → Mac Mini SSH trigger documented).
- Trigger class TIER_B_AUTH_AND_EXTERNAL_PERIMETER fires code-reviewer 2nd-pass per SKILL.md (triggers 1 + 4: auth/scope + API keys).

## Branch + PR

- Create branch `feat/waha-2026-4-key-split` off `main`.
- PR title: `feat(waha): split admin key into 3 scoped keys with rollback fallback chain (BRIEF_WAHA_2026_4_UPGRADE_AND_KEY_SPLIT_1)`.
- PR body: copy the §"Files Modified" + §"Quality Checkpoints" sections from the brief, plus literal pytest output.

## Heartbeat cadence

Per SKILL.md §"B-code stall chase" — minimum 12h heartbeat while claimed/in_progress. Post via:
```
BAKER_ROLE=b2 ~/Desktop/baker-code/scripts/bus_post.sh lead "<status one-liner>" heartbeat/waha-2026-4-key-split
```

## Bus contract — required posts

- `orient/waha-2026-4-key-split` to `lead` on first session-start in this dispatch window (one-liner: brief read + branch checked out + no surprises).
- `heartbeat/waha-2026-4-key-split` to `lead` every 12h while building.
- `ship/waha-2026-4-key-split` to `lead` on PR open with link + commit SHA + gate readiness.
- `blocker/waha-2026-4-key-split` to `lead` if stuck (env, design Q, ambiguity).

## Out of scope (will be REQUEST_CHANGES if attempted)

- WAHA Render image bump (Phase 1 — AH1 ops)
- POST /api/keys provisioning (AH1 ops, runs the pre-flight + production provisioning)
- Render env-var rotation (AH1 Tier-B post-merge)
- WAHA MCP-server adoption (Director-ratified out-of-scope)
- Removing the legacy `api_key` fallback chain (separate fold-back PR after +7 days)
