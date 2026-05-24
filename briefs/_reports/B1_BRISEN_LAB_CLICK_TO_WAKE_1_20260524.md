# B1 ship report — BRISEN_LAB_CLICK_TO_WAKE_1

**Date:** 2026-05-24
**Brief:** `briefs/BRIEF_BRISEN_LAB_CLICK_TO_WAKE_1.md`
**Mailbox:** `briefs/_tasks/CODE_1_PENDING.md` (dispatched_at 2026-05-24T21:18Z by lead)
**Branch:** `b1/brisen-lab-click-to-wake-1` (brisen-lab repo)
**PR:** https://github.com/vallen300-bit/brisen-lab/pull/34
**Commit:** `9fc95e8`

## Scope

Components 1+2 of brief shipped as a single brisen-lab PR. Component 3 (baker-vault SOP Row 13) is queued for a separate PR after this merges + Render deploy verifies.

## Mid-build IPC design change (Director-ratified mid-flight)

Brief originally specified `tell application "Terminal" to do script fnName` for Component 1's AppleScript handler. Local smoke testing surfaced an error `-1743 errAEEventNotPermitted` — macOS TCC `kTCCServiceAppleEvents` blocks the cross-app Apple Event on first use, and the permission prompt is silently swallowed under `LSUIElement=true` (required to hide the app from Cmd+Tab per brief constraint).

Blocker bus-post #945 (b1 → lead) at 2026-05-24T21:30Z surfaced the gap + recommended Option B (`.command` file IPC). Director ratified Option B with "go" the same turn.

Final mechanism: AppleScript writes `/tmp/brisen-lab-wake-<fn>.command` (zsh `-il` shebang + picker function name) and runs `open -a Terminal <path>`. No Apple Events boundary crossed, no per-app Automation permission grant required. Fail path uses the same Terminal-pop mechanism (display dialog also silently swallowed under LSUIElement).

## Ship-gate items (literal output)

### 1. `bash tools/wake-handler/build.sh`

```
.: replacing existing signature
Installed: /Users/dimitry/Applications/Brisen Lab Wake.app
Registered URL scheme: brisen-lab://

Verify with:
  /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -dump | grep -A1 brisen-lab

Smoke test:
  open 'brisen-lab://wake/b1'
```

Exit 0.

### 2. `lsregister -dump | grep -A1 brisen-lab`

```
claimed schemes:            brisen-lab:
--
claim id:                   com.brisen.lab.wake (0x10440)
localizedNames:             "LSDefaultLocalizedValue" = "com.brisen.lab.wake"
rank:                       Default
--
flags:                      url-type (0000000000000040)
roles:                      Viewer (0000000000000002)
bindings:                   brisen-lab:
```

Default-ranked Viewer claim under `com.brisen.lab.wake` (our app).

### 3. `open 'brisen-lab://wake/b1'` — visual confirmation

Terminal window count before: 10. After: 11. Delta +1. The new window opened, sourced `~/.zshrc` via the `#!/bin/zsh -il` shebang, ran `b1()` which `cd ~/bm-b1` + set title "B1" + spawned `claude` — Claude Code boot indicator (`✳`) visible in window title within ~2 seconds.

### 4. `open 'brisen-lab://wake/CM-1'` (case-sensitive uppercase)

Terminal window count before: 11. After: 12. Delta +1. `cm1` shell function executed in the new window. Confirms uppercase alias correctly maps to lowercase shell function name per `fnMap`.

### 5. `open 'brisen-lab://wake/cm1'` (case-sensitive lowercase — fail path)

Terminal window count before: 12. After: 13. Delta +1. Fail-path Terminal opened with sanitized error message:

```
$ cat /tmp/brisen-lab-wake-error.command
#!/bin/zsh
echo
echo 'Brisen Lab Wake: no terminal picker installed for alias cm1'
echo
read -k1 '?Press any key to close...'
```

Confirms case-sensitivity enforced (canonical is `CM-1`, lowercase `cm1` hits fail path).

### 6. `open 'brisen-lab://wake/no-such-alias'` — fail path

Terminal window count before: 11. After: 12. Delta +1. Same fail-path Terminal mechanism, error message reflects the sanitized alias name.

### 7. Frontend grep — `WAKEABLE_ALIASES` line

```
$ grep -n "WAKEABLE_ALIASES" static/app.js
896:const WAKEABLE_ALIASES = new Set(TERMINALS);  // exactly the 14 installed pickers
899:    const wakeable = WAKEABLE_ALIASES.has(alias);
```

Derived from existing `TERMINALS` const (no hand-typed duplicate per Gate-1 invariant #2).

### 8. Cache-bust paired bump

```
$ grep -n "app.js?v=\|styles.css?v=" static/index.html
7:  <link rel="stylesheet" href="/static/styles.css?v=13">
131:  <script src="/static/app.js?v=15"></script>
```

Both bumped (`14→15`, `12→13`). Paired bump per `tasks/lessons.md` iOS PWA safe pattern.

### 9. Python syntax: N/A (no Python in this brief).

## Gate-1 + Gate-2 invariants (per brief §reviewer instructions)

| # | Invariant | Status |
|---|-----------|--------|
| 1 | `fnMap` (14 entries) matches `TERMINALS` (14 entries) — same case, same aliases | ✓ |
| 2 | `WAKEABLE_ALIASES = new Set(TERMINALS)` — derived, not hand-typed | ✓ |
| 3 | Cache-bust paired bump in `static/index.html` | ✓ |
| 4 | Render deploy + live `curl` grep WAKEABLE_ALIASES | Pending merge + deploy |

## Director-facing manual smoke (post-merge, pending)

```bash
ls -la ~/Applications/ | grep -i "brisen lab wake"
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -dump | grep -A1 brisen-lab
open 'brisen-lab://wake/b1'
open 'brisen-lab://wake/CM-1'
open 'brisen-lab://wake/no-such-alias'
```

Browser smoke (post-deploy):
- Open https://brisen-lab.onrender.com/
- Bus-post yourself: `bus lead "wake test" wake-smoke` → lead card badge lights up
- Click the lead card → Terminal opens running `aihead1`
- Shift+click the lead card → detail modal opens
- Ack the bus msg; click lead again → detail modal opens (no badge → fallback)

## Gate chain (per mailbox)

- Gate-1 architecture: deputy (AH2)
- Gate-2 /security-review: deputy (AH2)
- Gate-3 picker-architect: SKIP (no install, no picker symlink change)
- Gate-4 code-reviewer 2nd-pass: deputy (AH2)
- Gate-5 merge: lead (AH1)

## Next step

Bus-post `ship/brisen-lab-click-to-wake-1` to lead (per mailbox reply-target rule).
