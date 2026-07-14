# BRIEF: CLIENT_STARTED_EMISSION_1 — client emits an explicit `started` signal on first action

> **AMENDED per G0 #11118 + lead ruling #11121 (2026-07-14).** Seam resolved to **first-action**, NOT
> pickup: codex G0 (#11107) showed `started` is the *terminal* delivery state (`mark_delivery_started_sync`
> sets `delivery_state=started` + `sla_state=delivered`, brisen-lab `db.py:1192-1200`), so pickup-emission
> would mark a picked-up-then-abandoned dispatch as *delivered*. Lead #11076's "pickup" wording is
> SUPERSEDED. `started` now fires on the recipient's **first non-ack post** tied to the dispatch (reply
> path), not on drain. Option B (new pickup state/schema) rejected — scope not justified. Two codex
> corrections folded in: (a) gate on `kind=dispatch`, not `execute_obligation` alone; (b) the client emit
> must NOT be added to the READ-ONLY `scripts/check_inbox.sh` (#557 contract). Fix-2 + rubric item 5 below
> are rewritten to this shape; deputy checks conformance at the correctness gate.

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
- **Semantic choice — RESOLVED at G0 (#11118 → lead ruling #11121): FIRST-ACTION.** "first-action = started" (emit on the recipient's first non-ack post tied to the dispatch), NOT "pickup = started" (emit on drain). Reason: `started` is the terminal delivery state (`sla_state=delivered`); emitting it on mere pickup would mark a picked-up-then-abandoned dispatch as delivered and corrupt the started-SLO the companion brief keys on. First outbound engagement is the honest, script-detectable "work began" signal; a BLOCKED report also counts as started (engagement happened; blocking escalates separately). No secondary E22 timer is added here — post-started monitoring would need its own state/query/alert contract (`list_open_delivery_records_sync` excludes `delivery_state=started`, `db.py:1312-1316`) and belongs to a separate companion, out of this brief's scope. Daemon inference (`detect_delivery_started_sync`) stays as fallback.

**Done rubric / done-state class (deterministic):**
1. Unit (brisen-lab): `POST /msg/<id>/started` with the recipient's key sets `started_at` via `mark_delivery_started_sync`; idempotent (second call = no-op, COALESCE holds).
2. Unit: `POST /msg/<id>/started` from a NON-recipient key → 403 (scope check, mirror ack-endpoint auth).
3. Unit: endpoint respects the escalation guard — a started POST arriving after `escalated_at` set does NOT un-escalate (`db.py:1190-1196` invariant preserved).
4. Unit: non-dispatch row → endpoint rejects (409/`not_dispatch`). Covers both Event-kind (`execute_obligation=FALSE`) AND `ratify_required` (`execute_obligation=TRUE` but `kind!='dispatch'`) — the codex-G0 scope correction. Only `kind='dispatch' AND execute_obligation` accepts started.
5. Unit (client): the **reply path** (`bus_post.sh` + codex reply scripts), when a role posts a non-ack message whose thread OR topic matches an inbound un-started `kind=dispatch` command it holds, POSTs `/started` for that msg_id once; a BLOCKED report counts as first-action; on endpoint 404/5xx it logs + continues (non-fatal — rollout-window safe). NOT wired into the READ-ONLY `check_inbox.sh`.
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
Add `POST /msg/<id>/started` mirroring the ack handler: resolve key → slug; verify slug ∈ `to_terminals` for the message (403 otherwise); verify the row is a **worker-start dispatch — `kind = 'dispatch'` AND `execute_obligation = TRUE`** (else 409/ignore). **Codex G0 #11107 correction:** gate on `kind='dispatch'`, NOT `execute_obligation` alone — `ratify_required` rows also carry `execute_obligation=true` (`bus.py:76-81`) but are not worker-start dispatches; P5 itself tracks only `kind=dispatch AND execute_obligation` (`bus.py:84-91`, `db.py:1316`). Then call `mark_delivery_started_sync(msg_id, recipient)` inside `db_gate.db_call`. Return the `{ok|already_started|forbidden|not_dispatch}` shape mirroring the ack endpoint. LIMIT on any lookup; `conn.rollback()` on except.

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

## Fix 2: client reply path emits started on first action (baker-master)

### Problem
A worker replies to a command-kind dispatch (its first outbound engagement = "work began") but never tells the daemon it started, so `started_at` stays null and the started-SLO has no signal.

### Current State
Outbound posts go through `scripts/bus_post.sh` (+ `bus_post.py`) and the codex reply helpers `scripts/codex-bus-reply.sh` / `scripts/codexarch-bus-reply.sh`. Replies to a dispatch carry `--parent <dispatch-msg-id>` (and/or a matching thread/topic). `scripts/check_inbox.sh` is the READ-ONLY drain surface (#557 contract, lines 19-24) and MUST NOT be modified. Ack is a separate explicit `POST /msg/<id>/ack`. No started emission exists anywhere on the client.

### Engineering Craft Gates
- Diagnose: applies (root of the 367/487 acked-not-started gap). Feedback loop: as a test slug, receive a seeded `kind=dispatch` command, post a non-ack reply, assert `started_at` lands. Hypothesis: no client first-action emission path exists [confirmed].
- Prototype: N/A. TDD: rubric item 5 (reply → started; ack-post does NOT; 404 non-fatal) is the first vertical test.

### Implementation
In the outbound reply path (`bus_post.sh` + the two codex reply helpers), after a **successful non-ack post**, if the post is tied to an inbound un-started `kind=dispatch` command held by this slug — matched by `--parent <dispatch-msg-id>` (primary, most direct signal) or a matching thread/topic — fire `POST /msg/<id>/started` for that dispatch msg_id, best-effort: capture HTTP status; 404/5xx → log + continue, never block or fail the post (mirrors the #557 authoritative-read discipline b1 owns). The endpoint is the authoritative gate (validates recipient + `kind=dispatch` + idempotent COALESCE), so an optimistic client fire for a non-qualifying parent is safely rejected (403/409) and ignored. Fire at most once per (msg,slug). A BLOCKED report is a non-ack post → counts as first-action/started (engagement happened; the block escalates on its own path).

### Key Constraints
- `kind=dispatch` command replies ONLY, and ONLY on **non-ack** outbound posts (an `ack` POST must NEVER trigger started — ack ≠ started is the whole point).
- Do NOT modify `scripts/check_inbox.sh` (READ-ONLY, #557). The emit lives in the outbound/reply path.
- Non-fatal on every failure path (a started-emit failure must not break or alter the outbound post's own result/exit code).
- No secret in scripts; reuse the existing `brisen_lab_read_terminal_key` credential path.

### Verification
Rubric item 5 + live: a real worker's first reply to a `kind=dispatch` command shows `started_at` set within seconds (Fix-1 SQL).

## Files Modified
- brisen-lab `app.py`/`bus.py` — new `POST /msg/<id>/started` route.
- baker-master `scripts/bus_post.sh` (+ `bus_post.py` for parity) + `scripts/codex-bus-reply.sh` + `scripts/codexarch-bus-reply.sh` — started emission on first non-ack `kind=dispatch` reply.
- tests both repos.

## Do NOT Touch
- `detect_delivery_started_sync` (keep as fallback), the ack endpoint, the `mark_delivery_started_sync` escalation guard, Event-kind paths.
- `scripts/check_inbox.sh` — READ-ONLY drain surface (#557 contract, lines 19-24). The client emit does NOT go here.
- The started-SLA / escalation path (`bus.py:1360`, `list_open_delivery_records_sync`) — no post-started monitoring added here (that's a separate companion; G0 #11118).

## Quality Checkpoints
1. Recipient started-POST sets `started_at`; non-recipient → 403.
2. Escalation-guard invariant preserved (late started can't un-escalate).
3. Event-kind never emits/accepts started.
4. Client reply path emits started on first non-ack `kind=dispatch` reply (never on an ack post, never from `check_inbox.sh`); endpoint-absent = non-fatal.
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
G0 ✅ DONE — routed to codex bus terminal (#11102), verdict REQUEST_CHANGES (#11107), resolved to first-action by lead ruling #11121 (#11118). → b1 builds (this branch) → codex correctness gate (deputy checks conformance to this amended shape) → lead PASS → merge (endpoint then client) → deputy `POST_DEPLOY_AC_VERDICT`. Gates the `=1` flip in `CASE_ONE_BTUNE_STARTED_SLO_TERMINAL_1` Rollout step 5.
