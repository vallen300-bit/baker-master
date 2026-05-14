---
status: PENDING
brief: briefs/BRIEF_WORKER_SELFWAKE_PHASE_1.md
brief_id: WORKER_SELFWAKE_PHASE_1
trigger_class: TIER_B_AGENT_RUNTIME
dispatched_at: 2026-05-15
dispatched_by: ai-head-1 (AH1)
target: b2
redispatch_note: |
  Originally dispatched to b1 in mailbox commit e2aece9 on 2026-05-15.
  Redirected to b2 same day — Director: "b1 is busy". Build context moves
  to ~/bm-b2; install/probe targets (worker-b1 first, then b2-b4) unchanged
  per Director ratification 2026-05-14.
mandatory_2nd_pass: true
security_review_required: true
effort_estimate: ~2d (1d build + 1d test + plist install)
director_anchor: |
  Director-ratified 2026-05-14 (chat): Stage 3 Phase 1 (B1-B4 self-wake worker).
  Source spec: ~/baker-vault/_ops/ideas/2026-05-14-stage-3-worker-self-wake-design.md
  (commit 5c55767). Phasing approved Phase 1 only (B-codes); cadence 2 min;
  daily digest @ 09:00 UTC + immediate push on Tier B / failure; no veto window.
scope: |
  Build per-B-code launchd worker that polls brisen-lab bus every 120s, fires
  `claude --print` non-interactively in ~/bm-b{N} on new messages, enforces
  cost/rate/breaker caps, audits to baker_actions via new HTTP endpoints.
  Touches: baker-master (dashboard endpoint + migration + worker scripts) +
  local Mac filesystem (~/Library/Application Support/baker/, ~/Library/LaunchAgents/).
  NOT touched: bus_post.sh/py outbound, B-code CLAUDE.md, baker_actions columns.
hard_ship_gate: |
  1. Literal `pytest tests/test_worker_wake_audit.py tests/test_baker_worker.py -v`
     green output in ship report. NO "pass by inspection".
  2. Token-count probe documented (parsed real / constant approximation w/ rationale).
  3. Manual install + kickstart of worker-b1 produces clean log entry.
     (install target = b1's runtime; b2 is the BUILDER, not the first install target.)
  4. End-to-end probe: test bus message → worker fires ≤120s → claude session runs
     in ~/bm-b1 → message acked → baker_actions row written.
  5. Breaker / rate cap / cost cap each probed manually (3 simple tests with
     pre-seeded state.json).
  6. SessionStart hook updated to write wake.lock on interactive picker open
     (concurrent-picker collision mitigation per brief §Concurrent-picker collision).
gate_chain_post_ship: |
  After b2 bus-posts ship/WORKER_SELFWAKE_PHASE_1, AH1 fires:
  1. AH2 static review
  2. AH2 /security-review (mandatory — new automation surface + token handling)
  3. picker-architect review
  4. feature-dev:code-reviewer 2nd-pass (parallel, mandatory per SKILL.md triggers
     1+3+4+7: auth/token handling + concurrency-ordering primitive (wake.lock) +
     new external-surface endpoints + judgment "high-stakes")
  All 4 must clear before merge.
existing_branches: none (fresh branch)
prs_open: none (this is a new build)
ship_report_to: |
  Bus-post to `lead` with topic `ship/WORKER_SELFWAKE_PHASE_1`.
  Body: literal pytest output + token-probe outcome + 10 Quality Checkpoint
  results from brief §Quality Checkpoints + PR link + commit SHA + any
  open issues surfaced during build.
---

# Dispatch notice

Read first (in order):
1. `briefs/BRIEF_WORKER_SELFWAKE_PHASE_1.md` — full spec (this brief)
2. `~/baker-vault/_ops/ideas/2026-05-14-stage-3-worker-self-wake-design.md` — Director-facing 1-pager with the design context, phasing rationale, devil's-advocate counter-points
3. `~/baker-vault/_ops/processes/agent-bus-posting-contract.md` — bus transport reference (you'll use this for the ship-post)
4. `scripts/bus_post.sh` — sender pattern (your worker polls inbound; outbound stays via this)
5. `~/bm-b{1-4}/.claude/hooks/user-prompt-submit-confirm.py` — inbound drain hook (your worker triggers this indirectly via `claude --print`)

Pre-flight:
1. `cd ~/bm-b2 && git fetch origin && git checkout main && git pull --ff-only origin main`
2. `git checkout -b b2/worker-selfwake-phase-1`
3. Read the brief end-to-end before writing any code — token-count probe in §Token accounting probe is REQUIRED before ship (do it first; it informs `_parse_tokens()`).

Build discipline:
- Migration first: `migrations/20260515_worker_self_wake.sql` (single action class registration; no DDL).
- Dashboard endpoints next: `POST /api/worker/wake` + `GET /api/worker/digest` in `outputs/dashboard.py`. Run `grep -n "/api/worker" outputs/dashboard.py` BEFORE adding routes (FastAPI shadow check). Verify `get_db_connection()` actual function name via grep before referencing.
- Worker library: `scripts/baker_worker.py`. Token-count probe FIRST; then `_parse_tokens()` implementation.
- Daily digest: `scripts/worker_digest.py` + dashboard endpoint.
- Installer: `scripts/install_workers.sh` + 2 plist templates (parameterized over `b{N}` — first install target is b1's runtime, not b2's).
- Tests: `tests/test_worker_wake_audit.py` + `tests/test_baker_worker.py` — mock urllib + subprocess; literal pytest output captured.
- SessionStart hook update: write wake.lock on interactive picker open (touch the 4 b-code `session-start-role.sh` files, NOT AH1/AH2 ones).

Anti-pattern checks (from /write-brief lessons):
- Every DB query has LIMIT (brief specifies LIMIT 100 on digest query).
- Every except has `conn.rollback()` (brief shows pattern in `/api/worker/wake`).
- Column names match actual schema (no new columns; uses existing `tier`, `cost_eur`, `action_class`, `committer_agent`, `committed_at`, `self_cost_eur`).
- Function signatures verified (brief flags `get_db_connection` vs `_get_db_conn` — grep before use).
- No secrets in code (brief uses `op://` refs and `state_dir/key` file mode 0600).

End-of-work:
- Open PR on `b2/worker-selfwake-phase-1` against `main`. PR description includes Director anchor + 10 Quality Checkpoint outcomes + token-probe outcome.
- Bus-post to `lead` with topic `ship/WORKER_SELFWAKE_PHASE_1` per `ship_report_to` above.
- Do NOT merge yourself. Mandatory 4-gate chain runs first.
- Mailbox flip `CODE_2_PENDING.md` → `status: COMPLETE` only AFTER AH1 confirms merge.

Surface a `BLOCKED-AI-HEAD-Q` mailbox transition for anything ambiguous in the brief — don't guess on architecture or scope.
