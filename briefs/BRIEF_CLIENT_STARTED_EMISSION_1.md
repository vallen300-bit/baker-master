# BRIEF: CLIENT_STARTED_EMISSION_1 — client emits an explicit `started` signal on dispatch pickup

> **Companion / hard prerequisite of `CASE_ONE_BTUNE_STARTED_SLO_TERMINAL_1`.** That brief flips the obligation-closed judgment from `acked` to `started`; it CANNOT arm (`BRISEN_LAB_OBLIGATION_STARTED_TERMINAL=1`) until this brief is live, because today `started_at` is almost never set (367/487 delivery rows are acked-not-started). Owner: **b1** (owns the #557 client read-contract context). Lead #11076 named the dependency.

## Context
Deputy delivery-backlog triage arc (lead #11022 / #11076). The P5 delivery loop's terminal-success marker is `started_at` within the started-SLA (`db.py:673`). But `started_at` is written only by the daemon's **indirect inference** (`detect_delivery_started_sync`, `db.py:1269`): it marks started iff (1) a P2 `agent_jobs` row bound via `source_msg_id` has a heartbeat / non-`created`/`claimed` state, OR (2) the recipient posts a non-`ack` message on the dispatch's thread after `posted_at`. Most workers ack a dispatch but produce neither signal — so `started` never lands. The started-based SLO/obligation predicate the companion brief introduces therefore has no reliable signal to read.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: P5 delivery loop live (`brisen_lab_delivery` table + `POST /msg/<id>/ack` as the sole `acknowledged_at` write path, `bus.py:10`). `mark_delivery_started_sync` (`db.py:1183`) already exists as the write function — this brief adds a client-driven HTTP path to it.

## Baker Agent Vault Rails
Relevant rails: bus-and-lanes (dispatch pickup / drain path), verification-surfaces (delivery loop started detection).
Ignore unrelated rails: standing-contract, build-command-center, skills-and-playbooks, memory-and-lessons, loop-runner.

## Harness V2

**Task class:** feature (new client→daemon signal path) + small brisen-lab endpoint. Production (bus daemon + client drain scripts).

**Context Contract:**
- **Repos:** brisen-lab (new `POST /msg/<id>/started` endpoint → `mark_delivery_started_sync`) + baker-master (client drain/check-inbox path emits it). Two-repo, but each side independently deployable (client no-ops gracefully if the endpoint 404s during the rollout window).
- **Inputs:** existing `POST /msg/<id>/ack` endpoint (`bus.py:10`) as the shape template; `mark_delivery_started_sync(msg_id, recipient)` (`db.py:1183`, COALESCE + `escalated_at IS NULL` guarded — do not weaken); the client drain path (`scripts/check_inbox.sh`, `~/.claude/hooks/session-start-bus-drain.sh`).
- **Outputs:** an explicit, authenticated `started` write path fired by the recipient's own client when it picks up a **command-kind** dispatch into a live session.
- **Out of contract (do NOT touch):** the daemon inference `detect_delivery_started_sync` stays as a *fallback* (belt-and-suspenders — keep both); the ack endpoint; the escalation guard; Event-kind traffic (never emits started).
- **Semantic choice to resolve at G0 (surface, don't silently pick):** "pickup = started" (emit on drain) vs "first-action = started" (emit on first non-ack threaded reply / job-create). Lead #11076 said *pickup*. Trade-off to weigh: pickup-emission marks started for a dispatch a worker drains but then ignores, which **weakens E22 (ack-then-idle) escalation** (the started-SLA currently catches ack-then-idle — `bus.py:1360`). Recommendation: emit on pickup per lead, BUT keep the started-SLA→escalate path measuring *progress after started* via the existing job-heartbeat so a picked-up-then-abandoned dispatch still escalates on a **secondary** idle timer. b1 + codex to confirm the exact seam at G0.

**Done rubric / done-state class (deterministic):**
1. Unit (brisen-lab): `POST /msg/<id>/started` with the recipient's key sets `started_at` via `mark_delivery_started_sync`; idempotent (second call = no-op, COALESCE holds).
2. Unit: `POST /msg/<id>/started` from a NON-recipient key → 403 (scope check, mirror ack-endpoint auth).
3. Unit: endpoint respects the escalation guard — a started POST arriving after `escalated_at` set does NOT un-escalate (`db.py:1190-1196` invariant preserved).
4. Unit: Event-kind message → client never emits started (command-kind `execute_obligation=TRUE` only).
5. Unit (client): drain path, on surfacing a command-kind dispatch, POSTs started for that msg_id; on endpoint 404/5xx it logs + continues (non-fatal — rollout-window safe).
6. Suite: no new failures vs the 27-fail brisen-lab baseline; baker-master client tests green.
7. Live `POST_DEPLOY_AC_VERDICT`: after deploy, a real command-kind dispatch drained by a live worker shows `started_at` set within seconds of pickup (query below).

**Gate plan:** G0 codex-arch on the pickup-vs-first-action seam + E22 interaction → G1 b1 self-verify (rubric 1–6) → codex correctness → lead PASS → lead merges (brisen-lab endpoint first, then client) → Render deploy → **deputy** live drill + `POST_DEPLOY_AC_VERDICT`. Feeds the companion brief's Rollout ladder step 3.

---

## Fix 1: `POST /msg/<id>/started` endpoint (brisen-lab)

### Problem
No HTTP path writes `started_at` on demand; only the daemon control-tick infers it. Clients cannot signal "I picked this up."

### Current State
`POST /msg/<id>/ack` (`bus.py:10`, "NM3 sole acknowledged_at write path") is the template: resolves `X-Terminal-Key`→slug, scope-checks the caller is a recipient, calls the guarded `stamp_delivery_ack_sync`. `mark_delivery_started_sync` (`db.py:1183`) is the analogous started writer, already guarded.

### Engineering Craft Gates
- Diagnose: N/A — additive endpoint, no bug to reproduce.
- Prototype: N/A — shape is a proven mirror of the ack endpoint.
- TDD/verification: applies. First vertical test = rubric item 1 (recipient POST sets started_at); then the 403 (item 2) and escalation-guard (item 3) tests before wiring the client.

### Implementation
Add `POST /msg/<id>/started` mirroring the ack handler: resolve key → slug; verify slug ∈ `to_terminals` for the message (403 otherwise); verify `execute_obligation = TRUE` (command-kind; else 409/ignore — started is meaningless for Event-kind); call `mark_delivery_started_sync(msg_id, recipient)` inside `db_gate.db_call`. Return the `{ok|already_started|forbidden|not_command}` shape the ack endpoint uses. LIMIT on any lookup; `conn.rollback()` on except.

### Key Constraints
Do NOT remove `detect_delivery_started_sync` — keep the daemon inference as a fallback so a client that hasn't upgraded yet still gets started-detection. The two paths are idempotent (COALESCE), so double-marking is safe.

### Verification
Rubric items 1–4 + this SQL:
```sql
SELECT msg_id, recipient, acknowledged_at, started_at
FROM brisen_lab_delivery
WHERE started_at IS NOT NULL
ORDER BY started_at DESC LIMIT 20;
```

---

## Fix 2: client drain/pickup emits started (baker-master)

### Problem
The worker's client drains a command-kind dispatch but never tells the daemon it started.

### Current State
`scripts/check_inbox.sh` + `~/.claude/hooks/session-start-bus-drain.sh` surface unacked dispatches. Ack is a separate explicit `POST /msg/<id>/ack`. No started emission.

### Engineering Craft Gates
- Diagnose: applies (this is the root of the 367/487 gap). Feedback loop: drain a seeded command dispatch as a test slug, assert `started_at` lands. Hypothesis: no client emission path exists [confirmed].
- Prototype: N/A. TDD: rubric item 5 (drain emits; 404 non-fatal) is the first vertical test.

### Implementation
In the drain path, for each surfaced message where `execute_obligation = TRUE` (command-kind) addressed to this slug, fire `POST /msg/<id>/started` (best-effort: capture HTTP status; 404/5xx → log + continue, never block the drain — mirrors the #557 authoritative-read discipline b1 owns). Fire once per (msg,slug); dedupe within a drain so a re-drain doesn't spam (idempotent server-side anyway).

### Key Constraints
- Command-kind ONLY. Never emit started for Event-kind.
- Non-fatal on every failure path (a started-emit failure must not break inbox drain).
- No secret in scripts; reuse the existing `brisen_lab_read_terminal_key` credential path.

### Verification
Rubric item 5 + live: a real dispatch drained by a live worker shows `started_at` within seconds (Fix-1 SQL).

## Files Modified
- brisen-lab `app.py`/`bus.py` — new `POST /msg/<id>/started` route.
- baker-master `scripts/check_inbox.sh` + `~/.claude/hooks/session-start-bus-drain.sh` — started emission on command-kind pickup.
- tests both repos.

## Do NOT Touch
- `detect_delivery_started_sync` (keep as fallback), the ack endpoint, the `mark_delivery_started_sync` escalation guard, Event-kind paths.

## Quality Checkpoints
1. Recipient started-POST sets `started_at`; non-recipient → 403.
2. Escalation-guard invariant preserved (late started can't un-escalate).
3. Event-kind never emits/accepts started.
4. Client drain emits started on command-kind pickup; endpoint-absent = non-fatal.
5. Live acked-not-started population begins draining toward ~0 (feeds companion Rollout step 4 + rubric item 9).
6. No new failures vs baselines (both repos).

## Verification SQL
```sql
-- acked-not-started population should shrink after this ships
SELECT COUNT(*) FILTER (WHERE acknowledged_at IS NOT NULL AND started_at IS NULL) AS acked_not_started,
       COUNT(*) AS total
FROM brisen_lab_delivery
WHERE execute_obligation = TRUE AND deleted_at IS NULL
LIMIT 1;
```

## Routing
G0 codex-arch (pickup-vs-first-action + E22) → b1 builds → codex correctness → lead PASS → merge (endpoint then client) → deputy `POST_DEPLOY_AC_VERDICT`. Gates the `=1` flip in `CASE_ONE_BTUNE_STARTED_SLO_TERMINAL_1` Rollout step 5.
