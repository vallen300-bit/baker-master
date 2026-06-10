---
name: bluewin-read-via-mail-app
description: Read Director's private dvallen@bluewin.ch inbox via macOS Mail.app AppleScript (local, no credentials)
when_to_use: Director asks to check / search / summarize his private Bluewin email. NOT auto-ingest — read on Director request only.
---

# Bluewin (private) email read — via Mail.app AppleScript

**UPDATE 2026-06-10 (Director ratified Option B — cloud pipeline):** Bluewin IS in
Baker's cloud pipeline. `triggers/bluewin_poller.py` polls imaps.bluewin.ch every email
cycle (BLUEWIN_USER/PASS set on Render); rows land in `email_messages` with
`source='bluewin'`. **Primary read surface for all agents:**
`baker_email_search(query=..., source="bluewin")` — verified live (full bodies returned).
Ingestion is forward-only from 2026-06-09 ~18:53Z (scheduler-stall fix #340 unblocked it);
the ~33.7k historical messages are NOT in the store.

**Surface 2 (history + fallback):** macOS Mail.app on the Mac Studio has the `Bluewin`
account configured (alongside iCloud, vallen300@gmail.com, Exchange). Any agent on this
Mac can read the FULL history via AppleScript below. Use for anything pre-2026-06-09.

**Privacy rule (updated per Option B ratification 2026-06-10):** auto-ingest into the
Baker store is Director-authorized. Quoting bluewin contents to counterparties or
external surfaces still requires Director instruction. Send is NOT in scope
(Outlook.app only has brisengroup).

## Read latest N headers

```bash
osascript <<'EOF'
tell application "Mail"
  set bx to mailbox "INBOX" of account "Bluewin"
  set msgs to messages 1 thru 5 of bx
  set out to ""
  repeat with m in msgs
    set out to out & (date received of m as string) & " | " & (sender of m) & " | " & (subject of m) & linefeed
  end repeat
  return out
end tell
EOF
```

## Read a message body

```applescript
tell application "Mail" to get content of message 1 of mailbox "INBOX" of account "Bluewin"
```

## Search by sender/subject (AppleScript `whose` is slow on big boxes — cap scope)

```applescript
tell application "Mail"
  set hits to (messages 1 thru 200 of mailbox "INBOX" of account "Bluewin") whose subject contains "Dropbox"
end tell
```

## Foot-guns

- Mail.app must be running (AppleScript auto-launches it; first call after reboot is slow).
- `whose` filters over a full large mailbox can hang — slice `1 thru N` first.
- Other accounts visible in Mail.app (iCloud, gmail, Exchange) — same pattern works, same privacy rule.
- Verified working 2026-06-10 (3 live headers read). If TCC/automation permission is reset,
  re-grant Terminal → Mail automation in System Settings → Privacy → Automation.
