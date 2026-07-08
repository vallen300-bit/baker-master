# CHECKPOINT — ARRIVALS_BOARD_LIVE_1 (+ follow-ups)

Seat: cowork-ah1 · Session rollover 2026-07-08 ~evening (~86% context).
Successor claim = the attempt-bump commit of THIS file, not a bus ack.

## STATE: DONE + LIVE (arc essentially closed; two watch items on lead's side)

Director sketched an all-flights ARRIVALS board on paper (14:00) → built, ratified, wired
to live state, click-through + real cockpits + back button + dock icon, all shipped today.

### Shipped to baker-master main (all deployed + live-verified)
- `ec941513` — BRIEF_ARRIVALS_BOARD_LIVE_1.md (the brief).
- deputy-codex build merged `2e085edf` — migration `flight_board_state`, `POST /api/flight-board/{code}` (verify_api_key, audited to baker_actions), `GET /arrivals` + `/api/arrivals.json`, PIN-cookie access gate (`ARRIVALS_BOARD_PIN=6470`). Codex G3 PASS #7303/#7320.
- `20835c78` — /flights routes accept the arrivals PIN cookie (click-through auth fix). Verdict #7375/#7376.
- lead `COCKPIT_SERVE_STOPGAP_1` (`orchestrator/cockpit_serve.py`, route `GET /cockpit/{code}`) — serves REAL vault Pattern-E cockpits from GitHub main via `BAKER_VAULT_READ_TOKEN`; board rows now point to `/cockpit/{code}`. Bridge live #7394.
- `5e9b32c1` — floating "← ARRIVALS" back-button injected in `cockpit_serve._inject_back_button` (all cockpits, vault files untouched). Verdict #7408/#7409.

### UI (ratified, frozen in vault @847c91f)
- Canonical board: `_ops/build/baker-os-v2/05_outputs/flight-dashboards/arrivals-board-v6.html`. Iterations v1→v6 beside it. Register: split-flap Solari, amber-on-black, 7 cols (ARRIVES/FLIGHT NO/AIRLINE/DESTINATION/DESK/STATUS/UPDATED), VIEW light-toggle, REFRESH, live clock, one-line rows, quiet flap cells (halfway v3↔v4).
- Ratified status vocabulary (exact strings): CHECK-IN · ON TIME · HOLDING · DELAYED · FINAL APPROACH · LANDED · DIVERTED. Machine forces DELAYED when arrives_on passes (except LANDED/DIVERTED). ARRIVES = next milestone/decision/landing.

### Board state seeded (both flights, updated_by cowork-ah1)
- BB-AUK-001: FINAL APPROACH · arrives 2026-07-10 · Page v13. Cockpit live at v16 (desk kept folding).
- AO-OSK-001: ON TIME · arrives 2026-07-10 · Page v4.

### Director dock icon (LOCAL, this Mac only — NOT in repo)
- Created `~/Applications/Chrome Apps.localized/Brisen Air — Arrivals.app` (cloned from Baker CEO Cockpit Chrome-app), custom AMBER AIRCRAFT icon (dark rounded, board palette), URL `/arrivals`, CFBundleIdentifier `com.google.Chrome.app.brisenairarrivalsboard`, ad-hoc signed. Pinned in Dock next to Baker (plistlib append, count 11→12). Dock plist backup: scratchpad `com.apple.dock.plist.bak`. Icon source PNG/icns in scratchpad. If icon stale in dock → bust IconServices cache + killall Dock.

## DOCTRINE FOLDED TODAY (lead's canon lane)
- Two-surface seat rule → THREE surfaces (D-42, vault `decision_action_log.md` @bdcde76): every PILOT ingest stamps dashboard (Page vN) + ClickUp task body (as-of) + `POST /api/flight-board/{code}`. Non-pilots exempt. Anchor: #7134 Maiworm chat-only lapse this AM.
- Director six-step airport metaphor: `_ops/skills/airport-process-orchestration/references/director-six-steps.md` (@847c91f), pointer in that SKILL.md. Lead to cross-point in agent-onboarding-runbook (#7229).
- "No seat number, no flight" — chat/bus = UNDELIVERED until on Director's surfaces.

## OPEN / WATCH (successor)
1. Lead live re-verify of back-button (#7406) + he flips `cockpit_url` if he chooses DB-side (currently rows default to `/cockpit/{code}` via render fallback — works).
2. Publisher real-cockpit PARITY track (Route A) — needs BB-desk v2 packet lane, NOT 2 days; lead owns. Route B `/cockpit` is the stopgap until then.
3. ao-desk confirmed (#7402) git-push at seat end folded to its checklist — verify it actually pushes next AO ingest.
4. Desks' FIRST self-made board POST (third stamp) — watch bb-desk + ao-desk do it unprompted on next real ingest.
5. My standing pre-existing opens (from prior handover): Cortex day-7 scorecard ≈13 Jul; Publisher shadow-week scorecard; P3 advisor paperwork; late questionnaire scoring; Page v9 browser-verify debt.

## BUS
Acked through #7402. Verdicts posted #7408/#7409 (cc deputy). Standing: GO/ratify asks route to LEAD (#6730). Bus key cached at scratchpad `.buskey` (session-local).

## KEY PATHS
- Live: https://baker-master.onrender.com/arrivals (PIN 6470) → rows → /cockpit/{code} → "← ARRIVALS".
- Brief: `briefs/BRIEF_ARRIVALS_BOARD_LIVE_1.md`.
- Server: `orchestrator/arrivals_board.py`, `orchestrator/cockpit_serve.py`, routes in `outputs/dashboard.py` (~8473).
