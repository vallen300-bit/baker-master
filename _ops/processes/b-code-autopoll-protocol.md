# B-Code Autopoll Protocol

You are a Code Brisen (B1–B5) running in `/loop` autopoll mode in working
directory `~/bm-bN`. On every wake, execute this protocol exactly. You have
no session memory across wakes — this file is the contract.

Authority: `briefs/BRIEF_B_CODE_AUTOPOLL_1.md` (Director ratified 2026-04-27).
Window-scoped exception to Lesson #48 — see `tasks/lessons.md` Lesson #50.

## Phase 1 — Wake & sync

1. `cd ~/bm-bN && git checkout main && git pull --rebase --quiet`
2. Check stop conditions:
   - Read `OVERNIGHT_AUTONOMY_UNTIL` env. If unset, default to `07:00 UTC`
     today. If `now > deadline` → write a one-line STOPPED log to chat,
     do NOT call `ScheduleWakeup`, exit loop.
   - Read persistent idle counter:
     ```
     python3 -c "from scripts.autopoll_state import read_idle_count; \
       print(read_idle_count('bN'))"
     ```
     If returned value `>= 3` → STOPPED, exit. Director re-arms by
     deleting `~/.autopoll_state/bN.yaml` or pasting startup block.
   - If the user pastes literal `STOP AUTOPOLL` into the tab → exit.

## Phase 2 — Read mailbox

3. ```
   python3 -c "from scripts.autopoll_state import read_state; \
     print(read_state('briefs/_tasks/CODE_N_PENDING.md'))"
   ```
4. Branch on `status`:
   - `OPEN` + `autopoll_eligible: true` + `dispatched_at` newer than the
     last `dispatched_at` you saw → claim (Phase 3).
   - `OPEN` + `autopoll_eligible: false` → leave; this dispatch wants the
     paste-block cold-start path (Lesson #48). Idle reschedule.
   - `IN_PROGRESS` + `claimed_by == bN` → resume; heartbeat then continue.
   - `IN_PROGRESS` + `claimed_by != bN` → leave alone, increment idle
     counter, reschedule.
   - `BLOCKED-AI-HEAD-Q` / `BLOCKED-DIRECTOR-Q` (yours) → check whether
     the status flipped back to `IN_PROGRESS`; if not, idle reschedule.
   - `COMPLETE` / `RETIRED` → idle reschedule.

   On any "idle reschedule" branch above, BEFORE Phase 7's
   ScheduleWakeup, call:
   ```
   python3 -c "from scripts.autopoll_state import increment_idle_count; \
     print(increment_idle_count('bN'))"
   ```
   If returned value `>= 3` → STOPPED, exit (skip Phase 7 reschedule).

## Phase 3 — Claim

5. `git pull --rebase --quiet` (race protection)
5a. Successful claim → reset idle counter:
    ```
    python3 -c "from scripts.autopoll_state import reset_idle_count; \
      reset_idle_count('bN')"
    ```
6. ```
   python3 -c "from scripts.autopoll_state import transition_state, push_state_transition; \
     transition_state('briefs/_tasks/CODE_N_PENDING.md', to='IN_PROGRESS', claimed_by='bN'); \
     push_state_transition('briefs/_tasks/CODE_N_PENDING.md', to='IN_PROGRESS')"
   ```
7. ```
   git add briefs/_tasks/CODE_N_PENDING.md && \
     git commit -m "claim(bN): <brief-id>" && \
     git push
   ```
8. If `git push` rejects (someone else's commit landed) → discard local
   mutation per LWW Q6 (the other writer's transition wins):
   ```
   git reset --hard origin/main && git pull --rebase --quiet
   ```
   Then re-read state via `read_state(...)`. If now `IN_PROGRESS` by
   another B-code → idle reschedule. If still `OPEN` → optionally
   re-attempt claim from Phase 3 step 6.

## Phase 4 — Execute

9. Read brief at `fm["brief"]`. Apply the existing dispatch protocol
   (`_ops/processes/b-code-dispatch-coordination.md` §2 busy-check +
   Lesson #47 codebase grep) — autopoll changes how you wake, not how
   you build.
10. Heartbeat every ~10–15 min while doing long work:
    ```
    python3 -c "from scripts.autopoll_state import heartbeat; \
      heartbeat('briefs/_tasks/CODE_N_PENDING.md')"
    git add briefs/_tasks/CODE_N_PENDING.md && \
      git commit -m "heartbeat(bN)" && git push
    ```
    Keeps stale-claim recovery (60-min cutoff) off your back.

## Phase 5 — Surface blockers

11. Tier-A-scope ambiguity (existing helper to use, pattern to follow,
    file:line clarification) →
    `transition_state(path, to='BLOCKED-AI-HEAD-Q',
    blocker_question='<text>')`. Push commit. Reschedule.
12. True Director Q (cost decision, scope question, env var the brief
    doesn't cover) →
    `transition_state(path, to='BLOCKED-DIRECTOR-Q',
    blocker_question='<text>')`. Push commit. Reschedule.

## Phase 6 — Ship

13. Open PR per existing dispatch protocol. Ship gate is **literal
    pytest output** in the PR + ship report — no "by inspection"
    (Lessons #34 / #42 / #44).
14. ```
    python3 -c "from scripts.autopoll_state import transition_state, push_state_transition; \
      transition_state('briefs/_tasks/CODE_N_PENDING.md', to='COMPLETE', \
        ship_report='briefs/_reports/BN_<name>_<date>.md'); \
      push_state_transition('briefs/_tasks/CODE_N_PENDING.md', to='COMPLETE')"
    git add briefs/_tasks/CODE_N_PENDING.md && \
      git commit -m "ship(bN): <brief-id> -> PR #<n>" && git push
    ```

## Phase 7 — Reschedule

15. `ScheduleWakeup(delaySeconds=900, reason='autopoll wake bN',
    prompt=<verbatim /loop prompt>)`. Use the same `/loop` prompt
    text every wake.
16. End turn.

## Hard rules

- NEVER take Tier B actions in autopoll. Surface to BLOCKED-DIRECTOR-Q.
- NEVER skip the ship gate (literal pytest stdout). Lessons #34 / #42 /
  #44 still apply.
- NEVER skip §2 busy-check / Lesson #47 codebase grep for new
  sentinel / capability / pipeline briefs.
- NEVER claim a dispatch you don't have working-dir setup for (e.g., B3
  doesn't claim a brief that requires `~/bm-b1` artefacts).
- NEVER edit `outputs/slack_notifier.py`, `config/settings.py`, or any
  production Cortex / capability code as part of the autopoll loop
  itself — autopoll is process plumbing, not feature work.
- NEVER force-push, NEVER `--no-verify`, NEVER amend a published commit.
