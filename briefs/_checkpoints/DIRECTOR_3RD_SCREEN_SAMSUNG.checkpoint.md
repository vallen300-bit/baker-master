# Checkpoint — Director live help: 3rd screen (Samsung) won't launch

**Type:** Director-facing computer-use troubleshooting (NOT a code brief). Ephemeral.
**Date:** 2026-06-23
**Status:** Diagnosed; awaiting Director choice + Director must dismiss a stuck popup.

## What the Director asked
"Fix connection with the 3rd screen (Samsung). I connected BenQ + Studio Display, can't launch the 3rd. Can my Mac do 3 screens?"

## Confirmed facts (from System Settings > Displays + Apple Account)
1. Computer = **MacBook Pro 14"** (Apple Silicon). NOT a Mac Studio.
2. "Mac Studio screen" = Apple **Studio Display** monitor — cabled, working.
3. **BenQ PD2700U** — cabled, working.
4. **Samsung Q60CA 75"** — connected via **AirPlay (wireless)**, shows in Displays with a "Disconnect" button + wallpaper thumbnail; macOS thinks it's an active Extended display, capped 1920×1080. TV itself likely black / on wrong input.
5. So the Mac IS already driving 3 displays in software; the wireless AirPlay link is the flaky part.

## Diagnosis
Samsung is wireless (AirPlay), not cabled like the other two. AirPlay to Samsung TVs drops silently while macOS still reports "connected." Needs TV awake + same Wi-Fi.

## Options put to Director (awaiting A or B)
- **A) HDMI cable** — stable, full-res. Best, IF chip allows a 3rd cabled display. (Chip NOT yet confirmed — base/Pro Apple Silicon caps at 2 external; Max supports up to 4. He already has 2 cabled, so a 3rd cable only works on a Max chip. CONFIRM CHIP FIRST via System Settings > General > About, or `system_profiler SPHardwareDataType | grep Chip`.)
- **B) Re-do AirPlay** — disconnect + reconnect the Samsung now (Control Center > Screen Mirroring), enter TV code if asked. Wireless, lower quality.

Recommendation given: **A** (cable) — wireless to a 75" TV is laggy/soft.

## BLOCKER for next session
An **AppleCare Plans purchase popup** (AppleCare+ for AirPods Pro, CHF 39) is stuck open over System Settings — opened accidentally when I clicked the device row. My synthetic clicks (Cancel/Decline/Escape) do NOT dismiss it (it's a commerce helper sheet). **Director must click "Decline Offer" with his own mouse.** Do NOT press Continue.

## Next session resume
1. Confirm Director dismissed the popup.
2. Get the chip: `system_profiler SPHardwareDataType | grep -i chip`.
3. If Max chip → guide HDMI cable for Samsung (drop AirPlay). If base/Pro → AirPlay is the only 3rd-screen path; reconnect it.
4. Lesson: stay in the Displays pane; clicking the device/Devices row triggers AppleCare/warranty sheets.
