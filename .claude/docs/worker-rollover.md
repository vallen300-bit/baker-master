# Worker Rollover Runtime Notes

Canonical process: `baker-vault/_ops/processes/worker-checkpoint-respawn.md`.

## Stop Hook

`.claude/hooks/context-threshold-check.sh` reads the Stop-event `transcript_path`, estimates tokens as `bytes / 4`, and compares that estimate with a per-picker window resolved in this precedence (first hit wins; `settings.local.json` is read before `settings.json` so a per-seat override beats the shared base):

1. env `ROLLOVER_WINDOW_TOKENS`
2. `.claude/settings.local.json` key `rollover_window_tokens`, then nested `rollover.window_tokens`
3. `.claude/settings.json` key `rollover_window_tokens`, then nested `rollover.window_tokens`

`rollover_soft_percent` / `rollover_hard_percent` resolve the same way (env → `settings.local.json` → `settings.json` → built-in default 70 / 85).

The hook is silent below 70%, emits a checkpoint reminder at 70%, and emits a hard checkpoint-now instruction at 85%.

**Block-at-most-once (hard band).** Over the hard band the hook returns `decision:block` exactly once per session — keyed to a marker at `<transcript_path>.rollover-blocked` — then steps aside (`block=False`) on every later Stop. A Stop hook that blocks forces the session to *continue*, never to stop; blocking every Stop would trap the session in a self-feeding loop (each blocked turn grows the transcript, pushing the percentage higher — BB desk ran 137→153%, +21.4k tokens, 2026-07-08, Director-witnessed). One block forces the checkpoint; the successor is spawned by orchestrator-wake, so the clean exit that follows loses nothing.

**Known limit.** Measurement happens only at Stop (turn end). One very long turn can jump from under the soft band to far over hard in a single measurement (BB desk first-fired at 137%). Mid-turn metering is the outer context-cost watchdog's job, not this hook's.

Install or refresh settings with:

```bash
python3 scripts/install-rollover-stop-hook.py --settings .claude/settings.json --window-tokens 1000000
```

Use each picker's real engine window. Do not hardcode model window sizes into the hook.

## Respawn Request

After writing and pushing `briefs/_checkpoints/<BRIEF_ID>.checkpoint.md`, post a respawn request to the dispatcher and self:

```bash
BAKER_ROLE=b2 scripts/respawn-request.sh lead BRIEF_ID briefs/_checkpoints/BRIEF_ID.checkpoint.md 1 b2/branch-name "state summary"
```

The helper posts topic `rollover/<BRIEF_ID>` and body `RESPAWN_REQUEST ...`.

Claim is the checkpoint `attempt:` bump commit, not bus ack. A fresh session must increment `attempt:`, commit, and push before resuming. If another session already bumped the counter, stand down.
