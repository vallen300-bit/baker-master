# WAKE_RESUME_BRIDGE_DIAG_1 — diagnosis report (b2, 2026-06-06)

**Brief:** runtime diagnosis — terminals (codex, deputy-codex) not draining bus on wake.
**Class:** runtime diagnosis (local host). Fix is code (wake-handler match logic) + optional host-side defense-in-depth.
**Dispatched by:** lead. **Diagnosis only — no PR shipped** (deploy is grant-sensitive + Director-gated; live AC not runnable from a b2 session — see Constraints).

## Root cause (high confidence, reproduced live 2026-06-06 15:07 CEST)

The wake nudge for codex-runtime aliases fails because `findRunningPickerTab` in the
Wake.app picks the **wrong process** off the codex tab's controlling tty.

The match shell (wake-handler.applescript, `findRunningPickerTab`):

```
pid=$(ps -t <tty> -o pid=,command= | awk '/<procPattern>/ && !/awk/ {print $1; exit}')
cwd=$(lsof -a -p $pid -d cwd ...)        # cwd of THAT one pid only
if [ "$cwd" = "<targetDir>" ] ...; then echo MATCH $pid ...; else echo NO; fi
```

For codex/deputy-codex, `procPattern` is `codex`. The Director also runs the **Codex
GUI app** (`/Applications/Codex.app`, started Jun 3 15:41). Its helper processes
— `/Applications/Codex.app/Contents/Resources/codex app-server --listen stdio://`
and `node_repl` — carry lowercase `codex` in their command line **and share the
same controlling tty** as the real deputy-codex CLI tab (ttys012 right now).

`ps -t ttys012` therefore lists many `codex`-matching rows. The awk does
`{print $1; exit}` — it returns the **first** one (a Codex.app `app-server`,
e.g. pid 11145), not the real deputy-codex CLI (pid 47724/47728). It then tests
**only that first pid's cwd**.

Two failure modes follow:
1. **Match fails (the symptom).** When the first codex-named process's cwd ≠ the
   picker dir (a Codex.app app-server pointed at a different project), the guard
   returns `NO`. The handler concludes "no running tab" and falls through to the
   **spawn fallback** → opens a *new* Terminal running the picker fn. The live
   deputy-codex tab is never nudged → message sits unacked. Repeated wakes each
   spawn another duplicate; none reach the live session. This matches #2034
   (deputy-codex woken ~7× 13:12–14:17, never acked).
2. **Wrong-PID match.** When the first process's cwd *coincidentally* equals the
   picker dir (the live state at 15:07 today), `MATCH` returns the app-server's
   pid as `claudePid`. The nudge still hits the right *tab* (good), but the
   returned pid is wrong — so the stale-kill path would `kill` a Codex.app
   app-server instead of the codex CLI.

