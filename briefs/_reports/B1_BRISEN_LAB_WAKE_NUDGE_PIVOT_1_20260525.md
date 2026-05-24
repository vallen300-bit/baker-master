# B1 ship report — BRISEN_LAB_WAKE_NUDGE_PIVOT_1

**Date:** 2026-05-25
**Brief:** `briefs/BRIEF_BRISEN_LAB_WAKE_NUDGE_PIVOT_1.md`
**Mailbox:** `briefs/_tasks/CODE_1_PENDING.md` (dispatched_at 2026-05-25T10:00Z by cowork-ah1)
**Branch:** `b1/brisen-lab-wake-nudge-pivot-1` (brisen-lab repo)
**PR:** https://github.com/vallen300-bit/brisen-lab/pull/36
**Predecessor merged:** PR #34 main is the baseline for this surgical edit.

## Scope

Detect-then-nudge with spawn-fallback in `tools/wake-handler/wake-handler.applescript`. Two new handlers (`cwdForAlias`, `findRunningPickerTab`) + nudge block inserted in `on open location` between the fnMap-not-found error block and the existing spawn block. README updated for nudge-first behavior + one-time AE grant + dual-map maintenance. Two correctness fixes in `build.sh` discovered during verification:

1. **Missing CFBundleIdentifier.** osacompile does not set it. Without it tccd cannot identify the bundle, so the macOS Automation prompt never surfaces and `tccutil reset AppleEvents com.brisen.lab.wake` errors with "No such bundle identifier".
2. **Post-PlistBuddy re-sign.** osacompile applies an ad-hoc signature at compile time; PlistBuddy mutations to Info.plist invalidate it. `codesign --force --deep --sign -` after the plist edits gives macOS a valid bundle to evaluate for TCC.

A third correctness fix was needed in the AppleScript itself:

3. **Tab iteration bug.** `repeat with t in tList` binds `t` to a list-of-references (`{«class ttab» 1 of window id ...}`) which cannot be dereferenced for `tty of t` or `index of t`. The error caught inside the inner `try` block on every iteration → `findRunningPickerTab` always returned `{0, 0}` → spawn always fired even when grant + matching tab were present. Fix: index-based iteration (`repeat with i from 1 to count of tList; set t to item i of tList`).

## Verification (all 5 brief cases)

### Build

```
.: replacing existing signature
/Users/dimitry/Applications/Brisen Lab Wake.app: replacing existing signature
Installed: /Users/dimitry/Applications/Brisen Lab Wake.app
Registered URL scheme: brisen-lab://
```

Exit 0. `CFBundleIdentifier=com.brisen.lab.wake` confirmed via PlistBuddy. `codesign -dv` shows `Identifier=com.brisen.lab.wake / Signature=adhoc`.

### Case 2 — first-grant (Director action)

`tccutil reset AppleEvents com.brisen.lab.wake` → clean slate. `open 'brisen-lab://wake/lead'` triggered the macOS system dialog "Brisen Lab Wake wants to control Terminal.app." Director clicked OK. TCC.db verified post-grant:

```
sqlite3 ~/Library/Application\ Support/com.apple.TCC/TCC.db \
    "SELECT service, auth_value FROM access WHERE client='com.brisen.lab.wake';"
kTCCServiceAppleEvents|2
```

`auth_value=2` (allow).

### Case 3 — nudge happy path

With ttys002 + ttys032 both running `aihead1` picker (claude foreground, cwd=`/Users/dimitry/bm-aihead1`):

```
rm -f /tmp/brisen-lab-wake-aihead1.command
open 'brisen-lab://wake/lead'
sleep 10
ls -la /tmp/brisen-lab-wake-aihead1.command 2>/dev/null
```

`/tmp/brisen-lab-wake-aihead1.command` was NOT created (no spawn). Director observed `check bus` typed into lead's claude prompt + window brought to front. Nudge fired end-to-end.

### Case 4 — spawn fallback when no matching tab

```
open 'brisen-lab://wake/b3'
sleep 3
cat /tmp/brisen-lab-wake-b3.command
#!/bin/zsh -il
b3
```

