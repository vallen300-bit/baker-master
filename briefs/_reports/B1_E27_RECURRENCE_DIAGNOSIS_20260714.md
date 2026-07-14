# B1 — E27 recurrence diagnosis (dispatch lead #10866)

**Task:** lead #10866 — E27 false-empty recurred post-#130. Dispatch #10860 (codex verdict,
to={lead}) was INVISIBLE to `scripts/check_inbox.sh` at 05:48Z ("no unacked messages") while a
direct browse `GET /msg/lead?...&full=true` showed it UNACKED. Diagnose, don't guess. Fix in a
fresh brief.

## Verdict
Root cause is NOT lead's (a) or (b). The daemon read path (my #130) is correct and live. The
false-empty re-surfaced one layer UP, in the **client** `check_inbox.sh`, which ignores HTTP
status and the `complete` flag and coerces a **503 `bus_busy_retry`** body into a false
"no unacked messages."

## Evidence (all captured, not inferred)
1. **Row #10860** (read-only DB, `brisen_lab_msg`): `to_terminals={lead}` (literal, NOT `*`),
   `acknowledged_at` was NULL at 05:48Z (acked 05:49:10Z), created 03:22Z. So at observation it
   genuinely matched the unread clauses (`'lead'=ANY(to_terminals)` AND `acknowledged_at IS NULL`).
2. **No pagination:** lead's unacked-as-of-05:48Z reconstruction = **1** total, **0** older than
   #10860. The unread page holds 1000 rows → overflow impossible. Ruled out.
3. **No deploy race:** merges #133/#134/#135 all landed by 23:16Z (07-13). Incident 05:48Z (07-14),
   ~6.5h later. Live daemon = e488f9d (#135), which contains #130. Confirmed live: the unread
   endpoint serves the fixed envelope (`complete` / `unacked_total` / `next_cursor` present).
4. **No stale client:** all `check_inbox.sh` copies (bm-b1/bm-b2/bm-aihead1/bm-aihead2) are
   byte-identical (same md5); `unread=true` landed 2026-07-11 (commit 7a20a65b), before the incident.
5. **Daemon read fail-closes correctly:** `db.get_conn` raises `BusPoolExhausted` on pool/stale
   contention → global handler → **503 `bus_busy_retry`**. There is NO code path that returns an
   empty-200 on a degraded read. #130's "degraded => 503, never silent empty" holds server-side.
6. **The client swallow (reproduced):** `check_inbox.sh` runs `curl -sS` (no `-f`, no status
   capture) and passes the body to `data.get("messages", [])`. Feeding the exact 503 body
   `{"detail":"bus_busy_retry"}` through its parser prints **"lead inbox: no unacked messages."**
   — a false all-clear. Any 4xx/5xx `{"detail":...}` body triggers the same.
7. **Trigger condition is live NOW:** my diagnostic write to the bus returned
   `HTTP 503 {"detail":"bus_busy_retry"}` after 4 retries — the bus is currently pool-contended,
   i.e. the exact state that makes check_inbox lie.

## Why lead's direct curl saw the row but check_inbox didn't
Same correct daemon. lead's browse curl hit a moment with a free pool slot (real 200 + row);
check_inbox's read hit a 503 during contention and rendered it as "no unacked." The discrepancy is
timing against a contended pool, decoded differently by two clients — one honest, one status-blind.

## Fix scope (for the fresh brief — NOT built here)
Client-side authoritative-read contract, mirroring #130's server envelope:
- `check_inbox.sh` must capture HTTP status; treat any non-200 (esp. 503 `bus_busy_retry`) as a
  loud ERROR / retry, NEVER as empty.
- Honor the envelope: report "no unacked" ONLY on a 200 with `complete: true`. A missing/`false`
  `complete`, or a body without a `messages` key, must not render as all-clear.
- Audit siblings for the same swallow: `read_bus_metadata.sh`, the SessionStart bus-drain hook,
  and any `data.get("messages", [])` reader.

Diagnosis only per dispatch. No code changed. Bus report posted to lead on topic
`case-one/e27-recurrence-diagnosis`.
