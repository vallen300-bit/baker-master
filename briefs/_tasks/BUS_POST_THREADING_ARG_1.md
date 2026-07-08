# BRIEF: BUS_POST_THREADING_ARG_1 — bus_post.sh cannot thread; add optional parent/thread args

dispatched_by: lead
assignee: b1
effort: medium (recommended tier for codex gate: medium)
repo: baker-master (`scripts/bus_post.sh`)
task_class: small-fix-production (fleet tooling; unblocks machine-matchable check-ins for every agent)

## Context

Live incident 2026-07-08 (thread `airport-ticketing/checkin-not-clearing`): the first production AO flight ticket (row id=601, `airport-ticket-v1-a375244ce8266f4e1e77`) stayed stuck in `status=sent` because ao-desk's VALID check-in (#7087) opened a NEW thread instead of replying to the boarding pass (#7019, thread 92ed6726). The airport check-in reader matches ONLY on parent/thread (proven by the BB drain — 38/38 threaded disposes cleared in one sweep). ao-desk had to hand-roll a raw POST (#7101, parent_id=7019) to clear its own ticket.

### Context Contract
- `scripts/bus_post.sh` — the fleet-wide outbound bus poster (key resolution via `scripts/brisen_lab_terminal_key.sh`, identity via `scripts/agent_identity_generated.sh`).
- Daemon: brisen-lab `POST /msg/{slug}` (own-key bus I/O; NOT baker-master / X-Baker-Key).
- Check-in reader: matches replies on parent/thread against the boarding-pass message.
- Evidence trail: bus #7087 (unthreaded VALID), #7098 (b2 DB verify: no checked_in, no dead_letter), #7099 (lead order), #7101 (raw threaded POST that worked), #7102 (ao-desk root cause).

## Problem

**`scripts/bus_post.sh` hard-sets `parent_id=None`** — no caller can ever post a threaded reply through it. Every desk/worker using the script is blind to threading; every future airport check-in posted through it will strand its ticket exactly like id=601.

## Task

1. Add optional threading args: `--parent <msg-id>` (and `--thread <uuid>` only if the daemon does not auto-inherit thread from parent — verify daemon behavior first, do not guess).
2. Un-flagged behavior must remain byte-identical on the wire (same request body as today).
3. Mirror the change into the canonical fixture copy if one exists (check `tests/fixtures/`) — forge drift-checks compare deployed vs fixture.
4. Survey which picker clones carry their own `bus_post.sh` copies + how they sync (git pull vs forge vs manual); report the propagation path — do NOT hand-patch other clones.
5. Doc line: add to `agent-bus-posting-contract` (canonical) the rule "check-in = threaded reply to the boarding pass, single verdict token" with the `--parent` invocation; pointer from the airport-process runbook.

## Files Modified

- `scripts/bus_post.sh` (baker-master) — add `--parent` / `--thread` optional args.
- `tests/fixtures/bus_post.sh` — only if this fixture exists; sync.
- `tests/test_bus_post*.py` or shell probe — new coverage per Verification below.
- `_ops/processes/agent-bus-posting-contract.md` (vault) — one canonical doc line + runbook pointer.
- Nothing else. No daemon changes in this brief — fail-loud if server-side turns out to be required.

## Constraints (hard)

- No change to recipient validation, key resolution, or daemon URL handling.
- Fail-loud: if the daemon rejects/ignores `parent_id` on this endpoint, STOP and report — the fix may belong server-side (brisen-lab), not in the script.
- TDD: prove the gap first — probe showing un-flagged post carries no parent, flagged post carries it.

## Verification

1. Pre-fix probe (literal output): post via current script, `GET /event/<id>/full` shows `parent_id=None`.
2. Post-fix probe (literal output): `bus_post.sh <recipient> <body> <topic> --parent <id>` → `GET /event/<new>/full` shows parent_id set + thread inherited from parent.
3. Un-flagged regression: capture request body pre/post change (e.g. via `BRISEN_LAB_DAEMON_URL` pointed at a local echo server) — diff must be empty.
4. `bash scripts/install_forge_agent.sh --check` → clean on this host class (fixture sync).

## Acceptance criteria (done rubric)

- AC1: Threaded post proven live — literal `/event/<new-id>/full` output showing parent_id + thread in the ship report.
- AC2: Un-flagged invocation request body byte-identical to pre-change (diff shown).
- AC3: Fixture copy (if any) synced; forge `--check` clean.
- AC4: Propagation survey reported (which clones, which sync path).
- AC5: Doc line landed in `agent-bus-posting-contract` + runbook pointer.

Done-state: all 5 ACs answered with literal evidence in the ship report — not "works by inspection".

## Gate plan

codex G3 (effort: medium) → lead merge. No deputy G2 (single-script, low blast radius). No Director gate (Tier-A fleet tooling).

## Reply target

Bus-post all state changes (start, blocker, gate request, ship) to `lead`. Reply-target = lead.
