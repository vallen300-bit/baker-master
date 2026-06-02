---
dispatch: BRISEN_LAB_DB_CONN_HARDEN_1
to: b3
from: cowork-ah1
dispatched_by: cowork-ah1
status: PENDING
dispatched_at: 2026-06-01T14:40:00Z
authored: 2026-06-01
brief_path: briefs/BRIEF_BRISEN_LAB_DB_CONN_HARDEN_1.md
target_repo: brisen-lab
estimated_time: ~2.5h
complexity: Medium
brief_version: v2 — Codex G0 PASS-WITH-CHANGES (architect, 2026-06-01); all 6 changes folded
codex_pre_review: PASS-WITH-CHANGES (architect 2026-06-01) — direct-endpoint + budget check, robust host parse, connect/keepalive/tcp_user/statement timeouts, dead-conn recycle, PoolError to 503, tests
reply_to: cowork-ah1
ship_topic: ship/brisen-lab-db-conn-harden-1
anchor_chat: Director 2026-06-01 "follow your recommendations" + "b3 is free". Durable fix for the bus DB-hang. b1 busy (lead AUTOWAKE), b2 busy (English skill), routed to b3 per Director.
supersedes_mailbox: OPUS_4_8_UPGRADE_1 SHIPPED (PR #276, bus #1427, report B3_OPUS_4_8_UPGRADE_1_20260531.md) — b3 free per Director 2026-06-01; ship-state preserved in that report + bus #1427.
---

### Surface contract: N/A — pure backend (brisen-lab `db.py` connection layer). No user-clickable surface.

# b3 dispatch — BRISEN_LAB_DB_CONN_HARDEN_1

Read `briefs/BRIEF_BRISEN_LAB_DB_CONN_HARDEN_1.md` end-to-end before any code. **Target repo: brisen-lab** (use YOUR brisen-lab clone, e.g. `~/bm-b3-brisen-lab`). Brief paths written `~/bm-b1-brisen-lab/...` mean "your brisen-lab clone"; treat all file paths as repo-relative (`db.py`, `bus.py`/`app.py`, `tests/`).

Brief cleared **Codex G0 = PASS-WITH-CHANGES** (architect, 2026-06-01); all 6 changes already folded into v2. No further pre-write review required.

**Why this exists:** 2026-06-01 the bus daemon hung ~30-35s on every DB-backed endpoint after idle (reads/ACK/cards). Root cause = Neon autosuspend leaves a half-open pooled connection; `db.py` has no connect_timeout/keepalives/statement_timeout/liveness. Restart was the stopgap; this is the durable fix.

**Scope (db.py-centric, 4 parts + tests):**
- **Fix 0 (PREREQUISITE):** Neon connection-budget check BEFORE switching to DIRECT. Run `SHOW max_connections;` on the direct endpoint + `SELECT count(*) FROM pg_stat_activity;`. Confirm combined pools (brisen-lab 10 + baker-master store_back 5 + deadlines 3 + contact_writer 2) sit well under the limit. If margin thin or max_connections unexpectedly low → STOP, escalate to cowork-ah1.
- **Fix 1:** DSN → Neon DIRECT endpoint via ROBUST host parse (`urlsplit`, replace only the `-pooler` host segment, preserve userinfo/port/query — NOT naive `.replace`). Pool kwargs: `connect_timeout=5`, keepalives (1/30/10/3), `tcp_user_timeout=15000`, `options="-c statement_timeout=15000"` (DIRECT-only; pooled rejects startup options).
- **Fix 2:** `get_conn()` dead-connection recycle — bounded `SELECT 1` probe; on `conn.closed`/`psycopg2.Error` → `putconn(conn, close=True)` + fresh `getconn` (bounded by connect_timeout). Preserve commit/rollback/putconn semantics.
- **Fix 3:** wrap `pool.getconn()` → on `PoolError` raise `BusPoolExhausted`; register a handler returning **503** (never hang). Optional: bound `asyncio` default executor to `maxconn`.
- **Tests:** (1) direct-host conversion preserves user/pass/port/query + leaves already-direct unchanged; (2) pool built with the timeout/keepalive/options kwargs; (3) dead-conn recycle; (4) PoolError → 503.

**Constraints:** keep `maxconn=10` unless Fix 0 clears otherwise. Do not touch the bus.py request-handler logic or the secret-scrubber.

**Gates:** G1 (cowork-ah1 fold) → G3 (deputy) → **post-deploy AC MANDATORY** (`08-post-deploy-ac-bus-gate`): after idle ≥ Neon autosuspend window, a dead-socket query fails fast (<15s) and `/api/v2/terminals` + `/event/{id}/full` respond <2s. A green deploy is NOT proof. **G2 `/security-review` NOT required** (connection-layer only; Codex concurred).

**Ship:** open PR on `brisen-lab`; bus-post `ship/brisen-lab-db-conn-harden-1` to `cowork-ah1`. **Do NOT merge** (AH gate). Answer the done-rubric in the ship report (task class = infra reliability; terminal state = dead-socket-fast-fail verified).

**Note — companion fix queued separately:** the bus read-ordering defect (#1506, GET /msg oldest-first) is a SEPARATE brief, not in this scope. Do not touch the read-query here.
