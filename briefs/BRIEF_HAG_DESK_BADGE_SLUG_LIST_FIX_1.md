# BRIEF: HAG_DESK_BADGE_SLUG_LIST_FIX_1 — add hag-desk to KNOWN_CARD_SLUGS

### Surface contract: N/A — backend-only Python tuple update. Front-end already alias-agnostic (verified `static/app.js:80 inboxBadgeProps()` operates on any slug; PR #25 wired the card slot for hag-desk). No clickable surface, no new route, no template change.

## Context

Smoke test 2026-05-22 ~08:13Z revealed `hag-desk` card badge events never reach the browser. Live SSE tap from `lead` confirms:
- `bus_msg` SSE event fires correctly when bus_post targets hag-desk (verified for msg #659, #660, #661).
- `bus_badge_change` SSE event is **NOT** emitted for hag-desk recipients.

Root cause: `bus.py:1056` filters affected recipients through `KNOWN_CARD_SLUGS`:
```python
recipients = [r for r in affected_recipients if r in KNOWN_CARD_SLUGS]
```

`KNOWN_CARD_SLUGS` (bus.py:895-897) is hardcoded:
```python
KNOWN_CARD_SLUGS: tuple[str, ...] = (
    "lead", "deputy", "b1", "b2", "b3", "b4", "cortex", "cowork-ah1",
)
```

`hag-desk` is absent → badge events filtered out → card never updates the "X unread" badge in real-time.

HAGENAUER_DESK_ON_BUS_1 (PR #25 brisen-lab, merged 2026-05-21) wired the bus recipient whitelist, server-side `/msg/hag-desk` route, front-end card slot, and `app.js` TERMINALS array. **It missed this one tuple.**

## Estimated time: ~20 min
## Complexity: Low
## Prerequisites: none — hag-desk recipient whitelist already merged in HAGENAUER_DESK_ON_BUS_1

---

## Fix 1: Add hag-desk to KNOWN_CARD_SLUGS

### Problem
`bus.py:895-897` tuple is hardcoded; missing `hag-desk`. Used at three sites: `bus.py:953`, `bus.py:989`, `bus.py:1056` — all gate hag-desk out of card-related queries + badge broadcasts.

### Implementation
In `~/bm-b1-brisen-lab/bus.py` (brisen-lab repo), modify lines 895-897:

```python
KNOWN_CARD_SLUGS: tuple[str, ...] = (
    "lead", "deputy", "b1", "b2", "b3", "b4", "cortex", "cowork-ah1", "hag-desk",
)
```

One-element tuple addition. No other changes.

### Key Constraints
- Do NOT modify any other line. `bus.py:953`, `:989`, `:1056` consume the constant; they automatically pick up the new entry.
- Do NOT touch `_build_terminals_response()` (`bus.py:900`) — it iterates the same tuple.
- Do NOT touch `/api/v2/terminals` shape — the response auto-includes hag-desk once it's in the tuple.

### Verification
After deploy + 1 bus_post to hag-desk:
```bash
KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')"
(curl -s -N --max-time 8 "https://brisen-lab.onrender.com/sse/stream?terminal=lead" -H "X-Terminal-Key: $KEY") &
SSE_PID=$!
sleep 2
BAKER_ROLE=lead ~/bm-b1/scripts/bus_post.sh hag-desk "post-fix smoke" smoke/post-fix
wait $SSE_PID 2>/dev/null
```
Expected output must include BOTH:
- `{"kind": "bus_msg", ... "to": ["hag-desk"] ...}` (already works pre-fix)
- `{"kind": "bus_badge_change", "badges": {"hag-desk": {"unacked_count": N, ...}}}` (this is the fix)

---

## Fix 2: Add test coverage for hag-desk badge event

### Problem
`tests/test_a3_a8_a9_bus.py` covers `bus_badge_change` emission for the original 8 slugs but has no fixture for hag-desk. Adding a regression test prevents future desk-on-bus additions from quietly hitting the same trap.

### Implementation
In `~/bm-b1-brisen-lab/tests/test_a3_a8_a9_bus.py`, copy the existing `bus_badge_change` emission test (lines ~200-225, around the existing positive case) and swap recipient to `hag-desk`. Verify both:
- `bus_badge_change` envelope is emitted.
- `badges["hag-desk"]` is present with `unacked_count >= 1`.

Use the exact helper functions the existing tests use (do not invent new ones — read the file's pattern + match).

### Verification
```bash
cd ~/bm-b1-brisen-lab
pytest tests/test_a3_a8_a9_bus.py -v
```
Expected: all existing tests PASS plus the new `test_bus_badge_change_emitted_for_hag_desk` PASS.

---

## Files Modified
- `bus.py` — +1 element in `KNOWN_CARD_SLUGS` tuple at line 895-897
- `tests/test_a3_a8_a9_bus.py` — +1 test function (~12 LOC)

## Do NOT Touch
- `static/index.html`, `static/app.js`, `static/styles.css` — front-end already alias-agnostic
- `~/bm-aihead1/scripts/forge_snapshot_push.sh` — different code path (snapshot pusher, fixed in PR #238)
- `bus.py:953`, `:989`, `:1056` — they reference the constant; no edit needed
- `_build_terminals_response()` — auto-picks up the new entry

## Ship gate
Literal `pytest tests/test_a3_a8_a9_bus.py -v` output (all green, including the new test) pasted in PR description. No "pass by inspection."

## Reporting
- Bus-post `lead` on PR open: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "PR #<num> opened: HAG_DESK_BADGE_SLUG_LIST_FIX_1" ship/hag-desk-badge-slug-fix`
- Bus-post `lead` on any blocker: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "<blocker>" blocker/hag-desk-badge-slug-fix`
- Mailbox UPDATE pattern: CLAIM → IN_PROGRESS → COMPLETE with ISO timestamps.

## Risks
- **LOW:** One-element tuple addition. Consumers iterate the tuple; no special-casing needed.
- Test fixture: if `tests/test_a3_a8_a9_bus.py` uses fixtures keyed to specific terminal slugs (check conftest), they may need a `hag-desk` entry — surface as blocker if so.

## Post-merge deploy
brisen-lab auto-deploys on push to main (Render). AH1 verifies post-deploy via smoke:
```bash
KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')"
(curl -s -N --max-time 8 "https://brisen-lab.onrender.com/sse/stream?terminal=lead" -H "X-Terminal-Key: $KEY") &
sleep 2; BAKER_ROLE=lead ~/bm-b1/scripts/bus_post.sh hag-desk "post-deploy smoke" smoke/post-deploy; sleep 4
```
Must observe `bus_badge_change` event with `hag-desk` in `badges` dict.
