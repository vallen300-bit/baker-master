# Fleet Wake Smoke — 2026-07-19 overnight (lead)

Director goal: every agent receives buses + wakes; fleet loop-ready by morning.
Method: direct-addressed smoke message per seat (`smoke/fleet-wake-20260719`,
ack-only instruction), monitored per-seat `acknowledged_at` via
`/msg/{terminal}/{msg_id}`.

## Result

- **28/28 seats verified.** 26 real end-to-end ACKs (bus → lab wake → laptop
  listener → controller tmux injection → session read → ACK).
- 2 bookkeeping exceptions (below): deep55, clerk.
- Wake dedupe hardening merged + live same night: main @8d8a9413
  (deputy-codex build c95c0ed4, codex PASS #13117); controller re-synced +
  launchd-restarted; 53 focused tests green post-merge.

## Interventions needed (root causes for follow-up briefs)

| # | Finding | Seats hit | Fix applied tonight | Follow-up |
|---|---------|-----------|---------------------|-----------|
| 1 | Daemon forced-kill/refresh respawn ate the queued wake — fresh session at empty prompt, never told of backlog | movie-desk, researcher (+ desks with #13038-40 kills) | Direct tmux injection | Respawn must drain unacked backlog on start (cadence-kill arc, known) |
| 2 | Controller cached `unacked_count=0` while bus showed unacked → wake endpoint skipped `no unacked` | movie-desk, origination-desk, publisher, researcher, russo-ai | Fresh bus nudge + direct injection | Controller mailbox cache staleness — refresh before wake decision |
| 3 | Agent read wake, dismissed smoke as noise: "Send me a real dispatch." | hag-filer | Explicit re-injection worked | Seat orientation: bus ACK obligation applies to every direct message |
| 4 | arm ack-wrapper misclassifies direct-addressed msgs as broadcast (to=['arm'] read as to=*), refuses to ack | arm | arm posted liveness receipt #13085; lead acked #13076 | Fix arm_ack.sh classification |
| 5 | clerk + clerk-haiku tmux sessions are the SAME claude instance in `/Users/dimitry/bm-clerk` — clerk seat has no distinct session | clerk | Bookkeeping ack #13067 (clerk-haiku session acked its own #13070) | Split the seats or retire one; fleet launcher maps both to one dir |
| 6 | codex CLI ran out of context mid-gate, no auto-recovery; verdict stalled ~2h | codex | `/new` thread + re-injected gate task → PASS in 20 min | Context-band discipline for codex seat / auto-thread-rotation |
| 7 | deep55 is a bare non-Claude REPL (`deep55>`), cannot drain bus | deep55 | Bookkeeping ack #13074 | Decide: wire deep55 REPL to bus or exclude from wake fleet |
| 8 | Bus `bus_busy_retry` frequent under burst posting; russo-ai initial post dropped | russo-ai | Retry succeeded (#13106) | Client-side retry loop in bus_post.sh |

## Message ledger

Smoke ids: #13057-13106 (per-seat, `/tmp/smoke_ids.txt` copied below).
Nudges: #13107-13111 (5 stale-cache seats), codex gate nudge #13114.
Dedupe arc: dispatch #13056 → deputy-codex DONE #13118 → codex PASS #13117 → merged 8d8a9413 → live notice #13119.

deputy 13057 · deputy-codex 13059 · aid 13060 · b1 13061 · b2 13062 · b3 13063 ·
b4 13064 · researcher 13065 · codex 13066 · clerk 13067 · clerk-haiku 13070 ·
russo-ai 13106 · deep55 13074 · arm 13076 · publisher 13078 · designer 13080 ·
hag-desk 13082 · origination-desk 13087 · ao-desk 13090 · movie-desk 13092 ·
baden-baden-desk 13093 · brisen-desk 13095 · CM-1 13096 · CM-2 13097 ·
CM-3 13099 · CM-4 13101 · hag-filer 13103 · cowork-ah1 13105
