# BRIEF: CODEX_WAKE_ENTER_SUBMIT_1 — codex card wake must auto-run, not wait for Enter

## Context
Director-flagged 2026-06-01: clicking the **codex** card on the Brisen Lab dashboard injects the
`check bus` nudge into the running codex Terminal session, but the text **sits in codex's input
until Director manually presses Enter**. Every other agent (Claude Code pickers) auto-runs. Only
codex is affected because it runs the OpenAI `codex` CLI (a full-screen TUI), not `claude`.

### Surface contract
1. **Surface:** existing dashboard codex card click → `fetch('/api/wake?alias=codex')` → SSE → local `wake-listener` → `open brisen-lab://wake/codex` → this AppleScript handler. No new UI element; behavior fix only.
2. **Trigger path verified:** wake-listener already lists `codex` in ALLOWED_ALIASES; the gap is purely in the AppleScript handler (Director confirms the text arrives, just doesn't submit).
3. **Destination correct:** the command must land in + submit to the *codex* session specifically (matched by the `codex` process), not another tab.
4. **No misfire:** clicking codex must not nudge a Claude picker or spawn a stray window.
5. **Failure mode:** if no live codex session, fall through to the existing graceful "no picker" path (no crash, no error spam).
6. **Cross-machine note:** wake fires on whichever machine runs the wake-listener (the laptop). Mac-Mini install is OUT OF SCOPE here.

## Estimated time: ~1.5h
## Complexity: Medium (AppleScript + live TUI behavior; needs real-session testing)
## Prerequisites: a live codex session open in Terminal for the acceptance test (Director launches via `cdx`)
## Repo: brisen-lab (NOT baker-master). Work in a brisen-lab clone; PR to brisen-lab main.

## Harness V2
- **Context Contract:** edit `tools/wake-handler/wake-handler.applescript` (brisen-lab). Read-only refs: `~/.zshrc` `cdx()`, `~/.brisen-lab/wake-listener.py` (no change). Build artifact via `tools/wake-handler/build.sh` → `~/Applications/Brisen Lab Wake.app` (+ `lsregister -f`). No baker-master / Cortex / DB / network / secret surface.
- **Task class:** bug-fix — Mac-local tooling / AppleScript TUI-submit behavior. Not production-server, not DB, not API.
- **Done rubric / done-state class:** behavioral (live-exercised, NOT compile-clean). DONE = clicking the codex card auto-runs `check bus` in a live codex session with zero manual Enter, AND a Claude-picker wake still auto-runs (no regression). "Compiles / by inspection" is explicitly insufficient.
- **Gate plan:** G1 = lead live-verifies the acceptance test (codex auto-run + Claude-picker regression) before merge. G2 `/security-review` = N/A (no network/secret/DB/path-join added — pure local AppleScript + key event; declare N/A in ship report). No G3 production-deploy gate (no server surface; artifact is a local .app rebuild).

---

## Fix: wake-handler must detect + submit to the codex TUI

### Problem
`tools/wake-handler/wake-handler.applescript` was built for Claude Code pickers. For codex it fails three ways:
1. **No codex entry** in the `cwdForAlias` map (lines ~42-57) or the `fnMap` map (lines ~138-150) — codex/codex-arch are absent.
2. **Detection mismatch:** `findRunningPickerTab` greps the tty's foreground process for `claude` (`awk '/claude/'`) and matches by picker **cwd**. codex runs the `codex` binary via the `cdx()` zsh function (`codex -m gpt-5.5`) and does **not** cd to a fixed picker dir — so it is never detected.
3. **No submit:** even when a command is delivered via `do script ... in <tab>`, codex's full-screen TUI does **not** execute it — the line stays in codex's input box. codex needs an explicit **Return key event** (System Events `key code 36`) to submit, which `do script` does not deliver to a raw-mode TUI.

### Current State
- Handler entry point: `on open location this_URL` (handles `brisen-lab://wake/<alias>`).
- Detect-then-nudge block: finds a Terminal tab running the picker, then `do script "check bus" in <tab>`.
- `cdx()` is defined in `~/.zshrc` (~line 96): sets `BAKER_ROLE=codex` + 1P key, then runs `codex -m gpt-5.5`. No `cd`.
- codex IS already a valid bus recipient/sender (`scripts/bus_post.sh` + `.py` whitelists) and the wake-listener `~/.brisen-lab/wake-listener.py` already lists `codex` in `ALLOWED_ALIASES` — so the SSE→listener→`open brisen-lab://wake/codex` path already fires; only the AppleScript handler mishandles codex.

### Implementation
1. **Add codex (and codex-arch) to both maps.** In `fnMap` add `{"codex", "cdx"}` (and `{"codex-arch", "<fn>"}` — confirm its zsh fn name; if codex-arch has no terminal picker, omit it and let it fall to the existing graceful "no picker" path). For `cwdForAlias`, codex has no stable picker dir — see step 2.
2. **codex-specific session detection.** codex cannot be matched by cwd. Add a detection branch: when `aliasName` is `codex`, in `findRunningPickerTab` match the tab whose tty foreground process command contains `codex` (the binary) instead of `claude`. Generalize cleanly (e.g. pass the expected process-name token per alias: `claude` for Claude pickers, `codex` for codex) rather than hard-forking the whole function.
3. **Explicit submit for the codex TUI.** After the `do script` (or in place of it) for codex, bring the matched Terminal tab/window to front and send a Return key event:
   ```applescript
   tell application "Terminal" to set frontmost to true
   tell application "Terminal" to set selected tab of window id <wid> to <tab>  -- ensure focus
   delay 0.2
   tell application "System Events" to key code 36  -- Return
   ```
   Validate empirically: if `do script` already delivers the text but not the submit, only the `key code 36` is needed; if `do script` does not even deliver the text to the TUI, switch to `System Events` `keystroke "check bus"` then `key code 36`. **Test against a live codex session and use whichever actually submits.**
4. **Rebuild + register.** Run `tools/wake-handler/build.sh` to rebuild `~/Applications/Brisen Lab Wake.app`, then `lsregister -f ~/Applications/Brisen\ Lab\ Wake.app`. Preserve the existing Apple Events automation grant (System Settings → Privacy & Security → Automation → Brisen Lab Wake → Terminal + System Events). If System Events control is newly required, note Director must approve the one-time Automation prompt.

### Key Constraints
- **Do NOT touch** `db.py` or `bus.py` — cowork-ah1 has active edits there (conn-harden + read-ordering). Do NOT touch the dashboard frontend (`app.js`, `app.py`, `static/`).
- Keep all existing aliases working unchanged — the codex branch must not regress Claude-picker detection/submit.
- Keep the graceful "no terminal picker installed for alias X" fallback intact.
- No secrets in brief/code; codex's 1P key handling stays in `cdx()`, untouched.

### Verification (must be live — no "by inspection")
1. Launch a real codex session (`cdx`) in Terminal.
2. Click the codex card on the dashboard (or run `open 'brisen-lab://wake/codex'`).
3. **PASS:** the `check bus` command executes in the codex session automatically, with **no** manual Enter.
4. Regression: click a Claude picker card (e.g. `lead` or `b1`) → still detects + auto-runs as before.
5. Capture the exact AppleScript path used (key code 36 only, vs keystroke+key code 36) in the ship report.

---

## Files Modified
- `tools/wake-handler/wake-handler.applescript` — codex maps + codex-process detection + explicit Return submit.
- (rebuilt artifact) `~/Applications/Brisen Lab Wake.app` — via `build.sh` (local, not committed).

## Do NOT Touch
- `db.py`, `bus.py` — cowork-ah1 active edit set.
- `app.js` / `app.py` / `static/*` — dashboard frontend, unrelated.
- `~/.brisen-lab/wake-listener.py` — already allows codex; no change needed.

## Quality Checkpoints
1. Live codex auto-run PASS (no manual Enter).
2. Claude-picker wake regression PASS.
3. Wake.app rebuilt + lsregister'd; brisen-lab:// still resolves.
4. Graceful no-session fallback intact.

## Reporting
Ship report → bus topic `ship/codex-wake-enter-submit-1` to **lead**. `dispatched_by: lead`.
Note in the report the exact submit mechanism that worked + whether a new Automation grant was needed.
