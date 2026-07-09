# BRIEF: AGENT_WORK_QUEUE_V1 — Durable Postgres work queue for the agent fleet (DRAFT — dispatch gated)

**Status:** DRAFT for codex-arch G0 review. Build dispatch GATED behind current b1/b4 wave close (lead #8004 condition 2). Target repo: **brisen-lab** (NOT baker-master).

Harness-V2: task class = feature-build (production service change, brisen-lab) · Context Contract: this brief + brisen-lab origin/main (`db.py` bootstrap, `bus.py` `register`/`_post_msg_inner`/`post_daemon_message`, `auth_lab.py`/`authz.py` stack, `tests/` fixture conventions — re-verify all signatures at build time) + bus decision trail #7987 → #7993 → #8004 → #8050 → #8061 → #8066 + researcher note `wiki/research/2026-07-09-agent-fleet-work-control-substrate.md` · done rubric = §Verification per feature + §Quality Checkpoints 1-8; done-state class = **deployed-flag-off-soak-verified** (merged ≠ done; checkpoint 8 drill required) · gate plan: brisen-lab PR → codex bus G3 review (`reasoning_effort=medium`) → lead merge → Render deploy flag-off 24h soak → POST_DEPLOY_AC_VERDICT v1 on bus (seeded-failure drill = the AC) → lead flips `agent_queue_enabled` for hag pilot.

## Context

Bus dispatches double as work assignments today: read ≠ claim, ack is manual, and a message nobody claims is work nobody does. Director reports this as a daily failure. Lifecycle-403 floor (baker-master PR #507) fixed the unacked-pileup symptom; the read≠claim root cause remains.

Decision trail (all on bus): sacca proposal codex-arch #7987 → cowork-ah1 verdict PASS-WITH-NITS #7993 → **lead ratification #8004** (5 binding conditions) → researcher substrate note (codex relay #8050, full note `wiki/research/2026-07-09-agent-fleet-work-control-substrate.md`) → codex 10-block challenge #8061 → cowork-ah1 triage decisions #8066 → Director briefed 2026-07-09, pattern confirmed via codex: `agent_jobs` = truth, events = audit timeline, NOTIFY/wake = doorbell, Brisen Lab = cockpit.

**Ratified authority rule:** queue = work truth for queue-scoped lanes; bus = notification + audit; ClickUp = human view only. In V1 the queue is authoritative ONLY for the pilot desk (hag-desk); `briefs/_tasks/CODE_N_PENDING.md` mailbox and ClickUp Dispatcher lanes stay authoritative for their lanes until V2.

## Estimated time: ~9h
## Complexity: Medium-High
## G0 history: codex #8079 FAIL folded @rev2 — F1 row-verified dispatch guard (blocker), F2 session-heartbeat producer (new Feature 6), F3 xact-scoped advisory lock. Re-review requested.
## Prerequisites
- Current b1/b4 wave closed (lead confirms on bus before dispatch).
- brisen-lab checkout current with origin/main at build time — **re-verify every signature referenced below; this draft was written against origin/main @15fb160-era (2026-07-09) and the repo moves fast.**
- brisen-lab has **NO migrations/ dir** — schema goes in the inline bootstrap in `db.py` (established pattern, codex #3852 F2).

## Baker Agent Vault Rails
Relevant rails: bus-and-lanes (queue/bus authority split), verification-surfaces (seeded failure test, post-deploy AC), build-command-center (dispatch gating).
Ignored rails: skills-and-playbooks, memory-and-lessons, loop-runner — no changes to any of them in V1.

---

## Locked design decisions (do NOT relitigate in build — challenge at G0 only)

| # | Decision | Source |
|---|---|---|
| 1 | `agent_jobs` = single truth for queue-scoped work; no row = not queue-assigned | #8004 c1, #8066 |
| 2 | States: created → claimed → working → blocked → done → verified; + expired, dead. `done` self-set = ready-for-verification. `verified` never self-set. No `closed` in V1 | #8066 |
| 3 | Claim = ownership, atomic via `SELECT ... FOR UPDATE SKIP LOCKED`; assignment to ROLE slug; session recorded for audit | #8066, #8050 |
| 4 | Leases hybrid: wall-clock ceiling + session-aware heartbeat; next-wake latency acceptable; no real-time requirement | #8004 c5, #8066 |
| 5 | Queue write commits FIRST; bus mirror emitted after commit; bus failure never rolls back queue state | #8066 |
| 6 | Pilot = hag-desk only; enforcement flag default OFF; rollback = flag off, bus untouched | #8004 c3, #8066 |
| 7 | Bus stays fully functional; free-form posts legal; ACK semantics unchanged | #8066 |
| 8 | Tier-C/protected work representable only as `blocked` (`blocker='pending_director'`); queue never triggers execution | #8066 |

State movers: owner → claimed/working/blocked/done · sweeper → expired/dead · dispatcher (lead/AH seats/codex-arch) → created/verified/resurrect.

---

## Fix/Feature 1: Schema — `agent_jobs` + `agent_job_events` + kill switch

### Problem
No durable job table exists. `brisen_lab_msg` is an event store (append-only, no state machine, message-level `acknowledged_at` only — `POST /msg/<id>/ack` is the sole write path, NM3).

### Current State
`db.py` `SCHEMA_V2_SQL` bootstraps `brisen_lab_msg`, `brisen_lab_worker_authority`, `brisen_lab_session_keys`, `wake_events`, `brisen_lab_settings`, `refresh_requests` — all `CREATE TABLE IF NOT EXISTS`, idempotent, no migration runner. `refresh_requests` is the precedent for a dedicated auditable queue table.

### Engineering Craft Gates
- Diagnose: applies — symptom (silent work loss) already reproduced and audited (#7993, PR #507 trail). Feedback loop for the fix = seeded stale-job test (below): create → claim → kill heartbeat → observe expired → dead → RED alert. Pass/fail is binary.
- Prototype: N/A — SKIP-LOCKED job queue is an industry-standard, researcher-validated pattern (#8050: pg-boss, graphile-worker, River, DBOS); no design uncertainty left.
- TDD: applies — public interface = queue REST endpoints; FIRST test = two concurrent claims on one job → exactly one winner (live-PG pytest).

### Implementation
Append to the inline bootstrap in `db.py` (same style as `SCHEMA_V2_SQL`, run inside `bootstrap()`):

```sql
-- AGENT_WORK_QUEUE_V1 — durable work truth. Queue-scoped lanes only (V1: hag-desk pilot).
-- Bus stays notification+audit; this table is the ledger. Lead ratification bus #8004.
CREATE TABLE IF NOT EXISTS agent_jobs (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    spec TEXT,                              -- instructions or pointer (vault path / brief path)
    matter_slug TEXT,
    created_by TEXT NOT NULL,               -- creator role slug
    assigned_role TEXT NOT NULL,            -- role slug, NOT session (decision #3)
    claimed_by_session UUID,                -- audit only; ownership is assigned_role
    state TEXT NOT NULL DEFAULT 'created' CHECK (state IN (
        'created','claimed','working','blocked','done','verified','expired','dead'
    )),
    lease_until TIMESTAMPTZ,
    attempt_count INT NOT NULL DEFAULT 0,
    last_heartbeat TIMESTAMPTZ,
    blocker TEXT,                           -- required when state='blocked'
    proof_kind TEXT CHECK (proof_kind IN ('path','bus_msg','commit','pr','db_readout')),
    proof_ref TEXT,                         -- required with proof_kind when state='done'
    parent_job_id BIGINT REFERENCES agent_jobs(id),   -- single-level only in V1
    source_msg_id BIGINT REFERENCES brisen_lab_msg(id),
    tier_required TEXT CHECK (tier_required IN ('B','A','director_only')) DEFAULT 'B',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Claim scan: only claimable rows, per role.
CREATE INDEX IF NOT EXISTS idx_agent_jobs_claimable
    ON agent_jobs (assigned_role, id)
    WHERE state IN ('created','expired');
-- Sweeper scan: leased rows past expiry.
CREATE INDEX IF NOT EXISTS idx_agent_jobs_lease
    ON agent_jobs (lease_until)
    WHERE state IN ('claimed','working');
CREATE INDEX IF NOT EXISTS idx_agent_jobs_matter
    ON agent_jobs (matter_slug) WHERE matter_slug IS NOT NULL;

-- Transition audit (codex 'agent_events'). Append-only; one row per state change.
CREATE TABLE IF NOT EXISTS agent_job_events (
    id BIGSERIAL PRIMARY KEY,
    job_id BIGINT NOT NULL REFERENCES agent_jobs(id),
    from_state TEXT,
    to_state TEXT NOT NULL,
    actor_slug TEXT NOT NULL,
    session_id UUID,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_agent_job_events_job
    ON agent_job_events (job_id, id);
```

Kill switch rows in `brisen_lab_settings` (reader defaults, no insert needed):
- `agent_queue_enabled` — 'on'/'off', default-**off** when row missing (opposite default from `autowake_master_enabled` — mirror the `_read_master_flag_sync` pattern in `bus.py` but invert the missing-row default).
- `agent_queue_pilot_roles` — comma-separated slugs, V1 value `hag-desk`.

### Key Constraints
- CREATE IF NOT EXISTS + guarded ALTERs only — bootstrap must survive Render rolling deploys (two instances run it concurrently; existing precedent handles this).
- Done-row bloat: out of scope V1 (row volume tiny); note researcher recommendation (partition/rotation) in code comment for V2.

### Verification
```sql
SELECT column_name FROM information_schema.columns WHERE table_name='agent_jobs' LIMIT 30;
```

---

## Fix/Feature 2: Queue API — new `queue.py` module

### Problem
No claim/heartbeat/done/block surface exists; agents have no way to own work.

### Current State
`bus.py` exposes `register(app: FastAPI, broadcast_fn: Callable[[dict], None], terminals: set[str]) -> None` mounting all bus routes; auth via `ctx: CallerContext = Depends(authz(Policy.AUTH_ONLY))`; freeze gate via `freeze.is_v2_enabled()`; cross-module bus posting via `post_daemon_message(...)` (bus.py ~line 715). **Verify all four signatures at build time.**

### Engineering Craft Gates
- Diagnose: N/A — new capability (covered by Feature 1 loop).
- Prototype: N/A — same rationale as Feature 1.
- TDD: applies — tests below are written FIRST, one vertical test per endpoint group.

### Implementation
New module `queue.py` mirroring `bus.py` structure: `register(app, broadcast_fn, terminals)`, every endpoint behind `authz(Policy.AUTH_ONLY)` + freeze gate + `agent_queue_enabled` flag check (503 `queue_disabled` when off).

Endpoints (all writes in try/except with `conn.rollback()` in except; every SELECT has LIMIT):

1. `POST /jobs` — create. Creator authority: slug must be in dispatcher set {lead, cowork-ah1, deputy, codex-arch} OR `created_by == assigned_role` (desk self-tasking). Cross-agent assignment restricted to dispatcher set (decision trail #8066 block 8). Body: title, spec, assigned_role, matter_slug?, tier_required?, source_msg_id?, parent_job_id?. Inserts row (state='created') + `agent_job_events` row + bus mirror.
2. `POST /jobs/claim` — claim-next for caller's role:
   ```sql
   SELECT id FROM agent_jobs
    WHERE assigned_role = %(role)s AND state IN ('created','expired')
    ORDER BY id
    FOR UPDATE SKIP LOCKED
    LIMIT 1
   ```
   then in the SAME transaction `UPDATE ... SET state='claimed', claimed_by_session=%(sid)s, lease_until=NOW() + make_interval(hours => %(lease_h)s), last_heartbeat=NOW(), updated_at=NOW()`. Also `POST /jobs/{id}/claim` for a specific row (same guards: row must be claimable AND assigned to caller's role). Claim = ownership (decision #3); two concurrent claims are structurally impossible — SKIP LOCKED means the loser sees no row.
3. `POST /jobs/{id}/heartbeat` — caller role must equal assigned_role and state IN ('claimed','working'); sets last_heartbeat=NOW(), extends lease_until to NOW()+lease_h (ceiling: never beyond NOW()+48h), optional state bump claimed→working.
4. `POST /jobs/{id}/done` — owner only; REQUIRES proof_kind + proof_ref (400 without); state→'done'. `done` MEANS ready-for-verification.
5. `POST /jobs/{id}/block` — owner only; REQUIRES blocker text; state→'blocked'. Tier-C representation: `blocker='pending_director'`.
6. `POST /jobs/{id}/verify` — dispatcher set only AND `ctx.slug != assigned_role` (server-enforced never-self-verify); state done→'verified'. Also `POST /jobs/{id}/resurrect` — dispatcher set only; dead/expired→'created', resets lease fields, attempt_count preserved.
7. `GET /jobs?role=&state=&matter=&limit=` — filtered list, default LIMIT 50, max 200.

Every state change: (a) UPDATE agent_jobs + INSERT agent_job_events in one transaction, commit; (b) THEN bus mirror via `post_daemon_message` (topic `queue/<job_id>/<to_state>`, kind='dispatch' for assignment notification to the assigned role, kind='alert' for dead) wrapped in its own try/except — bus failure logs and never unwinds the queue write (decision #5).

Lease default: `lease_h = 24` (wall-clock ceiling generous vs wake cadence — session-based agents, decision #4). Configurable via `brisen_lab_settings` key `agent_queue_lease_hours`, missing-row default 24.

### Key Constraints
- Single-writer rule: ONLY `queue.py` endpoints write `agent_jobs`/`agent_job_events`. No other module, no direct SQL from baker-master.
- No new auth scheme — existing X-Terminal-Key / session-key stack as-is.
- ACK endpoint untouched; ACKs remain for non-queue bus traffic; claim supersedes ack for queue jobs only.

### Verification
pytest (live PG, `TEST_DATABASE_URL`-style skip guard matching existing brisen-lab tests/ conventions — verify the fixture pattern at build time):
- `test_concurrent_claim_single_winner` — two parallel claim calls, one job → exactly one 200-with-row, other gets empty.
- `test_done_requires_proof` — done without proof_ref → 400.
- `test_verify_never_self` — verify by assigned_role slug → 403.
- `test_bus_mirror_failure_keeps_queue_state` — monkeypatch post_daemon_message to raise; done still commits.

---

## Fix/Feature 3: Lease sweeper

### Problem
Without a sweeper, an expired lease is just a stale timestamp — silent loss returns.

### Current State
`app.py` runs background loops (verify the existing asyncio-task startup pattern at build time). Advisory-lock precedent exists in baker-master lessons (concurrent startup tasks anti-pattern) — brisen-lab deploys also roll two instances.

### Engineering Craft Gates
- Diagnose: applies — the seeded stale-job test IS the feedback loop.
- Prototype: N/A. TDD: applies — sweep test below written first.

### Implementation
Async loop in `queue.py`, started from `app.py` startup, every 10 minutes. Single-instance guard: **`pg_try_advisory_xact_lock` (constant lock id, e.g. 780091) inside ONE transaction** — matches existing brisen-lab precedent (db.py ~215-230); lock auto-releases at commit/rollback, so a pooled connection can never wedge holding a session-level lock (codex G0 #8079 Finding 3). Sweep body:

1. **Stalled seat** (expire): `UPDATE agent_jobs SET state='expired', attempt_count=attempt_count+1, updated_at=NOW() WHERE state IN ('claimed','working') AND lease_until < NOW() AND (last_heartbeat IS NULL OR last_heartbeat < NOW() - INTERVAL '60 minutes') RETURNING id, attempt_count` (+ events rows).
2. **Slow seat** (alert only, per lead #8004 c5 stalled-vs-slow distinction): rows with `lease_until < NOW()` but a heartbeat within 60 min are NOT expired — emit one amber `kind='alert'` bus post per job to the dispatcher set ("lease expired, seat alive — verify progress"), throttled to one alert per job per sweep-day (track via events table lookup).
3. Dead: expired rows reaching `attempt_count >= 2` → `state='dead'` + events row + bus `kind='alert'` post naming job id, title, owner, attempts (RED path — no reliance on Director noticing silence).
4. Expired-but-not-dead rows stay claimable (`state='expired'` is in the claimable set) — auto-requeue by definition.

Retryable vs human blocker: lease expiry/no-heartbeat = retryable (sweeper handles); `blocked` = human, sweeper NEVER touches blocked rows.

### Verification
- `test_sweeper_expires_and_deadletters` — seed job with lease_until in the past, no recent heartbeat, attempt_count=1 → run sweep fn directly → state='dead', alert row exists in brisen_lab_msg.
- `test_sweeper_slow_seat_not_expired` — lease past, heartbeat 5 min ago → state unchanged, amber alert emitted.
- `test_two_sweepers_no_wedge` — run sweep fn on two connections concurrently → one sweeps, one no-ops, both connections reusable afterward (xact lock released).
- Staging seeded failure drill (Quality Checkpoint 8).

---

## Fix/Feature 6: Session-heartbeat wiring (heartbeat producer)

### Problem
Locked decision #4 promises session-aware leases, but Features 2-3 alone give only a manual `POST /jobs/{id}/heartbeat` no agent will reliably call — the sweeper would expire jobs under live seats (codex G0 #8079 Finding 2).

### Current State
brisen-lab already receives a per-session ticker at `/api/heartbeat` roughly every 45s (app.py ~700-705 — verify exact handler + slug field at build time).

### Engineering Craft Gates
Diagnose/Prototype: N/A — wiring, not new design. TDD: applies — one vertical test.

### Implementation
In the existing `/api/heartbeat` handler, AFTER its current work, when `agent_queue_enabled='on'`: fire-and-forget `UPDATE agent_jobs SET last_heartbeat = NOW() WHERE assigned_role = %(slug)s AND state IN ('claimed','working')` (own try/except + rollback; failure logs, never affects the heartbeat response). No lease extension here — session alive proves the SEAT is alive (slow seat), not that the JOB progresses; only explicit `POST /jobs/{id}/heartbeat` or state changes extend `lease_until`. This is exactly the stalled-vs-slow split lead required (#8004 c5): dead session → no last_heartbeat → sweeper expires (stalled); live session past lease → amber alert, no expiry (slow).

### Key Constraints
- Zero added latency budget on `/api/heartbeat` beyond one indexed UPDATE; must not raise.
- No new endpoint; no agent-side changes required for the pilot.

### Verification
- `test_session_heartbeat_touches_active_jobs` — seed claimed job for slug, call handler → last_heartbeat updated; verified/dead rows untouched.
- `test_session_heartbeat_queue_off_noop` — flag off → no UPDATE issued.

---

## Fix/Feature 4: Dispatch-warning hook for pilot desk (warn-only)

### Problem
During pilot, a bus dispatch to hag-desk without a queue row recreates the old failure mode invisibly.

### Current State
`_post_msg_inner` (bus.py ~line 802) handles all posts.

### Engineering Craft Gates
Diagnose/Prototype: N/A — trivial guard. TDD: applies — one test.

### Implementation
In `_post_msg_inner`, AFTER successful insert, when `kind='dispatch'` AND recipient in `agent_queue_pilot_roles` AND `agent_queue_enabled='on'`, run the **row-verified guard** (codex G0 #8079 Finding 1 — text-matching alone is spoofable by "job 999"):

1. Extract a job reference: explicit `queue_job_id` field in the POST payload (preferred; document in bus_post conventions) OR a `/jobs/<id>` token in the body. Bare "job N" prose does NOT count.
2. If no reference → warn.
3. If reference found → `SELECT id, assigned_role, state FROM agent_jobs WHERE id = %(id)s LIMIT 1` and warn unless ALL hold: row exists, `assigned_role` = recipient slug, `state NOT IN ('verified','dead')`.
4. Warn = include `"queue_warning": "<reason: no_job_ref|job_not_found|wrong_role|terminal_state>"` in the response JSON + emit audit bus post (kind='alert', to dispatcher set) — **no reject, no auto-create in V1** (#8066 block 6). Existing response shape otherwise byte-identical (posters parse it). Guard SELECT failure (DB error) → log + skip warning, never block the post.

### Verification
Seeded tests, one per guard outcome (codex G0 required set):
- `test_pilot_dispatch_no_ref_warns` (incl. spoof case: body says "job 999", no payload field, no `/jobs/` token → warns)
- `test_pilot_dispatch_job_not_found_warns`
- `test_pilot_dispatch_wrong_role_warns`
- `test_pilot_dispatch_terminal_state_warns`
- `test_pilot_dispatch_valid_job_clean`
- `test_nonpilot_dispatch_unaffected`

---

## Fix/Feature 5: Brisen Lab minimal visibility

### Problem
Director must SEE stale/dead work — RED by construction, not by silence.

### Surface contract
- Surface: Brisen Lab dashboard (`static/`), existing card grid + one new drawer.
- New: (a) per-card RED badge count = dead+expired jobs where assigned_role=card slug; (b) "Jobs" drawer listing agent_jobs (title, state, owner, lease age, proof link) via `GET /jobs`, default filter state NOT IN ('verified').
- NOT touched: card wake/state logic (LOCKED design — Option C bevel, 3×2 grid, canonical mockup `outputs/mockups/brisen-lab-dashboard-layout-v2.html`), SSE plumbing, history drawer.
- Cache bust: bump `?v=N` on touched static assets (iOS PWA).
- Director click-through to full job detail + bus thread = V2 (deferred, #8066 block 7).

### Engineering Craft Gates
Diagnose/Prototype: N/A — minimal read-only UI. TDD: N/A honest seam — manual mobile+desktop render check (Quality Checkpoint 6); no JS test harness exists in brisen-lab.

### Verification
Badge shows seeded dead job within one refresh cycle; drawer renders on iPhone viewport.

---

## Files Modified (ALL in brisen-lab repo)
- `db.py` — bootstrap DDL append (agent_jobs, agent_job_events, indexes)
- `queue.py` — NEW: endpoints + sweeper
- `app.py` — mount queue.register(...), start sweeper task, session-heartbeat → job touch (Feature 6)
- `bus.py` — row-verified dispatch-warning hook only (minimal diff inside `_post_msg_inner`)
- `static/` — RED badge + jobs drawer (+ `?v=N` bump)
- `tests/test_agent_queue.py` — NEW

## Do NOT Touch
- `auth_lab.py` / `authz.py` — auth stack unchanged
- ACK path (`POST /msg/<id>/ack` NM3 sole-write invariant)
- Card wake/state logic + locked card design
- `baker-master` repo entirely; `briefs/_tasks/CODE_N_PENDING.md` mailbox; ClickUp lanes (authoritative until V2)
- `wake_events`, `refresh_requests`, session-key tables

## Quality Checkpoints
1. Two concurrent claims → exactly one winner (live-PG test green).
2. Sweeper runs on exactly one instance (advisory lock; check logs across both Render instances).
3. Bus-mirror failure does not roll back a queue write (test green).
4. `done` without proof → 400; self-verify → 403.
5. `agent_queue_enabled` missing/off → every /jobs endpoint 503s, zero behavior change anywhere else (regression: existing bus tests all green).
6. Badge + drawer render on desktop AND iPhone PWA; `?v=N` bumped.
7. Bootstrap idempotent across a Render rolling deploy (two instances, no duplicate-object errors).
8. Staging seeded-failure drill: create → claim → kill session (no heartbeat) → expired (attempt 1) → expired (attempt 2) → dead + RED alert bus post received by dispatcher set.
9. Dispatch guard: all six seeded outcomes green, incl. "job 999" spoof → warns (G0 #8079 F1).
10. Two concurrent sweepers: no wedge, connections reusable (xact-lock test green, G0 #8079 F3).
11. Live seat past lease → amber alert, NOT expired; dead seat → expired (stalled-vs-slow, #8004 c5).

## Verification SQL
```sql
SELECT state, COUNT(*) FROM agent_jobs GROUP BY state ORDER BY state LIMIT 20;
SELECT job_id, from_state, to_state, actor_slug, created_at
  FROM agent_job_events ORDER BY id DESC LIMIT 20;
SELECT id, topic, kind, created_at FROM brisen_lab_msg
 WHERE topic LIKE 'queue/%' ORDER BY id DESC LIMIT 20;
```

## Pilot & rollout (post-build, lead-owned)
1. Deploy with `agent_queue_enabled` off → zero-change soak, 24h.
2. Flag on, pilot_roles='hag-desk'; seeded-failure drill in prod (checkpoint 8).
3. Two weeks clean (zero silent-loss incidents, Director cockpit acceptable) → MOVIE/AO onboarding decision (lead + Director).
4. Rollback at any point = flag off; bus wholly unaffected; tables stay (non-destructive).

## Cost impact
Zero LLM calls. Marginal Postgres storage (< a few hundred rows/month at fleet scale per researcher #8050). One 10-min background loop.
