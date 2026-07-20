# Fleet Wake Smoke — 2026-07-20 morning (lead, night-watch close)

Director goal: autonomous loops working by morning — validate the wake path
REBUILT overnight (obligation-filtered server counts + fail-closed controller
row selection + async listener + structured disposition).
Method: identical to 2026-07-19 — direct-addressed smoke message per seat
(`smoke/fleet-wake-20260720`, ack-only instruction), per-seat `acknowledged_at`
monitored via `/msg/{terminal}/{msg_id}` with each seat's own key.

## Result

- **27/28 verified** (25 real end-to-end ACKs + 2 sanctioned bookkeeping
  exceptions). 1 pending: cowork-ah1 (App-resident; server counted its
  obligation correctly woc=1/unacked=1 — drains when the Cowork app opens).
- 20 seats ACKed on the fully-automatic path (bus → obligation-filtered wake →
  tmux injection → ACK) — including every builder/reviewer seat and all 4 CMs.
- New disposition telemetry visible in `wake_audit.log`: `disposition:
  "delivered"` + `request_id` on wake rows — phase-1 contract live in
  production audit.
- Bookkeeping (same as 07-19): deep55 (bare REPL, not bus-capable), clerk
  (clerk/clerk-haiku same-instance collision; clerk-haiku ACKed its own).

## Findings

| # | Finding | Seats | Status |
|---|---------|-------|--------|
| 1 | **RECURRENCE of 07-19 finding 2, now proven SERVER-side:** live Lab glance returned `unacked_count=0, wake_obligation_count=0` for seats with verifiably unacked `kind=dispatch, execute_obligation=true` messages (checked via `/msg/{slug}/{id}` — `acknowledged_at: null`). Yesterday this was blamed on controller cache; controller now consumes server counts, so the zero originates in the Lab glance query/cache for these recipients. **Top brief candidate.** Evidence: msg #13884 (movie-desk) unacked while glance showed 0/0 at ~06:45Z. | movie-desk, origination-desk, publisher, researcher, russo-ai (same 5 as 07-19) | Chased via direct tmux injection → all 5 ACKed within minutes (seats alive + bus-capable; only the wake trigger data was wrong) |
| 2 | Smoke-post loop initially 0/28 — zsh word-splitting (Lesson #128) | all (tooling, not fleet) | Fixed with array; 28/28 posted, 0 failures |
| 3 | cowork-ah1 App-resident drain depends on app being open | cowork-ah1 | Expected behavior; obligation correctly counted server-side |

## Not recurring (07-19 findings now closed)

- Respawn-ate-wake: no recurrence observed this run.
- arm ack-wrapper broadcast bug: arm ACKed cleanly (fix held).
- hag-filer smoke dismissal: ACKed cleanly this run.
- codex context exhaustion: seat reset 3× during the NIGHT (gate work), but
  ACKed the smoke fine; forensics brief still owed (separate from smoke).
- bus_busy under burst: retry loop absorbed it — 0 post failures in 28.

## Message ledger

Posted 06:27-06:42Z. b3 13849 · deputy 13850 · deputy-codex 13852 · aid 13853 ·
b1 13854 · b2 13855 · b4 13856 · researcher 13857 · codex 13858 · clerk 13859 ·
clerk-haiku 13860 · russo-ai 13861 · deep55 13862 · arm 13867 · publisher 13875 ·
designer 13877 · hag-desk 13878 · origination-desk 13882 · ao-desk 13883 ·
movie-desk 13884 · baden-baden-desk 13885 · brisen-desk 13886 · CM-1 13887 ·
CM-2 13889 · CM-3 13890 · CM-4 13891 · hag-filer 13892 · cowork-ah1 13893.
Bookkeeping acks: clerk #13859, deep55 #13862 (lead, seat keys, sanctioned
07-19 precedent).

## Night context (what this smoke validated)

7 merges shipped overnight, all independently gated: copy-button #608,
wake-attribution lab #160 (+ live AC ×2), storm-fix #610 + lab #161 (storm-close
AC PASS #13790), slug-cards #609, listener lab #162 (deployed), disposition
phase-1 #611 (deployed). Phase-2 listener at final gate round (unknown-enum P2).
Full narrative: `briefs/_checkpoints/NIGHT_WATCH_2026-07-20.checkpoint.md`.
