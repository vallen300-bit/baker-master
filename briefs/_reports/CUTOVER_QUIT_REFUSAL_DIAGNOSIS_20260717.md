# Phase-2 cutover — Terminal quit-refusal diagnosis (2026-07-17)

- **Author:** lead (AH1), overnight lane per cowork-ah1 dispatch bus #12554.
- **Incident:** first Phase-2 cutover attempt aborted at step 3/7; whole fleet down ~30 min; second attempt clean 28/28.
- **Fix commit:** `0ceab93e` (quit escalation ladder). Runbook updated same commit.
- **Evidence:** bus #12544 (cowork-ah1 abort-recovery), `~/Library/Application Support/baker/cockpit/cutover_run.log` + `cutover_wave_report.log` (attempt 2; attempt-1 log overwritten — see Gap 3), commit `0ceab93e`.

## What happened (attempt 1, ~22:0x UTC)

1. Director GO → `cockpit_migrate.sh cutover` ran with the GO token.
2. Step 3/7: `osascript 'tell application "Terminal" to quit'` fired. Terminal showed its **"running processes" confirmation dialog** (live shells in every seat window) and never exited.
3. The script's single 20s wait expired → FATAL abort. Recovery trap fired correctly: **no plist had been edited yet**, forced whole-fleet BASELINE, ledger cleared. So far honest and safe.
4. **Then the tail bit:** Terminal died anyway *after* the abort (the pending quit eventually completed / dialog interaction), and nothing relaunched it — the recovery path had already run. Whole fleet dark except tmux pilots `b3` + `brisen-desk` (both stayed up; controller :7800 alive — the tmux substrate proved its point).
5. Second latent failure: the **wake-listener launchd job was left UNLOADED** — runbook precondition 5 pauses it before cutover, and resume was a manual runbook step, not script-owned. Abort path never resumed it.
6. Recovery (cowork-ah1, on Director ask): `open -a Terminal` (profiles baseline/untouched) + re-bootstrap wake-listener into launchd. No data loss; no plist corruption.

## Root cause

**The scripted quit assumed Terminal would honor a polite AppleScript quit.** With live shells, Terminal interposes a modal confirmation dialog; AppleScript `quit` does not bypass it. A fixed 20s wait with no escalation turned a UI dialog into a fleet-wide abort. Secondary: the abort path treated "Terminal still running" as terminal state and had no relaunch-on-abort; and wake-listener pause/resume lived outside the script's ownership.

## Fix (0ceab93e) and why it holds

Escalation ladder at step 3: polite AppleScript quit (10s) → `killall Terminal` SIGTERM (10s) → `killall -9` SIGKILL (5s) → abort. SIGTERM/SIGKILL **bypass the dialog AND skip Terminal's plist write on exit** — which is exactly what Lesson 76 wants (our profile rewrite must be authoritative while Terminal is down; a kill-path exit that skips Terminal's own plist flush cannot clobber it).

## Verification (attempt 2, 22:30 UTC)

- Run log shows step 3 completed with **no escalation lines** → the polite quit succeeded inside rung 1 (<10s) on the rerun; the ladder was armed but not needed.
- 28 profiles rewritten (0 already), fleet up 26 created + 2 already-up (pilots), 6 smoke waves **28/28 PASS**, Terminal relaunched. `CUTOVER COMPLETE: 28 passed, 0 failed.`
- Steady-state re-verified by lead 22:40 UTC (bus #12559): tmux 28/28 panes alive, cockpit 28/28 session_up+ttyd_up, manifest==fleet zero diff, wake_health firing.

## Residual gaps (follow-up candidates, not blockers)

1. **Abort-path Terminal relaunch race** — if a pending quit completes *after* emergency_recover, Terminal stays dead. Cheap fix: recovery tail re-checks `pgrep -x Terminal` and `open -a Terminal` if the quit was ever attempted. One-time-per-cutover exposure; fleet now lives on tmux so blast radius is far smaller post-cutover.
2. **wake-listener pause/resume is runbook-manual** — script should own resume in both success and abort paths (or precondition 5 should move into the script). This was the second silent failure of attempt 1.
3. **Run log overwritten per attempt** — attempt-1 forensic log was lost to attempt 2 (`cutover_run.log` truncates on start). Append or timestamp-suffix future runs.

4. **tmux global-env identity leak (found 2026-07-18 03:0x UTC, live impact)** — the tmux server absorbed `BAKER_ROLE=lead` + the lead terminal key from the cutover-running shell into its GLOBAL environment; all 28 seats inherited both. Codex's inbox reader (env-beats-cache precedence) presented lead's key for `/msg/codex` → 403 `reader_slug_mismatch` (bus #12583). Scrubbed live (`tmux set-environment -g -u` both vars). MUST-DO: rotate the lead key (sat in every seat's env since cutover); fix `fleet_terminals.sh` to scrub identity env at session-create; restart/repair the codex seat process env.
5. **Stuck composer on wake keystroke injection** — text lands in the seat's input box but Enter does not submit in one pass (seen on b1 by lead, on b1 again by cowork-ah1; second explicit Enter submits). Same family as the Mac submit-gap #3746 the cutover was meant to fix structurally — needs a look at send-keys pacing (text and Enter in one `send-keys` call vs split, and a settle delay).

Gaps 1-3 matter mainly for Mac-Mini / future-machine replays of the runbook; gaps 4-5 are LIVE fleet issues on the morning list.
