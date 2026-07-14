# B1 ship report — CLIENT_AUTHORITATIVE_READ_CONTRACT_1

**Dispatch:** lead #10901 (accepted my E27 recurrence diagnosis #10889). Implement the named
fix scope: bus-read clients must be HTTP-status-aware + `complete`-aware so a 503
`bus_busy_retry` (or any non-200) can never render as a false "no unacked messages".

**Branch:** `b1/client-authoritative-read-contract-1` (off fresh origin/main)
**Repo:** baker-master (client scripts + test)
**Gate plan:** G1 (this) → codex → lead merge.

## Root cause (from diagnosis #10889)
#130 moved the E27 false-empty OUT of the daemon: a degraded read now fail-closes to HTTP 503
(`db.get_conn` → `BusPoolExhausted` → 503; no empty-200 path). But the CLIENT `check_inbox.sh`
ran `curl -sS` with no status check and did `data.get("messages", [])`, so a 503 body
`{"detail":"bus_busy_retry"}` → `[]` → "no unacked messages". The false-empty re-surfaced one
layer up. Two codex sibling readers shared the identical swallow.

## Changes
- **scripts/check_inbox.sh** — capture HTTP status via `curl -w '\n%{http_code}'`; non-200 =
  LOUD error (surfaces the daemon `detail`), never empty; bounded retry on transient
  transport-fail / 5xx / 429; claim "no unacked messages" ONLY on 200 AND `complete:true`;
  `complete:false` → PARTIAL warning (exit 5), not an all-clear. Defensive python double-guard
  on a detail-only body. Retry knobs env-overridable (`CHECK_INBOX_RETRY_MAX/SLEEP`) for tests.
- **scripts/check-codex-inbox.sh** / **scripts/check-codexarch-inbox.sh** — same status-aware
  fetch + retry + `complete`-guard (their swallow printed "empty (no dispatches)").
- **tests/test_check_inbox_authoritative_read.py** — new pytest; the 503 reproduction is the
  load-bearing test. Stubs `curl` on PATH (no network). 6 cases: 503 busy, 4xx error body,
  transport failure, 200+complete empty (all-clear), 200+incomplete (NOT all-clear), 200 with
  a real unacked row (renders).

## Audit of the other named readers (fail-loud already — no change)
- **read_bus_metadata.sh** — `curl -fsS` + `set -euo pipefail`: a 503 makes curl exit non-zero
  → script fails loud. Not vulnerable to the silent swallow.
- **bus-drain hook** (`tests/fixtures/session-start-bus-drain.sh`, deployed `~/.claude/hooks/`)
  — already guards the error body (`"detail" in d and "messages" not in d → "daemon error …
  skipping"`, lines 274–276), so a 503 is surfaced, not swallowed. I did NOT change it: the
  only remaining hardening (a `complete:false` partial note on empty) would couple this PR to a
  Director cp-deploy of the user-global copy and break the drift test until then — out of
  proportion to the named swallow, which the hook already handles. Flagged as an optional
  follow-up if lead wants end-to-end `complete`-awareness there too.
- **ack_dispatch_msgs.sh** — already captures HTTP status. Not vulnerable.

## Done rubric
- [x] The 503/4xx/transport case is LOUD (non-zero exit) and never prints an all-clear — proven
      by pytest (`test_503_busy_is_loud_never_empty`) and a live-stub smoke on both codex siblings.
- [x] "No unacked" claimed ONLY on 200 + `complete:true`.
- [x] Happy paths preserved (200 empty → all-clear; 200 with unacked → renders) — pytest + live
      run against the real daemon (`b1 inbox: no unacked messages.`, exit 0).
- [x] `bash -n` clean on all edited scripts.

## Tests
- `pytest tests/test_check_inbox_authoritative_read.py` — 6 passed.
- `pytest tests/test_bus_drain_hook.py` — 16 passed (fixture unchanged; drift test green).
- `bash tests/test_check_inbox_unread_param.sh` — PASS (unread=true still sent on both branches).
- Live: fixed `check_inbox.sh` against the real daemon → correct 200 all-clear; codex siblings
  under a simulated 503 → exit 4, no false all-clear.

## Harness V2
Client-script + test change; not a production-facing Baker/Render deploy → no
`POST_DEPLOY_AC_VERDICT` applies. The load-bearing test IS the acceptance check.
