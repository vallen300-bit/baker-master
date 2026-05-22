# BRIEF: HAG_DESK_CARDS_LOOP_INCLUDE_1 — add hag-desk to /api/v2/terminals iteration

### Surface contract: N/A — backend-only Python tuple update. Front-end already alias-agnostic (card slot in static/index.html, hag-desk in app.js TERMINALS list, modal render code generic). No clickable surface, no new route, no template change.

## Context

Visual smoke test 2026-05-22 ~10:18Z post-PR-#27-merge: badge SSE event NOW fires for hag-desk (verified via SSE tap — `bus_badge_change` envelope arrived with `badges["hag-desk"]`). But Director's modal still shows **"(no bus messages)"**.

Root cause: `bus.py:1005` builds the `/api/v2/terminals` response by iterating a SECOND hardcoded slug tuple:

```python
for slug in ("lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4"):
```

`hag-desk` is absent → no card entry → modal's "Bus inbox" view (which fetches from `/api/v2/terminals`) sees no hag-desk entry → renders empty.

Verified via direct `curl /api/v2/terminals` 2026-05-22 10:20Z: response contains 8 slugs (`lead, cowork-ah1, deputy, b1, b2, b3, b4, cortex` — cortex is appended as a special case at line 1030); hag-desk is missing.

This is the THIRD hardcoded slug-list that HAGENAUER_DESK_ON_BUS_1 (PR #25, merged 2026-05-21) missed. Sequence so far:
- ✅ Snapshot pusher TERMINALS array → fixed in PR #238 (baker-master)
- ✅ `bus.py:895` `KNOWN_CARD_SLUGS` tuple → fixed in PR #27 (brisen-lab, merged 10:17Z)
- ❌ `bus.py:1005` for-loop iteration → this brief

Audited remaining files for hidden slug lists (`grep '"lead"\|"b1"\|"cortex"' brisen-lab/*.py`): no other unfixed places gate hag-desk from the card payload. `app.py:40 TERMINALS` already includes hag-desk. `db.py:226-235 terminal_tiers` lacks hag-desk but is auth-tier metadata (not card-rendering); `lifecycle.py:491-493` is token-pressure config (out of scope). Neither blocks the modal display.

## Estimated time: ~20 min
## Complexity: Low
## Prerequisites: PR #27 merged (KNOWN_CARD_SLUGS now contains hag-desk so the unacked-count subquery at line 953 already includes hag-desk data — this brief just adds the iteration that consumes it)

---

## Fix 1: Add hag-desk to the cards iteration

### Problem
`bus.py:1005` for-loop tuple is hardcoded without hag-desk.

### Implementation
In `~/bm-b1-brisen-lab/bus.py:1005`, change:
```python
for slug in ("lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4"):
```
to:
```python
for slug in ("lead", "cowork-ah1", "deputy", "b1", "b2", "b3", "b4", "hag-desk"):
```

One-element addition. Cortex stays as its existing special-case append at line 1030 (don't fold cortex into the loop — it has a different card-render path that omits git/mailbox state).

### Key Constraints
- Do NOT modify the cortex special-case append at lines 1030-1043.
- Do NOT modify the `recipient = ANY(%s)` query at line 949-953 — it already uses `KNOWN_CARD_SLUGS` which contains hag-desk post PR #27.
- Do NOT modify the SQL at lines 904-989 — they already select on all `to_terminals` and filter to KNOWN_CARD_SLUGS.

### Verification
After deploy:
```bash
KEY="$(op read 'op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_lead/credential')"
curl -s "https://brisen-lab.onrender.com/api/v2/terminals" -H "X-Terminal-Key: $KEY" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); slugs=[t['slug'] for t in d['terminals']]; print(slugs)"
```
Expected output: `['lead', 'cowork-ah1', 'deputy', 'b1', 'b2', 'b3', 'b4', 'hag-desk', 'cortex']` (hag-desk now present; order matches loop order with cortex appended last).

Also verify hag-desk card contains recent_messages:
```bash
curl -s "https://brisen-lab.onrender.com/api/v2/terminals" -H "X-Terminal-Key: $KEY" \
  | python3 -c "import json,sys; d=json.load(sys.stdin); h=[t for t in d['terminals'] if t['slug']=='hag-desk'][0]; print('unacked:',h['unacked_count'],'recent:',len(h['recent_messages']))"
```
Expected: `unacked: 6  recent: <=20` (matching current hag-desk inbox state).

---

## Fix 2: Add test coverage

### Problem
`tests/test_a3_a8_a9_bus.py` has tests that fetch `/api/v2/terminals` and assert per-slug card content (helper at line 133-134) but no test asserts hag-desk presence.

### Implementation
In `~/bm-b1-brisen-lab/tests/test_a3_a8_a9_bus.py`, add a new test:

```python
def test_v2_terminals_response_includes_hag_desk(client):
    """HAG_DESK_CARDS_LOOP_INCLUDE_1 regression: hag-desk was missing from
    the hardcoded for-loop in _build_terminals_response, so /api/v2/terminals
    omitted it from the card payload even after KNOWN_CARD_SLUGS was fixed."""
    from bus import _CACHE
    _CACHE.pop("v2_terminals", None)
    r = client.get("/api/v2/terminals")
    assert r.status_code == 200, r.text
    slugs = [t["slug"] for t in r.json()["terminals"]]
    assert "hag-desk" in slugs, f"hag-desk missing from /api/v2/terminals slugs: {slugs!r}"
```

Use the existing `_CACHE.pop` pattern that other tests use to bypass the 15s TTL.

### Verification
```bash
cd ~/bm-b1-brisen-lab
pytest tests/test_a3_a8_a9_bus.py::test_v2_terminals_response_includes_hag_desk -v
pytest tests/test_a3_a8_a9_bus.py -v
```
Expected: new test PASS + all existing tests PASS.

---

## Files Modified
- `bus.py` — +1 element in for-loop tuple at line 1005
- `tests/test_a3_a8_a9_bus.py` — +1 test function (~10 LOC)

## Do NOT Touch
- Cortex special-case append at `bus.py:1030-1043`
- SQL queries at `bus.py:904-989`
- `_emit_badge_refresh()` at `bus.py:1047+` (already correct post PR #27)
- Front-end files
- `db.py:226-235 terminal_tiers` — separate concern; surface if it causes auth issues but not part of this fix
- `lifecycle.py:491-493 token-pressure config` — separate concern; out of scope

## Ship gate
Literal `pytest tests/test_a3_a8_a9_bus.py -v` output (all green including new test) in PR description.

## Reporting
- Bus-post `lead` on PR open: `BAKER_ROLE=b1 ~/bm-b1/scripts/bus_post.sh lead "PR #<num> opened: HAG_DESK_CARDS_LOOP_INCLUDE_1" ship/hag-desk-cards-loop-include`
- Mailbox UPDATE: CLAIM → IN_PROGRESS → COMPLETE with ISO timestamps.

## Risks
- **LOW:** Same shape as PR #27 (one-element tuple addition + mirror-test). No architectural change.
- If the iteration ordering matters in the test fixtures, hag-desk lands between b4 and cortex; verify by reading any test that asserts specific positions (likely none — most tests use `slug == "X"` lookups).

## Post-merge deploy
brisen-lab auto-deploys on push to main. AH1 verifies via `curl /api/v2/terminals` + visual confirmation on Director's browser.
