---
status: CLAIMED
brief: briefs/BRIEF_HAG_DESK_HEARTBEAT_DAEMON_1.md
brief_id: HAG_DESK_HEARTBEAT_DAEMON_1
target_repo: baker-master
matter_slug: baker-internal
dispatched_at: 2026-05-22T05:55:00Z
dispatched_by: lead
target: b1
working_branch: b1/hag-desk-heartbeat-daemon-1
reply_to: lead
deadline: 2026-05-23T18:00:00Z
priority: tier-b
claimed_at: 2026-05-22T06:20:00Z
---

# CODE_1_PENDING — HAG_DESK_HEARTBEAT_DAEMON_1 — 2026-05-22

**Brief:** `briefs/BRIEF_HAG_DESK_HEARTBEAT_DAEMON_1.md`
**Working branch:** `b1/hag-desk-heartbeat-daemon-1` (branch off `main`)
**Repo:** baker-master only
**Pre-requisites:** none — canonical script at `scripts/forge_snapshot_push.sh` is current; deployed copy verified identical 2026-05-22

## Acceptance criteria (testable)

### AC1 — TERMINALS array updated
- One new line in `scripts/forge_snapshot_push.sh:61-69` TERMINALS array: `"hag-desk:/Users/dimitry/baker-vault"` (appended after `b4` entry).
- No other changes to the array. No refactoring.

### AC2 — Smoke test Case H added
- New Case H in `tests/test_forge_snapshot_push.sh` after Case G, per brief's Fix 2 implementation snippet.
- Verifies: `terminal_alias=="hag-desk"`, `mailbox_status=="n/a"`, `mailbox_brief_name==""`.
- Reuses existing `run_daemon` + `extract_payload_field` + `assert_no_prod_aliases` helpers.

### AC3 — Test suite green
- `bash tests/test_forge_snapshot_push.sh` exits 0 with **8** PASS lines (A through H).
- Literal output included in ship report — no "pass by inspection."

### AC4 — Deploy verification (post-merge, AH1 Tier-B)
- AH1 runs `install_forge_push.sh` on whichever hosts run the daemon (Mac Mini + MacBook — both currently active).
- Verification command (run twice 30s apart):
  ```bash
  KEY="$(op read 'op://Baker/brisen-lab-lead-key/credential')"
  curl -s "https://brisen-lab.onrender.com/api/state?terminal=lead" -H "X-Terminal-Key: $KEY" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['snapshots']['hag-desk']['daemon_last_seen'])"
  ```
- Both timestamps within last 60s; second > first.
- Out of b1's scope (AH1 owns post-merge deploy + verification).

## Ship gate
Literal `bash tests/test_forge_snapshot_push.sh` output showing 8 PASS lines pasted into PR description. No "pass by inspection."

## Reporting
- Bus-post `lead` on PR open: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "PR #<num> opened: HAG_DESK_HEARTBEAT_DAEMON_1" ship/hag-desk-heartbeat`
- Bus-post `lead` on any blocker: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "<blocker>" blocker/hag-desk-heartbeat`
- Mailbox UPDATE pattern: append CLAIM / IN_PROGRESS / COMPLETE entries with ISO timestamps per b-code-dispatch-coordination protocol.

## Files Modified (expected)
- `scripts/forge_snapshot_push.sh` — +1 line in TERMINALS array
- `tests/test_forge_snapshot_push.sh` — +1 Case H (~30 LOC)

## Do NOT Touch
- `scripts/install_forge_push.sh` — deploy mechanism unchanged
- `~/Library/Application Support/baker/forge_snapshot_push.sh` — deploy script handles it
- Anything in `~/bm-b1-brisen-lab/` — front-end already wired
- The `mailbox_status` classification logic at `scripts/forge_snapshot_push.sh:449` — `^b([1-9])$` regex is correct as-is; hag-desk intentionally falls through to "n/a" default
