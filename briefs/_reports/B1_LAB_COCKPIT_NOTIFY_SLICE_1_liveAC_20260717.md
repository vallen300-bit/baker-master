# B1 ship report — LAB_COCKPIT_NOTIFY_SLICE_1 post-deploy AC

- date: 2026-07-17
- brief: `briefs/_tasks/LAB_COCKPIT_NOTIFY_SLICE_1.md` · dispatch: lead #12318 item 2
- PR #590 merged @5735ddab + deployed (lead ran installer; :7800 up)
- codex delta gate: FAIL #12354 → fixed 0b7127da → re-verdict PASS-WITH-NOTE #12357
- deployed `cockpit_controller.py` + `cockpit_layout.json` byte-match merged main (verified diff-clean)

## Test suite (merged main)
- `pytest` 9 cockpit files: **72 passed** (67 prior + 5 new), 0 failed, 0 skipped.
- `node --check` cockpit.js + glance_state.js: clean.

## Live AC results (:7800, deployed @5735ddab)

| AC | Result | Evidence |
|----|--------|----------|
| AC-1 banner on eligible 0→N, one fire, seat named | PASS (objective) | Merged code + **real Lab glance** + **real codex-arch dispatch** (#12370, codex-arch unacked 0→1): `notify_macos` fired exactly once = `('codex-arch', 1)`; seed tick did not fire. Deployed controller (identical code/config, codex-arch seeded 0 at startup) consumed the same real transition and fired the actual osascript banner. |
| AC-2 N→N+1 no re-fire; ack→0 then re-fires | PASS | committed transition-matrix tests (codex-verified): first-seen seed, 0→N fire, N→N+1 no fire, ack→0 then 0→N re-fire, cooldown suppress. |
| AC-3 self-awake / Wake.app seats excluded | PASS | live `/api/notify/state` eligible = codex-arch + 9 `wakeable:false` cowork desks exactly; excludes all terminals (b1) + Wake.app-covered app-claude (cowork-ah1, ben, cowork-bb-desk). committed-layout classifier test locks it. |
| AC-4 mute suppresses / persists / page-closed still fires | PASS | live deployed: POST mute=true → state muted + `notify_mute.json` `{"muted": true}` (the file the loop reads) → restored; no-auth POST → 401. Suppression on a real 0→N = committed `test_notify_tick_muted` (codex-verified, identical code path). Page-closed = inherent: AC-1 fired with no browser open. |
| AC-5 existing suite green + live unchanged | PASS | 72 cockpit pytest pass; `/api/agents` + page render unaffected. |

## Fail-loud notes
- **Banner not shell-observable.** osascript `display notification` is silent on success and macOS does not expose the notification text to `log stream` (verified: controlled probe captured nothing). The notify feature writes **no success audit trace** (unlike wake's `wake_audit.log`). So the actual banner render/sound is confirmed only by the **Director's ratified "hear the sound" step**, not by me. My AC-1 proof establishes the fire path objectively up to `notify_macos`.
- **Recommended follow-up (for lead to weigh):** add a `notify_audit.log` success line parallel to `wake_audit.log`, so future banner fires are verifiable/debuggable after the fact. Out of this brief's scope (brief did not require an audit log).
- **Live mute suppression** against a fresh real 0→N was not independently re-run to avoid planting a collateral drill dispatch into a live matter desk; it is covered by the committed test on the identical `read_mute()` gate + the live mute-file persistence proof above.
- Drill dispatch #12370 to codex-arch is labelled "no action; ack and idle" — codex-arch will ack it.

## Done-state
All AC engineering-verified live/tested. Remaining ratified gate: **Director audible eyeball** (hear the sound on a real codex-arch dispatch) per the brief gate plan — that is the final close, held by lead/Director, not b1.
