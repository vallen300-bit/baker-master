# B3 — EMAIL_STORE_NEON_SSL_RCA_1 — diagnosis report (2026-06-10)

**Brief:** EMAIL_STORE_NEON_SSL_RCA_1 (bus #2798, dispatched 10:17Z)
**Lane:** diagnosis only — no code changes made.
**Verdict class:** root cause named with log evidence + live repro (AC1 met).

## Verdict (AC1)

Two distinct failure modes share the "SSL connection has been closed unexpectedly" / degraded-store symptom. Both root-caused with evidence.

### Failure mode A — stale shared retriever connection (deputy's incident class)

`SentinelRetriever._get_pg_conn()` (`memory/retriever.py:680`) is a **single cached psycopg2 connection** (misleadingly named `_pg_pool`), shared by ALL retriever reads AND `baker_email_search provider=store` (`tools/email.py:_run_email_query`). It connects via `config.postgres.dsn_params` to the **Neon pooler endpoint** (`POSTGRES_HOST=ep-summer-sun-aih7ha4h-pooler...`, confirmed via Render env API) with **no TCP keepalives and no stale-conn recycle** — only `direct_dsn_params` got the SCHEDULER_NEON_IDLE_HARDEN_1 keepalive treatment (`config/settings.py:353-360`; the pooled `dsn_params` at `:323-334` has none).

Sequence: connection idles > Neon idle cutoff → Neon/pgbouncer closes it server-side → the NEXT caller eats one `SSL connection has been closed unexpectedly` failure → `_reset_pg_conn()` drops it → the call after that succeeds on a fresh connection.

**Evidence:**
- 45 SSL-closed events in 23h (2026-06-09T12:19 → 06-10T10:12), steady ~2/hr day and night, load-independent — idle-timeout signature, NOT load (Render log grep, `/tmp/rca_ssl_24h.json`). 43× `sentinel.retriever`, 3× `baker.tools.email` (10:12:52, 10:12:57, 10:28:48).
- **Live repro during this lane:** probe at 10:28:48Z → `backend_unavailable: true, "SSL connection has been closed unexpectedly"`; immediate retry ~60s later → `match_count: 3` (Spanyi mails returned). Fail-once-then-heal confirmed end-to-end on the prod MCP surface.
- The 10:12:52 + 10:12:57 double failure (back-to-back resets failing) coincides with a Neon pooler recycle: `pg_stat_activity` at 10:23Z showed every pgbouncer-side backend started 10:14Z or later.
- Same signature as the 2026-06-01 arc (bus #1500/#1503 — not readable from b3, not-party; cited per brief).
- Deputy's exact ~08:35Z call is NOT in dashboard logs (no `email store backend unavailable` line 07:00–10:00 except the three above). Nearest same-class event: 08:42:31 `sentinel.retriever` SSL-closed (contact lookup leg, same shared conn). His timestamps may be approximate; the mechanism is proven by the live repro regardless. Note 08:34:42–08:44:25 was also a deploy window (6 deploys 08:23–09:27 this morning, each restarting the service).

### Failure mode B — app-side pool exhaustion at 5-min poll ticks (ongoing, started 09:33:45Z today)

`SentinelStoreBack` ThreadedConnectionPool is `maxconn=5` (`memory/store_back.py:306-310`). At every 5-min scheduler tick, `graph_mail_poll` + bluewin poller + `email_poll` + `tier_b_reservation_sweep` + clerk poll run concurrently; with per-message `trigger_state.is_processed()` checks each doing getconn/putconn, concurrent demand exceeds 5 → psycopg2 raises `connection pool exhausted` immediately (non-blocking pool).

**Evidence:**
- First flood 09:33:45.567Z; recurring at every 5-min tick since (09:58 ×44, 10:03, 10:08, 10:13, 10:18, 10:23 ×16 — still live at lane close). ZERO occurrences outside tick minutes → bursty contention, NOT a permanent leak: a `Cursor updated for graph_mail_poll` write succeeded at 09:33:48, 3s after the flood.
- Amplifiers today: (1) Gemini 503 outage (09:16–09:35+ log-confirmed) stretching email-pipeline jobs; (2) backfill volume — bluewin backfill (started 09:24Z) inserted 3,230 rows in the 09:00h + 2,988 in the 10:00h; b2 graph lane +504.
- **Correctness hazard:** on exhaustion, `trigger_state.is_processed()` fails OPEN — `"No pooled DB connection — assuming not processed"` (`triggers/state.py:467`) → items can be re-processed (duplicate ingest + duplicate LLM spend) on the next tick.

## Backfill-pressure answer (AC2)

**Does pid-4177 backfill load correlate with store failures? Indirect-only — and it is NOT the original trigger.**
- Failure mode A pre-dates the backfill by ≥22h (events from 06-09T12:19; deputy's repro 08:35Z vs backfill start 09:24Z). Backfill is exonerated for the Director-impacting incident.
- Failure mode B started 09:33:45Z, 10 min after backfill inserts began — temporal correlation yes, but the mechanism is app-side: backfill writes go direct Mac→Neon on its own 1–2 connections and never touch the dashboard pool. Neon server is comfortable: only **8 backends total** at 10:23Z snapshot, no saturation. The backfill's contribution is more rows/work per poll tick, tightening the already-undersized 5-conn pool. No backfill throttle needed from Neon's side.

## Proposed fix (AC3 — for lead to brief separately; no code this lane)

1. **Harden the pooled-path connections** (root fix for mode A): add the same keepalive params to `dsn_params` that `direct_dsn_params` already has, AND retry-once-on-stale inside `_run_email_query`/retriever conn use (reset + single in-call retry makes the idle-kill invisible to callers — today the first caller after every idle gap eats a failure).
2. **Resize/absorb tick contention** (mode B): raise store_back pool `maxconn` 5→~15 (Neon pooler multiplexes; server showed 8 backends — ample headroom) and/or add a short bounded getconn retry. Optional: stagger the 300s jobs (offset start seconds) so ticks don't align.
3. **Close the fail-open dedup hole:** `is_processed()` returning False on pool failure should instead fail CLOSED (skip item this tick; next tick retries) — prevents duplicate processing + duplicate LLM cost during exhaustion windows.

## Live watch (verification block)

3 store probes against prod `POST /mcp` `baker_email_search provider=store q=Spanyi`, spaced ~10 min, during active backfill:

| probe | time (UTC) | result |
|---|---|---|
| 1 | 10:28:48 | FAIL — backend_unavailable, SSL-closed (then immediate retry 10:29 → PASS, match_count=3) |
| 2 | 10:39:55 | PASS — match_count=3, no backend_unavailable |
| 3 | 10:49:57 | PASS — match_count=3, no backend_unavailable |

Net: 1 fail / 3 passes while the bluewin backfill ran at full rate (6,069/33,687 done at 10:30Z) — store works whenever the shared conn is warm; the only failure was the first call after an idle gap. Confirms mode A (idle-kill) and confirms the backfill does not break the store path under load.

## Artifacts

- /tmp/rca_ssl_24h.json, /tmp/rca_ssl_window1.json, /tmp/rca_pre_exhaust.json, /tmp/rca_probes.log, /tmp/rca_probe_raw*.json (local to b3 Mac)
- pg_stat_activity snapshot 10:23:59Z (in-session, reproduced in verdict above)
