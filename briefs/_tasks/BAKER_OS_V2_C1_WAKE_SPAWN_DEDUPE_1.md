# BRIEF: BAKER_OS_V2_C1_WAKE_SPAWN_DEDUPE_1 — seat pile-up + swallowed spawn errors (wake handler)

dispatched_by: lead
reply_to: lead (bus topic `baker-os-v2/c1-wake-spawn-dedupe`)
Harness-V2: task class = bugfix (infra, non-Baker-prod) · Context Contract below · done rubric §Verification · gate plan: codex bus review (reasoning_effort=medium) → lead merge. POST_DEPLOY_AC_VERDICT: N/A — local tooling, no Render deploy; live AC = scripted wake drill below.

## Context
ClickUp C1 (86cakdynn), Baker OS V2 rollout. Two Aukera-pilot glitches: (1) repeated wakes piled up 4 duplicate desk Terminal windows; (2) wake fires but no window opens and nothing is logged. Both live in the wake handler, NOT the bus daemon — server 5s debounce stays as is. Roadmap: `baker-vault/_ops/build/baker-os-v2/05_outputs/baker-os-v2-execution-roadmap-20260706.md` §3 C1.

**Repo:** brisen-lab (your own checkout; canonical file `tools/wake-handler/wake-handler.applescript`). Do NOT edit `/Users/dimitry/brisen-lab-staging` directly — that is a deploy target, rebuilt from repo.

## Estimated time: ~3h · Complexity: Medium · Prerequisites: none

## Current state (verified 2026-07-06)
- `wake-handler.applescript:89-149` `findRunningPickerTab()` — scans Terminal tabs for live `claude`/`codex` with cwd = `cwdForAlias(slug)`; fresh (<8h) → nudge, else spawn.
- `wake-handler.applescript:244-296` — nudge path wrapped in try; **on ANY nudge error it silently falls through to spawn**. This is the pile-up: live session + broken Apple-Events grant ⇒ every wake spawns a new window.
- `wake-handler.applescript:303-305` — spawn `do shell script "open -a Terminal " & quoted form of cmdPath` is **outside any try** — failures (−1743/−600/−609, TCC timeout) vanish silently.
- `wake-handler.applescript:41-63` `cwdForAlias()` — hardcoded map; `cowork-bb-desk` returns `/Users/dimitry/baker-vault` (generic fallback) while the real picker dir is `~/bm-cowork-bb-desk` ⇒ nudge scan never matches ⇒ spawn every time (second pile-up cause).

## Engineering craft gates
- Diagnose: applies — repro loop = fire 3 wakes 10s apart at a slug with a live session and a broken/absent automation grant; pass = 0 new windows + logged nudge failures; fail = stacked windows. Hypotheses (ranked): H1 nudge-fail→spawn fallback (confirmed by code read); H2 cwdForAlias mismatch (confirmed for cowork-bb-desk); H3 server debounce gap (out of scope — client fix suffices).
- Prototype: N/A — failure modes already reproduced live 2026-07-06; code paths confirmed.
- TDD/verification: no honest unit seam in AppleScript — verification is the scripted live drill below (documented, repeatable).

## Fix 1 — nudge failure must NOT fall through to spawn
In the `on open location` nudge block (lines 244-296): when `findRunningPickerTab()` FOUND a fresh session but the nudge (`do script` into the tab) errors, log via `do shell script "logger -t brisen-lab-wake ..."` + append to `~/.brisen-lab/wake-handler.log`, retry the nudge once after 2s, and if it fails again **exit without spawning** (a live session exists; spawning duplicates it). Spawn remains ONLY for: no session found, or stale session (existing SIGTERM path unchanged).

## Fix 2 — spawn error trap
Wrap lines 303-305 in try/on error: log `SPAWN FAILED for <slug>: <err> (<errNum>)` to syslog (`logger -t brisen-lab-wake -s`) AND `~/.brisen-lab/wake-handler.log`. No fallback launcher — a visible logged failure is the goal (fail loud).

## Fix 3 — per-slug spawn lock
Before spawn: create `/tmp/brisen-lab-spawn-<slug>.lock` via `do shell script`; if a lock younger than 60s exists, log `SPAWN SUPPRESSED (lock)` and exit. Remove/ignore stale locks >60s. Prevents concurrent-wake double spawn.

## Fix 4 — cwdForAlias correction
Fix `cowork-bb-desk` → `/Users/dimitry/bm-cowork-bb-desk` in `cwdForAlias()`. Then add a comment block anchoring the map to `scripts/agent_identity_generated.sh` `AGENT_IDENTITY_SNAPSHOT_TERMINALS` as source of truth. (Full dynamic lookup is a later brief — do not build it now.)

## Key constraints
- Do NOT touch bus.py / server-side wake emission (debounce stays 5s).
- Do NOT change the 8h freshness threshold or the stale-kill path.
- Do NOT rebuild/re-sign the deployed handler on the Mac Mini — C4 hold (Director). Build + deploy on the MacBook only; Mini redeploy rides the C4 release.
- Follow repo build script (`tools/wake-handler/build.sh` or equivalent) — note its codesign step is the C4 subject; do not "fix" signing here.

## Verification (done rubric)
1. Drill A (dup guard): live lead session + 3 wakes 10s apart → 0 new windows, nudges logged.
2. Drill B (nudge-fail): revoke/absent automation grant sim (or temporarily rename grant target), fire wake → NO spawn, 2 logged nudge failures.
3. Drill C (spawn error): point `open -a` at a bogus app name in a scratch copy → error logged loudly, handler exits clean.
4. Drill D (lock): 2 wakes 3s apart, no live session → exactly 1 window.
5. `cwdForAlias("cowork-bb-desk")` returns the bm- path (grep).
Report drill transcript in your completion post. Any drill you cannot run — say so explicitly, do not report done.

## Files modified
- `tools/wake-handler/wake-handler.applescript` (brisen-lab repo) — 4 fixes above.
## Do NOT touch
- `bus.py` — server wake emission out of scope.
- `tools/wake-listener/` — allowlist already correct.
- Mac Mini deployment — held (C4).
