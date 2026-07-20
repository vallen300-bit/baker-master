---
brief_id: NIGHT_WATCH_2026-07-20
attempt: 1
owner: lead (AH1)
status: IN PROGRESS — self-scheduled night loop, Director asleep (authorized ~23:00Z), morning summary owed pre-AO-meeting
---

# Night watch 2026-07-19/20 — checkpoint (02:52Z)

## Shipped tonight (all merged + live)

1. Copy-button PR #608 @b0f1d9bf (codex PASS #13683/#13688), static synced.
2. WAKE_ATTRIBUTION lab PR #160 @02b67b2 (b4; CLI provenance #13694 accepted);
   live-AC PASS ×2 (#13724 deputy, #13737 deputy-codex).
3. STORM-FIX baker PR #610 @f69fbf4c + lab PR #161 (@29bf325b / @dbac318;
   3-round gate; codex PASS #13765 + lead CLI + deputy concur). Controller
   re-synced + kickstarted 00:05:30Z. STORM-CLOSE AC PASS #13790 — arc GREEN.
4. Slug-only cards PR #609 (b2 @2fdb16a5 + my v4 cache-bust @06920d7f; CLI gate
   PASS-with-P2). Static synced, v4 live.

## In flight (merge on PASS)

- **Listener** b1/wake-listener-no-legacy-fallback-1 (brisen-lab): round 6 in
  build at b1 (#13811 — per-alias pending-latest slot + queue-don't-drop).
  Rounds 1-5 history in gates/wake-listener-no-legacy-fallback-1 topic.
  Re-gate on LEAD CLI lane (codex-verify; codex seat unstable — 3 resets).
- **Disposition phase 1** deputy-codex/wake-disposition-rewake-1 (baker):
  compat-P2 fix in build (#13808 — undelivered must fill legacy `skipped`
  field with reason). Prior HEAD 9ecc7917 clean otherwise. On PASS: merge,
  cp controller + rsync static to App Support, kickstart
  com.baker.cockpit-controller, verify restart, then release b1 phase 2.
- Brief: `briefs/_tasks/WAKE_DISPOSITION_REWAKE_1.md` (committed this push).

## Owed by morning (~06:15Z)

1. 28-seat fleet wake smoke (FLEET_WAKE_SMOKE_2026-07-19 method) → report to
   `briefs/_reports/` + morning summary in Director chat + §A pin.
2. Morning summary must include: storm-fix merged ping (Director asked),
   4 merges list, listener + disposition status, codex-seat forensics note
   (3 resets, stale 'working' glance misclassification ×2 — brief candidate).

## Method notes for successor

- CLI gate: `git worktree add /tmp/<x> origin/<branch>; cd; codex-verify
  --review --base main -- '<context>'` (background, ~5-15 min).
- Bus read: lead key `~/.brisen-lab/keys/lead`, `/event/{id}/full`, retry on
  bus_busy_retry; ack via POST /msg/{id}/ack.
- Daemon lifecycle noise addressed to other seats: skip (not_party).
- Cockpit controller wake: basic-auth creds at
  `~/Library/Application Support/baker/cockpit/credentials`, port 7800.