Spawn `.command` file written (b3 is not currently running a picker — `findRunningPickerTab` returned `{0, 0}`, the `if wId is not 0` guard skipped the nudge, fell through to spawn). New Terminal window appeared on screen running `b3()`.

### Case 5 — graceful degrade with no AE grant

Pre-grant runs (before the CFBundleIdentifier + signature + iteration fixes were all in place) all fired the spawn fallback cleanly. No error dialog, no crash, no hung handler — the `try / on error` around the nudge body absorbed the AE permission error and the existing `.command` spawn path ran normally. Each pre-grant fire of `open 'brisen-lab://wake/<alias>'` produced a fresh `/tmp/brisen-lab-wake-<fn>.command` file + a popped Terminal window. Same path tested explicitly via tccutil reset twice during diagnosis.

### Case 6 — unknown alias

```
open 'brisen-lab://wake/garbage-alias-test'
sleep 2
cat /tmp/brisen-lab-wake-error.command
#!/bin/zsh
echo
echo 'Brisen Lab Wake: no terminal picker installed for alias garbage-alias-test'
echo
read -k1 '?Press any key to close...'
```

Sanitized error `.command` file written + Terminal popped with friendly message + press-any-key wait. fnMap behavior unchanged.

## Diagnosis path (root-cause notes for lessons.md / future debugging)

When Director's first nudge attempt fell through to spawn instead of bringing lead's Terminal to front, three issues had to be untangled:

1. `tccutil reset AppleEvents com.brisen.lab.wake` returned `No such bundle identifier`. That surfaced the missing CFBundleIdentifier — the .app was anonymous to tccd, so no prompt could be addressed to it.
2. After adding CFBundleIdentifier and re-signing, tccd correctly surfaced the prompt + recorded auth_value=2. BUT spawn still fired. TCC was clean.
3. Probing `findRunningPickerTab` via `osascript` returned `NO MATCH` even though a manual ttys enumeration (same `ps`/`lsof` shell-out) found two matching tabs. That isolated the bug to AppleScript-level tab iteration: `repeat with t in tList` binds `t` to a list-of-references unfit for `tty of t` / `index of t`. Index-based iteration resolved it. The `try / on error` inside the loop was silently absorbing the dereference error on every iteration, leaving `{0, 0}` as the final result.

Suggested lessons.md entry: "Pop-up `display dialog` is not the only LSUIElement-swallowed UI — system TCC prompts are silently broken too if the bundle has no CFBundleIdentifier. Always set CFBundleIdentifier on osacompile-built .apps that use Apple Events."

## Gate-1 + Gate-2 invariants (per brief §reviewer instructions)

| # | Invariant | Status |
|---|-----------|--------|
| 1 | `fnMap` unchanged (14 entries, same case + aliases) | ✓ |
| 2 | `cwdForAlias` covers same 14 aliases as `fnMap` (parallel map) | ✓ |
| 3 | No frontend changes (`app.js`, `index.html`, `styles.css` untouched) | ✓ |
| 4 | No new HTTP routes (server-side untouched) | ✓ |
| 5 | All 5 verification cases pass in real environment | ✓ |

## Files modified

- `tools/wake-handler/wake-handler.applescript` — `cwdForAlias` + `findRunningPickerTab` handlers + nudge block in `on open location` + header comment updated.
- `tools/wake-handler/README.md` — nudge-first behavior section + one-time-setup section + dual-map-maintenance section.
- `tools/wake-handler/build.sh` — CFBundleIdentifier add + post-PlistBuddy codesign.

## Gate chain (per mailbox)

- Gate-1 architecture: deputy (AH2)
- Gate-2 `/security-review`: deputy (AH2) — AppleScript shell-out injection surface deserves a careful pass even though `targetDir` comes from a bounded hard-coded map
- Gate-3 picker-architect: SKIP (no install change, no picker symlink change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: lead (AH1)

## Next step

Bus-post `ship/wake-nudge-pivot-1` to cowork-ah1 (per mailbox reply-target rule). cowork-ah1 dispatches the gate chain through deputy + lead.
