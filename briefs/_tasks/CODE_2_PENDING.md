---
status: PENDING
brief_id: CORRELATION_ID_PRIMITIVE_1
to: b2
from: lead
dispatched_by: lead
dispatched_at: 2026-06-29
branch: correlation-id-primitive-1
reply_target: lead (bus)
effort: medium
task_class: small-feature — read-only correlation primitive (helpers + parser + one read-only resolver; no write / no migration / no deploy)
gate_plan: G1 py_compile + pytest fixtures green -> codex-arch 2nd-pair (parser strictness + resolver placement) -> codex G3 (effort medium; no-write assertion, never-raise, LIMIT 1, rollback) -> lead /security-review G4 (no secret/PII in parsed bodies, ReDoS-safe regex) -> lead merge -> NO deploy.
design_source: cowork-ah1 spec bus #4623 + outputs/correlation-id-primitive-spec.md; Director go via codex-arch #4625; folded by lead from cowork-ah1 dispatch-ready #4627.
---

# BRIEF: CORRELATION_ID_PRIMITIVE_1 — bus↔signal_queue thread-back identity (read-only)

## Context

The Baker bus has no `ticket_id`/`signal_id` field (schema = id/thread_id/parent_id/
topic/body only), so a desk reply cannot be tied back to the signal that triggered
it. This blocks the whole airport check-in loop (cowork-ah1 review #4612, Director-
accepted pivot #4620/#4625). This brief builds ONLY the minimal, read-only
correlation primitive: mint a stable id from `signal_queue.id`, carry it in the bus
topic slug, parse a one-line structured reply, and resolve it back to the signal row.
No SLA, no control, no writes. Spec source: cowork-ah1 #4623 +
`outputs/correlation-id-primitive-spec.md`.

## Estimated time: ~2–3h
## Complexity: Low
## Prerequisites: none (read-only; no migration, no env flip, no deploy)

## Context Contract
- **Owner:** Code Brisen (**b2**).
- **Task class:** small-feature — pure helpers + parser + one read-only resolver.
- **Interfaces:** `signal_queue` (read), bus topic/body conventions (string), the
  canonical DB connection in `kbl/db.py`.
- **Activation state:** library only; nothing calls it in prod yet (the future
  monitor/Dispatcher consumes it). No scheduler, no env, no deploy.
- **Authority:** read-only. No writes to any table. No Director messages, no sends.

### Surface contract: N/A — pure backend primitive (helpers + parser + read-only
resolver). No UI, no route, no dashboard card.

## Engineering Craft Gates
- Diagnose: N/A — net-new primitive, not a bug.
- Prototype: N/A — the format is locked by the spec; no design uncertainty.
- TDD/verification: **applies** — write the fixture tests for `corr_id` round-trip,
  topic extraction, and `CHECK_IN_VERDICT` parse FIRST (they are pure-string, no DB),
  then implement. The resolver is verified with a stubbed connection, not a live DB.

## Problem
No deterministic way to map a desk bus reply back to its originating signal. The id
must come from something that exists today (`signal_queue.id`) and ride a carrier
every sender can set (the topic slug — `bus_post.sh` sets only `topic`).

## Implementation — new module `kbl/correlation.py`

1. **Token mint/parse (pure):**
   ```python
   import re
   _SIG_RE = re.compile(r"sig-(\d+)")

   def corr_id(signal_id: int) -> str:
       return f"sig-{int(signal_id)}"

   def parse_corr_id(text: str) -> int | None:
       if not text:
           return None
       m = _SIG_RE.search(text)
       return int(m.group(1)) if m else None
   ```
   `parse_corr_id` works on either a topic (`checkin/<owner>/sig-123`) or a body;
   first match wins; `sig-abc` / no token → `None`.

2. **Topic builders (pure):**
   ```python
   def checkin_topic(owner_slug: str, signal_id: int) -> str:
       return f"checkin/{owner_slug}/{corr_id(signal_id)}"

   def checkin_reply_topic(owner_slug: str, signal_id: int) -> str:
       return f"checkin-reply/{owner_slug}/{corr_id(signal_id)}"
   ```