**Why intermittent:** which codex-named process sorts first on the shared tty,
and what its cwd is, both vary with the Codex.app GUI lifecycle (it spawns/kills
app-server + node_repl on demand). Morning wakes (#PR-A/#PR-B) landed when the
first match was benign; afternoon wakes failed when it wasn't. Same code path,
different runtime state — exactly the reported pattern.

Live repro (2026-06-06 15:07):
```
ps -t ttys012 ... | awk '/codex/{print;exit}'  -> 11145  /Applications/Codex.app/.../codex app-server
# real deputy-codex CLI is 47724 (node /opt/homebrew/bin/codex) / 47728, later in the list
```

## Brief questions answered

1. **What the `brisen-lab://wake/<slug>` handler does:** `~/Applications/Brisen Lab
   Wake.app` (AppleScript applet, URL scheme `brisen-lab`). Nudge-first /
   spawn-fallback: if it finds a Terminal tab running the alias's CLI in the
   picker dir, it `do script "check bus" in <tab>` (Apple Events) and fronts the
   window; else it writes `/tmp/brisen-lab-wake-<fn>.command` and `open -a Terminal`
   to spawn a new session. It injects input into an **already-running REPL**; it
   does not start a Claude session on the nudge path.
2. **Does the wake deliver input to an idle session?** For Claude pickers — yes,
   reliably (proven: this b2 session's first message was the injected `check bus`).
   The `do script` carriage return submits for Claude. For **codex** the embedded
   return does NOT submit (raw-mode TUI); a second empty `do script ""` sends the
   submitting CR. The break is *before* this step — the tab is never matched (mode
   1 above), so nothing is injected at all.
3. **SessionStart bus-drain hook on wake?** No. `~/.claude/hooks/session-start-bus-drain.sh`
   is a **Claude Code SessionStart** hook — it fires on a fresh Claude session
   (startup/resume/spawn), NOT when the handler injects text into a live REPL.
   Codex is not Claude Code, so the hook never runs for codex at all. There is
   **no cron/launchd codex self-drain** either. So for an already-running codex,
   the wake nudge landing is the ONLY drain trigger — no safety net. One missed
   nudge = indefinitely unacked.
4. **Working vs non-working terminal:** Claude pickers (b1–b4, lead, deputy,
   desks) — nudge works (do-script return submits; no Codex.app tty pollution).
   codex/deputy-codex — share their tty with Codex.app GUI helpers → match grabs
   the wrong pid → intermittent spawn-fallback instead of nudge.

## Proposed fix (code — `tools/wake-handler/wake-handler.applescript`)

Harden the process selection in `findRunningPickerTab`:
- **Exclude the Codex GUI app:** drop any row whose command contains
  `/Applications/Codex.app/` (and/or `app-server`, `node_repl`, `--listen stdio`).
- **Don't `exit` on first match:** iterate the codex-named procs on the tty and
  pick the one whose cwd matches `targetDir` (and ≠ `excludeDir`), i.e. move the
  cwd test *inside* the per-process loop instead of testing only the first hit.
  This finds the real CLI even when a GUI helper sorts ahead of it.

Optional defense-in-depth (separate decisions, not required for the fix):
- **Codex self-drain safety net (host config):** a launchd/cron poll running
  `check-codex-inbox.sh` every N min so codex drain no longer depends solely on a
  fragile UI nudge. Describe-for-AH1 (host), not a code PR.
- **Nudge-landed confirmation:** today the listener logs `dispatched` even when
  the in-app match fails — a blind spot. A post-nudge ack-check + retry would
  close it (code, heavier).

## Constraints on shipping/deploying (why no PR auto-shipped)

- **Repo↔local drift (Lesson #94):** the repo `findRunningPickerTab` is
  `(targetDir, procPattern)` — **2 params, missing `excludeDir`** that the
  deployed local app has (2026-06-05 Lesson #95 fix). A rebuild-from-repo would
  REGRESS the deputy-codex-vs-codex disambiguation. Any PR must first mirror the
  live app state back into the repo, then add the hardening.
- **Grant-sensitive deploy (Lesson #93):** deploying = in-place osacompile onto
  the live bundle + `codesign --force` (NOT `build.sh`'s rm-rf rebuild, which
  drops the Apple Events Automation grant fleet-wide). Needs Director present.
- **Unverifiable from here (Lesson #84):** live AC must reproduce a non-Terminal-
  frontmost wake through `open brisen-lab://wake/deputy-codex` and observe the
  real codex tab drain. Cannot be done from this b2 session.

## Recommendation

Ship a single brisen-lab PR that (1) reconciles repo↔local drift (restore
`excludeDir`) and (2) hardens the match (exclude Codex.app procs + loop-until-cwd-
match). Deploy via in-place osacompile in a Director-present window; verify through
the real wake surface. Treat the launchd codex self-drain poll as a fast follow —
it removes the single-point-of-failure regardless of match correctness.
Awaiting lead's go on PR + deploy sequencing.

---

## FIX SHIPPED — WAKE_RESUME_BRIDGE_FIX_1 (lead GO, bus #2051)

**PR:** brisen-lab #67 — https://github.com/vallen300-bit/brisen-lab/pull/67
**Branch:** `b2/wake-resume-bridge-fix-1`. **Bus to lead:** #2064 (ship), #2050 (root cause).

Two commits as scoped:
- `0adb71d` — reconcile repo↔local drift: restore `excludeDir` to `findRunningPickerTab`
  so repo is byte-identical to the live bundle (Lesson #94). No behavior change vs prod.
- `5cc74d9` — the fix in `matchScript`: (a) exclude non-CLI "codex"-bearing procs
  `!/Codex.app/ && !/app-server/ && !/heartbeat-ticker/`; (b) loop instead of awk
  exit-on-first, selecting the first candidate whose cwd matches target (and ≠ excludeDir).
  Finds the real CLI regardless of `ps` order; returns the correct pid for stale-kill.

**Root cause sharpened during build:** the loose `/codex/` awk also matched the forge
`heartbeat-ticker.sh ... deputy-codex` (not just Codex.app `app-server`); both share the
CLI tab's controlling tty. Fix excludes both.

**G1 evidence:**
- Deterministic test `tools/wake-handler/test-find-picker-selection.sh` (no live deps,
  `/bin/sh`): 6 cases — prod failure (A), benign-but-wrong-pid (B), reviewer/deputy
  disambiguation (C/C2), noise-only (D). ALL PASS.
- Live `/bin/sh` repro: `ttys012` → `47724` (real deputy-codex CLI; was NO/app-server),
  `ttys017` → `21131` (reviewer, no regression). `osacompile` clean.

**Not done (correctly out of scope):**
- Deploy — AH1/lead Tier-B: in-place `osacompile` + `codesign --force` (NOT `build.sh`
  rm-rf, Lesson #93), live AC via real non-Terminal-frontmost wake (Lesson #84).
- Launchd codex self-drain poll — noted as follow-up in the PR description; not built.

**Gate status:** awaiting lead G1 → G2 → G3 codex.

---

## REBASE — lead #2067 (2026-06-06 ~13:55)

PR #67 conflicted with main after PR-C/#66 merged. Two main commits landed on the
same file: `fb79cf3` (AH2 — added `excludeDir` to the repo, the same drift my
`0adb71d` was restoring) and `4c5e1f0`/#66 (clerk-haiku wake wiring).

Resolution: `git rebase --onto origin/main 0adb71d` — dropped my now-redundant
`0adb71d` (main already has `excludeDir` via fb79cf3), replayed only the fix commit
(`5cc74d9` → `23832d2`). **Zero conflicts** — my matchScript change (~line 124) does
not overlap #66's clerk-haiku additions (cwdForAlias line 62, fnMap line 209).

Merged `wake-handler.applescript` verified to contain BOTH:
1. PR-C/#66 clerk-haiku entries (lines 62, 209).
2. My fix — Codex.app/app-server/heartbeat-ticker exclusion (124) + cwd-loop (126-133)
   + `excludeDir` preserved in the loop (129; 3-param signature line 90).

G1 re-run: `test-find-picker-selection.sh` ALL 6 PASS; osacompile clean.
Force-pushed `--force-with-lease`. PR #67 now **MERGEABLE** (head `23832d2`).
codex G3 PASS (#2066) unchanged by rebase. Confirmation posted to lead bus #2068.
Deploy remains lead Tier-B.
