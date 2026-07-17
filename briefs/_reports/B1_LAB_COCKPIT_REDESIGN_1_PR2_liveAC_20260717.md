# B1 ship report — LAB_COCKPIT_REDESIGN_1 (PR 2) live post-deploy AC

- date: 2026-07-17
- brief: `briefs/_tasks/LAB_COCKPIT_REDESIGN_1.md` @716995c6 · dispatch: lead #12318
- commit under test: `92b735fe` (merge PR #589) — on `main`
- surface: local Director cockpit `http://127.0.0.1:7800/` (loopback, Basic-auth)
- deployed static + `cockpit_controller.py` byte-match repo `scripts/cockpit_static/*` + `scripts/cockpit_controller.py` (verified diff-clean)

## Test suite (merged main)
- `pytest` cockpit suite: **52 passed** (layout, controller, wake, card_geometry, contrast, manifest_strict, panel_go, serve).
- `node --check` cockpit.js + glance_state.js: clean.
- `amberState` predicate (node): amber iff unacked>0 AND not WORKING AND not needs_go — 5/5 cases pass.

## Live AC results (:7800)

| AC | Result | Evidence |
|----|--------|----------|
| AC-1 layout | PASS | served `cockpit_layout.json` = 6 plates / 43 cards, Director short labels; `generate_cockpit_layout.py --strict` exit 0 ("cards 43, unassigned 0") |
| AC-2 visuals | PASS | Director eyeball GOOD (live ratified #12318); no AG-pill class in served js/css |
| AC-3 context band | PASS | ctx-band element+css served; API `context_pct: null` → bar hidden (null-safe); no card-height cost |
| AC-4 amber/panel | PASS | `/api/agents` per-seat `unacked_messages` list live (id/topic/age); planted msg surfaced as count=1 + message row; controller proxies the Lab per-seat unacked query (count IS the Lab number by construction) |
| AC-5 wake-on-open | PASS | real-seat drill on `b1`: planted unacked #12322 → `POST /api/sessions/b1/wake` → `sent:true line="check bus #12322 drill/wake-ac"`; audit line written to `wake_audit.log`; sibling seat woke, ran check bus, read+acked the msg. Guards live: 2nd fire skipped `working` (seat busy processing nudge — proves never-fire-on-WORKING); `lead` (down) skipped `session down`. needs_go guard + pure 600s dedupe are unit-covered (52 tests) — pure-dedupe not independently live-exercised because the WORKING guard pre-empted the 2nd fire. |
| AC-6 invariants | PASS | `--strict` clean; zero innerHTML assignments (only a doc-comment mentions it); `goAffordanceVisible` gating present; `/wake` call in openTerm path |
| AC-7 E1-E5 | PASS | Director eyeball GOOD (live ratified); geometry+contrast pytest sweeps green |

## Notes / fail-loud
- Visual ACs (AC-2, AC-7) rest on Director's live eyeball ratification (#12318) — no fresh screenshots re-captured this session; the live page is the ratified artifact.
- Pure 600s per-seat dedupe skip was not independently reproduced live (WORKING guard took precedence on the 2nd fire); it remains unit-test-covered.
- Drill message #12322 was auto-acked by the woken sibling seat — no residue left on the bus.