3. **Reply contract parser (pure, never-raise):** first body line is
   `CHECK_IN_VERDICT v1 sig=<id> outcome=<X> by=<slug>`.
   ```python
   _OUTCOMES = {"VALID","FAKE","DUPLICATE","WRONG_TERMINAL","NEEDS_LUGGAGE","CHECK_IN_MISSED"}

   def parse_checkin_verdict(body: str) -> dict | None:
       if not body:
           return None
       line = body.strip().splitlines()[0].strip()
       if not line.startswith("CHECK_IN_VERDICT v1"):
           return None
       kv = dict(re.findall(r"(\w+)=(\S+)", line))
       try:
           sig = int(kv.get("sig", ""))
       except ValueError:
           return None
       outcome = kv.get("outcome", "")
       if "sig" not in kv or outcome not in _OUTCOMES or "by" not in kv:
           return None
       return {"sig": sig, "outcome": outcome, "by": kv["by"]}
   ```
   Missing/garbled/unknown-outcome → `None` (caller treats as UNKNOWN). Never raises.

4. **Read-only resolver (the only DB touch):**
   ```python
   from kbl.db import get_conn  # use the canonical pooled connection helper

   def resolve_signal(signal_id: int) -> dict | None:
       conn = get_conn()
       try:
           with conn.cursor() as cur:
               cur.execute(
                   "SELECT id, status, matter_slug FROM signal_queue WHERE id=%s LIMIT 1",
                   (signal_id,),
               )
               row = cur.fetchone()
           if not row:
               return None
           return {"id": row[0], "status": row[1], "matter_slug": row[2]}
       except Exception:
           conn.rollback()
           return None
   ```
   Builder: confirm the exact `kbl/db.py` accessor name + cursor style (RealDict vs
   tuple) before finalizing; keep `LIMIT 1`, the try/except, and the rollback.

## Key Constraints (what NOT to change)
- **No writes.** `grep` the diff for INSERT/UPDATE/DELETE → must be zero.
- **No SLA / monitor / scheduler** — downstream (Dispatcher / BUILD-B), not here.
- **No `airport_tickets` coupling** — reserve the `at-<id>` token only; do not wire.
- **No dependency on `parent_id`** — topic slug is the floor carrier. (`bus_post.py`
  may also set `parent_id`, but this primitive must work without it.)
- **No bus-daemon / schema change** — existing `topic` + `body` only.

## Acceptance Tests — `tests/test_correlation.py` (fixtures, no DB/network)
1. `corr_id(123) == "sig-123"`.
2. `parse_corr_id("checkin/baden-baden-desk/sig-123") == 123`; `parse_corr_id("checkin-reply/x/sig-7")==7`; `parse_corr_id("no-token") is None`; `parse_corr_id("sig-abc") is None`.
3. `checkin_topic("ao-desk", 9) == "checkin/ao-desk/sig-9"`; reply variant mirrors.
4. `parse_checkin_verdict("CHECK_IN_VERDICT v1 sig=42 outcome=VALID by=baden-baden-desk\nfree prose")` → `{"sig":42,"outcome":"VALID","by":"baden-baden-desk"}`.
5. `parse_checkin_verdict` returns `None` for: wrong version (`v2`), missing `sig`, non-int `sig`, outcome not in enum, empty/None body — and NEVER raises.
6. `resolve_signal`: with a stubbed `get_conn` returning a row → dict; returning no
   row → `None`; raising on execute → `None` AND `rollback()` was called. SQL string
   contains `LIMIT 1`.

## Out of Scope (do NOT build)
SLA scheduler, monitor tick, escalation logic, `airport_tickets` wiring, desk-on-bus
install, `parent_id` enforcement, bus daemon changes, any `signal_queue` write, any
prod caller. This is the identity primitive only — everything else builds ON it later.

## Files
- NEW `kbl/correlation.py` — helpers + parser + read-only resolver.
- NEW `tests/test_correlation.py` — the 6 acceptance tests above.

## Gate Plan
1. cowork-ah1 / codex-arch second-pair on parser strictness + resolver placement.
2. codex G3 correctness/security (no-write assertion, never-raise, LIMIT 1, rollback).
3. AH1 `/security-review` G4 (no secret/PII in parsed bodies; ReDoS-safe regex).
4. No deploy — library lands on `main`, nothing calls it in prod yet.

## Reply
Ship report to **lead** via bus (`bus_post.sh lead "<SHIP ...>" "ship/correlation-id-primitive-1"`),
PR number + branch + commit, G1 self-check results, and the no-write grep result.
