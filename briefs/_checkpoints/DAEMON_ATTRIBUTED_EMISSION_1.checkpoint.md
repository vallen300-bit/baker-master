# CHECKPOINT — DAEMON_ATTRIBUTED_EMISSION_1

attempt: 1
seat: b1
branch: b1/daemon-attributed-emission-1 (brisen-lab, in ~/bm-b1/brisen-lab), off main @661bebd (post-#130)
created: 2026-07-13
updated: 2026-07-13

## Brief id
DAEMON_ATTRIBUTED_EMISSION_1 — brief `_ops/agents/aihead2/BRIEF_DAEMON_ATTRIBUTED_EMISSION_1.md` @ed33634
(deputy spec; lead dispatch #10730, ruling #10702/#10712). Reply topic: case-one/daemon-attributed-emission.
ACK+claim #10738. Ship #10750.

## STATUS: CODEX PASS — MERGE-ELIGIBLE, handed to lead (b1 build complete)
- codex #10751: PASS, NO findings (hard-refreshed main — no stale-base repeat of #130). Confirmed
  both daemon inserts stamp source+unattributed=FALSE, client gate unchanged, tests cover all paths.
- Flagged lead merge-eligible #10754. Merge = lead's action; on merge ARM re-runs --label and the
  48h zero-shared-key clean window arms (last code blocker per #10730).
- Nothing further from b1 unless lead requests changes or rules on the bus.py:2664 follow-up.

## (history) BUILT + G1 GREEN + PR OPEN — awaiting codex gate then lead merge
- PR brisen-lab #134 (branch b1/daemon-attributed-emission-1). Build on post-#130 main @661bebd.
- Fix (surgical, 2 files):
  - post_daemon_message._insert (bus.py ~1189): + source=from_slug, unattributed=FALSE.
  - emit_audit._do_insert (bus.py ~925): + source='daemon', unattributed=FALSE on the audit row
    AND the escalate_to_aihead ratify_required row.
  - New test tests/test_daemon_attributed_emission_1.py (6 cases).
- Riders held: VALID_KINDS byte-identical; CLIENT shared-key gate (bus.py unattributed=is_shared_key)
  UNTOUCHED (shared-key client POST -> unattributed=TRUE; per-seat -> FALSE).
- G1: full brisen-lab suite 618 pass / 1 skip / 26 fail = pre-existing autowake/identity env baseline,
  ZERO new failures.
- codex gate requested #10747 (effort=medium; TOLD codex hard-refresh main first — #130 stale-base lesson).

## G1 test-isolation trap caught + fixed (lesson)
First test file imported `app`/`bus` at MODULE TOP -> `import app` binds app.FORGE_KEY = os.environ["FORGE_KEY"]
at pytest COLLECTION time, BEFORE conftest's session-autouse fixture sets FORGE_KEY=test-forge-key.
Result: 24 later forge/refresh tests 401'd ("bad forge key") in the FULL suite (passed in isolation).
Fix: lazy app/bus imports inside each test (house pattern per test_forge_heartbeat/test_case_one_p5).
Diagnostic pattern: full-suite +N failures but families pass in isolation => a collection-time
import/global-state leak, not a code bug.

## Observation flagged to lead (out of brief scope)
Third direct-insert = client ratify_decision write (~bus.py:2664) also omits source/unattributed.
CLIENT-authenticated path (from sender_slug), NOT daemon — left untouched; raised for lead ruling
(attribution should follow the client gate, not a hardcode).

## Next concrete step
Await codex verdict on #10747. If PASS -> post verdict ref to lead (#10750 thread) for merge; on merge
ARM re-runs --label and the 48h clean window arms. If codex findings -> address as NEW commit (never
amend pushed), re-run suite, re-push, re-request. If codex FAILs on file-count again -> check it
hard-refreshed main (authoritative diff = 2 files).

## Claim discipline
Successor claims by the attempt:-bump commit on THIS checkpoint. If attempt already bumped, stand down.
At attempt >= 3, stop resuming + escalate to lead with this path + last error.
