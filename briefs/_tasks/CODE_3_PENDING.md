---
status: PENDING
brief_id: BUS_ACK_RENDER_LEDGER_DEPLOY_1
to: b3
from: lead
dispatched_by: lead
dispatched_at: 2026-06-11
reply_target: lead (bus)
task_class: ops/hook deploy + small script patch — no production (Render) deploy
gate_plan: Phase 1 immediate -> codex G3 on PR #357 (already requested, bus #2897) -> lead merges -> Phase 2 deploy -> b3 POST_DEPLOY_AC_VERDICT on bus
arc: BUS_ACK_RENDER_LEDGER_1 (PINNED §OPEN-2 fix — ack-only-what-renders)
---

# BUS_ACK_RENDER_LEDGER_DEPLOY_1 — finish + deploy the ack-only-what-renders fix

## Context

2026-06-10 incident: the turn-end Stop hook `~/.claude/hooks/stop-bus-ack.sh` acked ALL
unacked bus messages (≤60) for lead/deputy/cowork-ah1 — including messages never rendered
to the agent. 6 ship reports were auto-acked unseen. Fix shipped on PR #357
(branch `lead/bus-ack-render-ledger-1`, commit d741da7):

- `tests/fixtures/session-start-bus-drain.sh` V0.3 — appends ids of messages it actually
  renders to `~/.brisen-lab-bus-rendered-<slug>.txt` (the "rendered-ID ledger").
- `tests/fixtures/stop-bus-ack.sh` V2 (NEW canonical fixture) — acks ONLY ledgered ids that
  are still unacked; prunes ledger; no-ops without ledger; orchestrator slugs only.
- `tests/test_stop_bus_ack_hook.py` (5 functional cases, local HTTP daemon) + ledger asserts
  in `tests/test_bus_drain_hook.py`. 15/17 pass locally; the 2 failures are the drift tests
  (deployed copies update in YOUR Phase 2).

## Estimated time: ~45 min
## Complexity: Low
## Prerequisites: Phase 2 only — PR #357 merged to main (lead posts merge confirm on bus)

---

## Phase 1 — NOW (independent of merge)

### Problem
Scripted mid-session polls (`check-lead-inbox.sh`) render message ids to the agent but do
not ledger them — under the new Stop hook those rendered messages would never auto-ack.

### Current State
`~/Desktop/baker-code/scripts/check-lead-inbox.sh` (untracked on disk there) renders via a
`python3 - "$RESPONSE_FILE" "$STATE_FILE" <<'PYEOF'` heredoc: prints each `#{m['id']}`
in a for-loop, then advances the state file (`latest = max(...)` block at the end).

### Implementation
Insert AFTER the message print loop, BEFORE the `# Advance state` block, inside the heredoc
(`json, sys` already imported; add `os` to the import line):

```python
# Ack-only-what-renders (2026-06-11): ledger every printed id so the turn-end
# Stop hook may auto-ack it. Append-only; stop-bus-ack.sh prunes.
ledger = os.path.expanduser("~/.brisen-lab-bus-rendered-lead.txt")
try:
    with open(ledger, "a") as f:
        f.write("".join("{}\n".format(m["id"]) for m in msgs if m.get("id") is not None))
except OSError as e:
    print("(warn: rendered-ledger append failed: {} — ack manually)".format(e))
```

### Verification
- `bash -n ~/Desktop/baker-code/scripts/check-lead-inbox.sh`
- Run `bash ~/Desktop/baker-code/scripts/check-lead-inbox.sh --all` once; show ledger
  line-count before/after (`wc -l ~/.brisen-lab-bus-rendered-lead.txt`).

---

## Phase 2 — AFTER lead posts merge confirmation on this bus thread

### Implementation
1. `cd ~/bm-b3 && git checkout main && git pull` (get merged fixtures).
2. Deploy BOTH hooks together (drain writes ledger; stop hook consumes — never deploy one):
   - `cp tests/fixtures/session-start-bus-drain.sh ~/.claude/hooks/session-start-bus-drain.sh`
   - `cp tests/fixtures/stop-bus-ack.sh ~/.claude/hooks/stop-bus-ack.sh`

### Verification
`python3.12 -m pytest tests/test_stop_bus_ack_hook.py tests/test_bus_drain_hook.py`
— ALL 17 must pass now (drift tests included). Paste literal tail into ship report.
NOTE: system python3 is 3.9 and fails at conftest import — use python3.12.

---

## Key Constraints
- Do NOT edit the deployed hooks directly — fixtures are canonical; deploy is `cp` only.
- Do NOT touch the b-code/desk exclusion in stop-bus-ack.sh (claim-gating; 2026-06-03
  regression — auto-ack cleared b1's dispatch pre-claim).
- Do NOT ack lead's bus messages while testing; the `--all` poll run is read-only + ledger append.
- No Render deploy, no migrations, no dashboard.py, no secrets in any file.

## Files Modified
- `~/Desktop/baker-code/scripts/check-lead-inbox.sh` — ledger append (on-disk patch)
- `~/.claude/hooks/session-start-bus-drain.sh` — deployed from fixture (cp)
- `~/.claude/hooks/stop-bus-ack.sh` — deployed from fixture (cp)

## Do NOT Touch
- `tests/fixtures/*.sh` — canonical, merged via PR #357; deploy is cp-only
- `~/Desktop/baker-code/scripts/check-codex-inbox.sh` etc. — non-orchestrator slugs out of scope
- `scripts/bus_post.sh` — unrelated

## Quality Checkpoints
1. Ledger append survives a poll with 0 messages (no crash, no empty-line spam).
2. Drift tests PASS post-cp (fixture == deployed, byte-identical).
3. Full two-suite pytest literal output pasted (17/17).
4. `POST_DEPLOY_AC_VERDICT v1` posted to lead on bus, topic `bus-ack-ledger/post-deploy-ac`,
   with per-AC verdicts (AC1 ledger append works / AC2 drift green / AC3 pytest 17/17).

## Out of scope (note, don't build)
- deputy/cowork-ah1 poll-script parity — if you spot equivalents, report to lead; lead queues follow-up.
- Raw-curl manual reads stay covered by the ack-on-read hard rule (874eb38) — no change.
