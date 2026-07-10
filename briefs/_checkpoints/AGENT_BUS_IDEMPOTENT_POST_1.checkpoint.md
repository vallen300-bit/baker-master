---
brief_id: AGENT_BUS_IDEMPOTENT_POST_1
attempt: 1
status: CLOSED — codex-medium PASS #8389 (3 rounds); both PRs merged (baker-master #514 @d8b522be + brisen-lab #111 @053a7c77); brisen-lab deployed live ~07:00Z; live prod AC PASS; POST_DEPLOY_AC_VERDICT v1 posted lead #8410. Brief DONE end-to-end. Nothing owed.
repos: MERGED — brisen-lab PR #111 @053a7c77 + baker-master PR #514 @d8b522be (both on main)
dispatched_by: lead (#8362, 2026-07-10T06:11Z); re-scoped lead #8366 (C+B ratified)
codex_rounds: R1 #8373 (py socket.timeout retry P1 + empty-key P2) -> 22fdab91; R2 #8385 (sh whitespace parity) -> 5032dc09; R3 #8389 PASS. tests/test_bus_post.py 44/44.
live_ac: PASS — one row (msg 8408) + deduped:true replay + single wake_event (CODEX_NEON_READONLY) + whitespace/empty flag rc=2 no post. Report: briefs/_reports/B1_AGENT_BUS_IDEMPOTENT_POST_1_20260710.md.
updated: 2026-07-10T07:04Z
---

# AGENT_BUS_IDEMPOTENT_POST_1 — checkpoint

## CODEX ROUND 1 (#8373 FAIL) — FIXED in PR #514 commit 22fdab91
Codex passed PR #111 (no daemon findings), FAILed PR #514 with 2 Python-client blockers — both fixed:
- **P1** read-timeout not retried: a urllib READ timeout escapes as bare socket.timeout (py3.9) /
  TimeoutError (3.10+), NOT urllib.error.URLError — the retry loop caught neither, so the core
  post-commit-timeout mode crashed uncaught. Fix: `import socket`; `_post` except now
  `(urllib.error.URLError, socket.timeout, TimeoutError)`. Tests test_39 (retry->success, 3 calls) +
  test_40 (persistent->exhaust->SystemExit, 4 calls).
- **P2** empty --idempotency-key silently minted: `'' or ... or uuid4()` treated empty as falsy. Fix:
  fail loud BEFORE any post on empty/whitespace flag (parity with sh test_35); empty env still mints.
  Tests test_41 (empty) + test_42 (whitespace).
- tests/test_bus_post.py now 42/42 green. LIVE: bus_post.py two same-key posts -> one row (8378);
  empty-key rc=1 no post. Re-review requested: lead #8382, codex #8383.

## SHIPPED (2026-07-10 ~06:37Z)
- Lead re-scoped brief to 2 gaps + ruled design fork = **C+B** (#8366).
- brisen-lab PR #111: `deduped:true` on ON-CONFLICT replay (bus.py). Test in
  test_ticket_id_dedup_1_daemon.py. Dedup daemon file 5/5 green (live PG).
- baker-master PR #514: bus_post.{sh,py} internal retry-backoff (4 attempts ~2/4/8s, 503/timeout
  only, env-tunable BUS_POST_MAX_ATTEMPTS/BUS_POST_BACKOFF_BASE) reusing ONE minted key +
  --idempotency-key / BUS_IDEMPOTENCY_KEY passthrough. tests/test_bus_post.py 38/38 green.
- LIVE end-to-end smoke: two same-key posts via updated bus_post.sh -> ONE row (msg 8369).
- Autowake combined-run failures = pre-existing WAKE_CLUSTER_1 (proven identical on stashed clean tree).
- Ship report -> lead #8371 (fleet/bus-idempotency).

## LEFT (b1 owes, after lead merges both + Render deploys brisen-lab)
1. Live prod AC: POST twice with ONE key via the merged bus_post.sh against prod -> assert single
   brisen_lab_msg row + single wake_event + `deduped:true` on the 2nd (replay). deduped:true only
   appears once PR #111 is deployed.
2. POST_DEPLOY_AC_VERDICT v1 on topic fleet/bus-idempotency.
3. Do NOT merge (B-code scope) — lead merges. Do NOT re-run drills.

## KEY FINDING (recon done, do NOT redo)
The DAEMON side of this brief is ALREADY MERGED ON MAIN under a different ticket:
**TICKET_ID_DEDUP_1** (brisen-lab commit `92e3ae6`, on origin/main — daemon half of lead ruling #7342).
It already satisfies brief Task-1 + AC2 + AC4:
- bus.py 943-952: optional `idempotency_key` param, str + <=200 validation, empty->None.
- bus.py 968-1007: INSERT ... ON CONFLICT (from_terminal, idempotency_key) WHERE idempotency_key IS NOT NULL
  DO NOTHING; on conflict re-SELECT + return ORIGINAL row. Returns (row, is_new).
- bus.py ~1020: is_new gating — no re-broadcast / no re-wake / no wake_events on replay.
- db.py 500-506 + 737-763: nullable idempotency_key column + partial unique index
  `uq_brisen_lab_msg_idempotency` via catalog-guarded additive bootstrap ALTER (no migration rewrite).
- tests/test_ticket_id_dedup_1_daemon.py PASSES: 3x same key->one row+same message_id, keyless->distinct,
  scoped-per-sender. (Client wiring in TICKET_ID_DEDUP_1 was ONLY orchestrator/airport_ticketing_bridge.py.)
- `origin/b2/ticket-id-dedup-1` is STALE/merged (git log main..that-branch is empty) — no active collision.

## TWO GENUINE GAPS vs this brief
1. **AC1 `deduped:true` NOT met** — daemon returns original message_id on replay but never sets
   `deduped:true` (string 'deduped' is nowhere in brisen-lab repo). Fix = set resp['deduped']=True when
   is_new is False (bus.py ~1075, the resp dict) + a test assertion. Small.
2. **Fleet clients NOT wired** — scripts/bus_post.sh + scripts/bus_post.py (baker-master) do NOT
   generate/send a key. THIS is the brief's core: my stand-down dup storm (#8331-#8335) came from a
   bus_post.sh CALLER loop, not the ticketing bridge.

## DESIGN FORK (escalated — lead must pick before client build)
bus_post.sh AND bus_post.py have NO internal retry loop; the storm was the CALLER (ad-hoc bash for-loop)
re-invoking bus_post.sh. So:
- A) mint per invocation only (literal brief): does NOT fix caller-loop storms (each attempt = new key).
- B) additive passthrough: script auto-mints if none given BUT accepts --idempotency-key / BUS_IDEMPOTENCY_KEY
  so a caller loop mints ONE key + reuses across invocations. Keyless byte-identical. Kills the real failure mode.
- C) internal retry-with-backoff loop reusing one key + move callers off ad-hoc loops — brief forbids new retry loops.
b1 leaned B in the escalation.

## NEXT CONCRETE STEP
Design fork RESOLVED = C+B (lead #8366). Both PRs SHIPPED (#111 daemon, #514 client) + ship report #8371.
AWAIT codex-medium verdict + lead merge of BOTH. Then (b1-owed): live prod AC (post twice one key via merged
bus_post.sh -> single row + single wake_event + deduped:true on replay) + POST_DEPLOY_AC_VERDICT v1 on
fleet/bus-idempotency. On codex request_changes: address -> NEW commit (never amend) on the same branch -> push
-> reply. Do NOT merge (lead does).

## KEY PATHS
- brisen-lab checkout: ~/bm-b1-brisen-lab (branch b1/bus-idempotent-post off main @6b75f70; clean, no edits).
- baker-master: ~/bm-b1 (client scripts scripts/bus_post.sh + scripts/bus_post.py).
- Existing daemon test to mirror/extend: tests/test_ticket_id_dedup_1_daemon.py.
- brisen-lab test harness: conftest.py `client`/`fresh_db` fixtures; POST helper `_post(client,term,key,**kw)`.
