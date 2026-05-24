# BRIEF: BRISEN_LAB_CLICK_TO_WAKE_1 — clickable cards open Terminal picker

## Context

Director just installed 5 new terminal pickers (CM-1..4 + hag-filer) today. Brisen Lab dashboard now shows 14 terminal cards. Today's friction: when a card lights up with an unread badge, Director must either remember the shell function name (`cm1`, `b3`, etc.) and type it into a free terminal tab, OR open Terminal → Shell → New Window → click profile. Either way, manual.

Director-ratified Path 1 (cowork-ah1 bus #916, 2026-05-24): **click on a badged card → opens that picker in Terminal.app.** Mechanism: custom `brisen-lab://` URL scheme + tiny local handler that maps alias → shell function and tells Terminal to run it.

### Surface contract

Per ui-surface-prebrief skill. 6 checks completed before brief authoring.

**1. User action (one sentence):** Director wants to launch the picker terminal for an agent whose Brisen Lab card currently shows an unread badge — by single-clicking the card itself.

**2. Backend that performs the action:** None in the HTTP sense — this is entirely a client-side `window.location.href` redirect to a custom URL scheme. macOS Launch Services routes `brisen-lab://` URLs to the local `Brisen Lab Wake.app` handler (shipped by this brief). No new route on baker-master, brisen-lab server, or any other repo.

**3. Endpoint contract verification:** The "handler" is the AppleScript `on open location this_URL` block shipped in this brief itself (Component 1). The contract: URL must match `brisen-lab://wake/<alias>` where `<alias>` is exactly one of the 14 entries in `TERMINALS` at `static/app.js:9`. AppleScript strips the `brisen-lab://wake/` prefix via `sed` and does a literal-string match against the `fnMap` AppleScript list. Unknown aliases hit a graceful `display dialog` path.

**4. State the UI displays + mutates:** Reads existing `state.busBadge[alias]` (populated by `bus_badge_change` SSE events, no schema change). Mutates nothing — clicking a badged card fires `window.location.href = 'brisen-lab://wake/' + alias`, the browser hands the URL to the OS, dashboard state is preserved. No new Postgres tables, no new SSE events, no new API routes.

**5. Director surface preference:** Already ratified Path 1 per cowork-ah1 bus #916 ("custom URL scheme + tiny local handler"). The cards on the existing brisen-lab dashboard ARE the surface; only the click handler behavior changes. No alternative surface (Slack/email/CLI) is in scope.

**6. Reviewer instruction:** See `## Gate-1 + Gate-2 reviewer instructions` block at the bottom of this brief.

## Estimated time: ~3-4h
## Complexity: Medium (3 components, each small)
## Prerequisites: 14 terminal pickers already installed (zshrc functions cm1/cm2/cm3/cm4/hagfiler shipped 2026-05-24)

---

## Component 1: macOS URL handler app

### Problem

There is no system component today that knows `brisen-lab://wake/<alias>` means "launch the `<alias>` picker in Terminal." macOS Launch Services needs an installed app registering that URL scheme.

### Current State

Nothing. `~/Applications/` has no Brisen Lab Wake app. `lsregister -dump | grep brisen-lab` returns nothing.

### Implementation

Create a tiny AppleScript-based .app bundle. Source lives in the brisen-lab repo at `tools/wake-handler/` so it's reproducible + version-controlled. A build script produces the .app in `~/Applications/`.

**File: `tools/wake-handler/wake-handler.applescript`** (new)

```applescript
-- Brisen Lab Wake handler
-- Registered for brisen-lab:// URL scheme via Info.plist.
-- Receives brisen-lab://wake/<alias>, maps alias -> shell function name,
-- launches the picker in Terminal.app.

on open location this_URL
    -- Strip "brisen-lab://wake/" prefix; everything after is the alias.
    set aliasName to do shell script "echo " & quoted form of this_URL & " | sed 's|^brisen-lab://wake/||'"

    -- alias -> shell function map. Mirrors the install-agent-to-brisen-lab-sop.md
    -- alias map. Update both when adding a new agent.
    set fnMap to {¬
        {"lead", "aihead1"}, ¬
        {"deputy", "aihead2"}, ¬
        {"cowork-ah1", "aihead1app"}, ¬
        {"b1", "b1"}, {"b2", "b2"}, {"b3", "b3"}, {"b4", "b4"}, ¬
        {"hag-desk", "hagenauerdesk"}, ¬
        {"researcher", "researcher"}, ¬
        {"CM-1", "cm1"}, {"CM-2", "cm2"}, {"CM-3", "cm3"}, {"CM-4", "cm4"}, ¬
        {"hag-filer", "hagfiler"}}

    set fnName to ""
    repeat with pair in fnMap
        if item 1 of pair is aliasName then
            set fnName to item 2 of pair
            exit repeat
        end if
    end repeat

    if fnName is "" then
        display dialog "Brisen Lab Wake: no terminal picker installed for alias '" & aliasName & "'." buttons {"OK"} default button 1 with icon caution
        return
    end if

    tell application "Terminal"
        activate
        do script fnName
    end tell
end open location

-- If launched without a URL (double-clicked), show a friendly message rather than crash.
on run
    display dialog "Brisen Lab Wake is a URL handler. It launches picker terminals when you click a card on the Brisen Lab dashboard. No action when run directly." buttons {"OK"} default button 1 with icon note
end run
```

**File: `tools/wake-handler/build.sh`** (new — idempotent build + install; `chmod +x`)

```bash
#!/usr/bin/env bash
# Build the Brisen Lab Wake .app bundle and install to ~/Applications/.
# Idempotent: safe to re-run after editing wake-handler.applescript.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Brisen Lab Wake.app"
INSTALL_DIR="$HOME/Applications"
APP_PATH="$INSTALL_DIR/$APP_NAME"

mkdir -p "$INSTALL_DIR"

# Remove any prior install so osacompile starts from a clean slate.
[ -d "$APP_PATH" ] && rm -rf "$APP_PATH"

# Compile AppleScript -> .app
osacompile -o "$APP_PATH" "$SRC_DIR/wake-handler.applescript"

# Patch Info.plist: register the brisen-lab:// URL scheme + hide from Dock.
PLIST="$APP_PATH/Contents/Info.plist"

/usr/libexec/PlistBuddy -c "Delete :CFBundleURLTypes" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes array" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0 dict" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLName string com.brisen.lab.wake" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes array" "$PLIST"
/usr/libexec/PlistBuddy -c "Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string brisen-lab" "$PLIST"

/usr/libexec/PlistBuddy -c "Delete :LSUIElement" "$PLIST" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$PLIST"

# Force Launch Services to re-register so the URL scheme is recognized.
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -f "$APP_PATH"

echo "Installed: $APP_PATH"
echo "Registered URL scheme: brisen-lab://"
echo
echo "Verify with:"
echo "  /System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -dump | grep -A1 brisen-lab"
echo
echo "Smoke test:"
echo "  open 'brisen-lab://wake/b1'"
```

**File: `tools/wake-handler/README.md`** (new — one paragraph)

```
# Brisen Lab Wake

URL-scheme handler that launches the Brisen Lab picker terminals when a card on the dashboard is clicked.

## Install / re-install
  bash tools/wake-handler/build.sh

Produces ~/Applications/Brisen Lab Wake.app + registers brisen-lab:// URL scheme via Launch Services. Rerun after editing wake-handler.applescript (e.g. when adding a new agent to the alias map).

## Alias map maintenance
The fnMap literal at the top of wake-handler.applescript MUST be kept in sync with the TERMINALS list at static/app.js:9 and the shell functions in ~/.zshrc. The install-agent-to-brisen-lab-sop.md Row 13 documents this as the formal maintenance step on every new agent install.
```

### Key Constraints

- AppleScript handler MUST fail gracefully (`display dialog`) when alias has no mapping. Matter-placeholder aliases (movie/ao/bb/brisen/origination) + future-but-not-yet-installed aliases will hit this path. Do NOT throw.
- `LSUIElement=true` is required — without it, the app shows up in Cmd+Tab and steals focus.
- `lsregister -f <path>` must run after build to pick up the URL scheme change. PlistBuddy edits alone don't trigger Launch Services refresh.
- Build script is idempotent — safe to re-run after editing the AppleScript source.

### Verification

1. `bash tools/wake-handler/build.sh` runs clean, prints "Registered URL scheme: brisen-lab://".
2. `lsregister -dump | grep -A1 brisen-lab` shows the registered scheme.
3. `open 'brisen-lab://wake/b1'` opens a new Terminal window running `b1` (the B1 picker).
4. `open 'brisen-lab://wake/nonexistent-alias'` shows the "no terminal picker installed" dialog, no crash.
5. App does NOT appear in Cmd+Tab or Dock when running.

---

## Component 2: Frontend click semantics

### Problem

Today every `.card[data-alias]` click opens the detail modal (app.js:889-895). We need: badged card → wake; unbadged card → existing modal (no change); shift+click on either → always modal (escape hatch for accessing detail when badge is up).

### Current State

`static/app.js:888-895` (verified by Read this brief-authoring session):

```javascript
// ---- Wiring ----
document.querySelectorAll(".card").forEach(c => {
  if (SYSTEM_CARDS.includes(c.dataset.alias)) return;  // system cards not drillable
  c.addEventListener("click", () => {
    state.detailAlias = c.dataset.alias;
    renderDetail();
  });
});
```

`SYSTEM_CARDS` is empty today (`const SYSTEM_CARDS = [];` at app.js:10), so every card with a `data-alias` gets the click handler. Cortex card has `data-alias="cortex"` but is not in TERMINALS (app.js:9) — it's its own rendering path. `state.busBadge` is populated by `bus_badge_change` SSE events; structure is `{alias: {unacked_count, oldest_unacked_age_sec, topics}}`.

### Implementation

**File: `static/app.js` — modify the click handler at line 889-895.**

Replace the existing handler with badge-gated semantics:

```javascript
// ---- Wiring ----
// Click semantics:
//   - Card with unread badge + plain click -> wake the picker (brisen-lab:// URL)
//   - Card without unread badge + plain click -> open detail modal (existing behavior)
//   - Shift+click on any card -> always open detail modal (escape hatch)
//   - Cortex card -> always detail modal (cortex not in TERMINALS, no picker)
//
// BRISEN_LAB_CLICK_TO_WAKE_1 (Director-ratified 2026-05-24, cowork-ah1 bus #916)
const WAKEABLE_ALIASES = new Set(TERMINALS);  // exactly the 14 installed pickers
document.querySelectorAll(".card").forEach(c => {
  if (SYSTEM_CARDS.includes(c.dataset.alias)) return;  // system cards not drillable
  c.addEventListener("click", (ev) => {
    const alias = c.dataset.alias;
    const hasBadge = !!(state.busBadge[alias] && state.busBadge[alias].unacked_count > 0);
    const wakeable = WAKEABLE_ALIASES.has(alias);
    if (hasBadge && wakeable && !ev.shiftKey) {
      // Fire the URL scheme. macOS Launch Services routes to Brisen Lab Wake.app.
      window.location.href = "brisen-lab://wake/" + encodeURIComponent(alias);
      return;
    }
    // Fallback: existing detail modal.
    state.detailAlias = alias;
    renderDetail();
  });
});
```

**Also update `static/index.html`** — bump the cache-bust query param on `app.js` AND `styles.css` so iOS PWA + browser caches pick up the change. Grep for `app.js?v=` and `styles.css?v=` and increment the integer (both, even though styles.css unchanged — paired bump is the safe pattern per `tasks/lessons.md`).

### Key Constraints

- **Do NOT remove the existing detail-modal path** — it's the only way to drill into card history. The new behavior is gated to badged + non-shift clicks.
- **Do NOT widen `WAKEABLE_ALIASES` beyond `TERMINALS`** — matter placeholders (movie/ao/bb/brisen/origination panels) live as `.matter-panel` divs, NOT `.card[data-alias]` elements, so they're naturally excluded. Cortex IS a `.card[data-alias="cortex"]` but is not in TERMINALS, so it'll fall through to the modal path — correct.
- **`encodeURIComponent(alias)`** — defends against future aliases with URL-unsafe characters. Today all 14 are ASCII-safe, but mistakes happen.
- **First-click browser prompt** — Chrome/Safari will prompt "Open in Brisen Lab Wake?" the first time. Director clicks "Always allow" and it's silent thereafter. This is browser-controlled, can't be suppressed from JS.

### Verification

1. Click an unbadged card → detail modal opens (existing behavior preserved).
2. Click a badged card → Terminal window opens running the picker for that alias (e.g. CM-2 badge present → click → CM-2 picker launches).
3. Shift+click a badged card → detail modal opens (escape hatch works).
4. Click the cortex card with a badge → detail modal opens (cortex not in TERMINALS, falls through correctly).
5. Click a matter-panel area (not a `.card` element) → nothing happens (matter panels are separate DOM tree).

---

## Component 3: SOP Row 13 update (separate baker-vault PR)

### Problem

Future agent installs (next matter desk, next worker) will need to extend the alias-map in `tools/wake-handler/wake-handler.applescript`. If not documented in the install SOP, the next install will ship cards on the dashboard whose click does nothing (graceful dialog, but still a gap).

### Current State

`~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md` has a 12-row wiring map at line 26 (§"The complete wiring map"). Rows 1-12 cover picker folder, zshrc function, Terminal.app profile, bus_post.sh whitelist, drain hook, 1P key, Render env, brisen-lab frontend, brisen-lab server, snapshot pusher, snapshot pusher redeploy, end-to-end smoke. Row 3 was amended this morning (2026-05-24) to cover Terminal.app profiles programmatically — but the wake-handler alias-map is not covered anywhere.

### Implementation

**File: `~/baker-vault/_ops/processes/install-agent-to-brisen-lab-sop.md`**

Add Row 13 to the wiring-map table immediately after Row 12 (end-to-end smoke). Also add an `AC13` entry in the Acceptance criteria section that mirrors Row 13.

Row 13 text (table cell):

```
| 13 | Wake-handler alias map | brisen-lab repo: `tools/wake-handler/wake-handler.applescript` `fnMap` literal | Add `{"<slug>", "<shell-fn-name>"}` pair to the `fnMap` AppleScript list. Rebuild + reinstall via `bash tools/wake-handler/build.sh`. Without this, clicking the new card on the dashboard shows the "no terminal picker installed" dialog instead of opening the picker. |
```

AC13 text:

```
- **AC13 — Wake-handler alias map** updated in `brisen-lab/tools/wake-handler/wake-handler.applescript` `fnMap` literal — add `{"<slug>", "<shell-fn-name>"}` pair. AH1 Tier-B post-merge: re-run `bash tools/wake-handler/build.sh` on every host where Director clicks the dashboard (currently just MacBook).
```

This SOP edit lives in a SEPARATE PR against baker-vault, NOT in the brisen-lab PR. The brisen-lab PR ships the feature; the baker-vault PR documents the maintenance step. AH1 (lead) commits + merges the baker-vault PR after the brisen-lab PR merges.

### Key Constraints

- Do NOT renumber existing rows 1-12 or their AC entries — would break any external references.
- Place Row 13 + AC13 strictly at the bottom of their respective sections.

### Verification

1. `git diff` on baker-vault shows only the Row 13 row + AC13 AC entry added; rows 1-12 untouched.
2. SOP renders cleanly (no broken markdown table).

---

## Files Modified

- `tools/wake-handler/wake-handler.applescript` (NEW — brisen-lab repo)
- `tools/wake-handler/build.sh` (NEW — brisen-lab repo, `chmod +x`)
- `tools/wake-handler/README.md` (NEW — brisen-lab repo)
- `static/app.js` (modify click handler at line ~889 — brisen-lab repo)
- `static/index.html` (bump app.js + styles.css cache-bust ints — brisen-lab repo)
- `_ops/processes/install-agent-to-brisen-lab-sop.md` (add Row 13 + AC13 — baker-vault repo, separate PR)

## Do NOT Touch

- `static/app.js:9` TERMINALS array (already populated; alias-map source)
- `static/app.js:11` TERMINAL_LABELS dict (unrelated to click semantics)
- `static/app.js:265` renderCard function (badge rendering unchanged)
- `static/app.js:102` renderUnreadBadge function (badge appearance unchanged)
- `static/app.js:889` SYSTEM_CARDS guard line (keep — system cards stay non-drillable)
- `bus.py`, `app.py` (server-side — no auth/DB/API change in this brief)
- `~/.zshrc` (shell functions already exist from 2026-05-24 install)
- `~/Library/Preferences/com.apple.Terminal.plist` (Terminal profiles already installed manually + verified by Director)

## Quality Checkpoints

1. `bash tools/wake-handler/build.sh` exits 0, prints "Registered URL scheme: brisen-lab://".
2. `lsregister -dump | grep -A1 brisen-lab` shows the scheme registered to `~/Applications/Brisen Lab Wake.app`.
3. `open 'brisen-lab://wake/b1'` opens a Terminal window running `b1` picker.
4. `open 'brisen-lab://wake/cm1'` (LOWERCASE alias — does NOT exist in TERMINALS; canonical alias is `CM-1`) → graceful dialog "no terminal picker installed for alias 'cm1'". Confirms case-sensitivity is enforced + graceful fail path works.
5. `open 'brisen-lab://wake/CM-1'` opens a Terminal window running `cm1` picker (the correct uppercase alias).
6. Frontend in a fresh browser session: click on a card with badge → wakes picker. Click on card without badge → opens detail modal. Shift+click on badged card → opens detail modal.
7. Cortex card click (even when cortex badge present) → always opens cortex detail modal (cortex not in TERMINALS, falls through).
8. Brisen Lab Wake.app does NOT appear in Cmd+Tab.
9. Cache-bust ints in `static/index.html` bumped (both app.js + styles.css).
10. SOP Row 13 + AC13 land in baker-vault separate PR; rows 1-12 unchanged.

## Verification post-deploy (Director-facing manual smoke)

```bash
ls -la ~/Applications/ | grep -i "brisen lab wake"
/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister -dump | grep -A1 brisen-lab
open 'brisen-lab://wake/b1'
open 'brisen-lab://wake/CM-1'
open 'brisen-lab://wake/no-such-alias'
```

Browser smoke:
- Open https://brisen-lab.onrender.com/
- Bus-post yourself: `bus lead "wake test" wake-smoke` → lead card badge lights up
- Click the lead card → Terminal opens running `aihead1`
- Shift+click the lead card → detail modal opens
- Ack the bus msg; click lead again → detail modal opens (no badge → fallback)

## Ship gate

Literal output required (no "pass by inspection"):

- `bash tools/wake-handler/build.sh` — full stdout pasted into ship report
- `lsregister -dump | grep -A1 brisen-lab` — pasted output showing registration
- `open 'brisen-lab://wake/b1'` — describe the Terminal window that opened (visual confirmation required; cannot ship on AppleScript-looks-right alone)
- Frontend: `grep -n "WAKEABLE_ALIASES" static/app.js` shows the new line + click handler diff
- Cache-bust ints bumped in static/index.html (diff confirms)
- Python syntax: N/A (no Python in this brief)

Single brisen-lab PR for Components 1+2; separate baker-vault PR for Component 3 (SOP). Order: brisen-lab first (feature), baker-vault second (docs).

## Gate-1 + Gate-2 reviewer instructions

Per ui-surface-prebrief skill Check 6, reviewer MUST verify these four invariants beyond the standard architecture + security review:

1. **alias-map parity:** The `fnMap` literal in `tools/wake-handler/wake-handler.applescript` MUST contain exactly the 14 entries that match `TERMINALS` at `static/app.js:9` — same aliases, same case (uppercase `CM-1` etc., lowercase `hag-filer`). Reviewer pastes both lists side-by-side in the review verdict. Any drift = REQUEST_CHANGES.

2. **WAKEABLE_ALIASES = TERMINALS:** The `const WAKEABLE_ALIASES = new Set(TERMINALS)` line in `static/app.js` MUST derive the set from the existing `TERMINALS` constant — NOT a hand-typed duplicate. Reviewer greps for `WAKEABLE_ALIASES` and confirms the source is `TERMINALS`. Any hand-typed duplicate = REQUEST_CHANGES.

3. **Cache-bust paired bump:** Both `app.js?v=N` AND `styles.css?v=N` in `static/index.html` MUST be incremented (even though styles.css unchanged). Paired bump is the iOS PWA safe pattern per `tasks/lessons.md`. Reviewer greps both refs in the index.html diff.

4. **Render deploy gate:** brisen-lab Render deploy MUST complete before ship report says "done." `curl -s https://brisen-lab.onrender.com/static/app.js?v=N | grep WAKEABLE_ALIASES` must return the new line. Live-deploy confirmation, not commit-only.

If any of these four fail, REQUEST_CHANGES.

## Lessons applied (from tasks/lessons.md)

- **Phantom helper function:** `WAKEABLE_ALIASES` is defined in the same file before use; no import needed.
- **Cache bust required:** bump both `app.js?v=N` and `styles.css?v=N` (paired pattern).
- **Push before declaring done:** both PRs must merge + brisen-lab Render deploy must serve the new app.js before the ship report says "done."
- **Test before declaring done:** at least Component 1 smoke (`open 'brisen-lab://wake/b1'`) must produce a real Terminal window. Cannot ship on inspection alone.
