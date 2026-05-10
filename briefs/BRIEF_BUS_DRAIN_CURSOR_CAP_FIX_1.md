# BRIEF: BUS_DRAIN_CURSOR_CAP_FIX_1 — fix cursor advance on rendered slice (not full fetch) + cleanup nit

**Status:** V0.1 — ready to dispatch
**Author:** AH1 (terminal session, 2026-05-11)
**Reviewer:** AH2 cross-lane (no `/security-review` mandate — correctness-only fix in already-reviewed file)
**Target build lane:** B2 (just shipped the parent PR #183; smallest possible context-switch)
**Tier:** B (small; ~30 min)
**Branch convention:** `b2/bus-drain-cursor-cap-fix-1`
**Trigger:** AH2 cross-lane + /security-review on PR #183 (2026-05-11) flagged a confirmed data-loss bug at `tests/fixtures/session-start-bus-drain.sh:377`. Director ruled "ship now, fix later" on the parent PR — this brief is the "fix later."

---

## Problem

`session-start-bus-drain.sh:377` advances the `last_seen_at` cursor using `max(m["created_at"] for m in msgs)` over the **full fetched** message set (up to 50), while the rendering loop only emits the **first 30** (`shown = msgs[:RENDER_CAP]`). When the daemon returns 31-50 unread messages:

- Receiver sees: 30 rendered messages + a status-line note that 20 older messages were elided.
- State file is written with the newest `created_at` of all 50.
- Next session's drain runs `since=<that ts>` → daemon returns 0 messages → those 20 messages are silently lost from inbox view forever.

**Daemon ordering confirmed:** `bus.py:349` uses `ORDER BY created_at ASC`. `shown = msgs[:30]` are the 30 OLDEST unread; `max(shown).created_at = msgs[29].created_at`. Next drain `since=msgs[29].created_at` returns `msgs[30:]` correctly.

## Fix (one-line)

`session-start-bus-drain.sh:377` — change `for m in msgs` to `for m in shown`:

```python
# OLD (buggy):
newest = max(m["created_at"] for m in msgs)

# NEW (correct):
newest = max(m["created_at"] for m in shown)
```

That's the entire functional change. The `shown = msgs[:RENDER_CAP]` slice is computed earlier (V0.2 brief Step 1 of the python3 block); reuse it.

## Cleanup nit (same PR — AH2 flagged)

`tests/test_bus_drain_hook.py:647` — `body_json` is assigned but never used. Remove the line.

## New regression test (same PR)

Add `test_overflow_cursor_advances_to_rendered_max` in `tests/test_bus_drain_hook.py`:

```python
def test_overflow_cursor_advances_to_rendered_max(tmp_path, stubs_dir):
    """When daemon returns >RENDER_CAP messages, cursor must advance to the
    rendered slice's max created_at, NOT the full fetched slice's max.
    Otherwise messages RENDER_CAP+1..N are silently lost. Daemon orders
    ASC by created_at (bus.py:349), so shown[:30] are oldest unread."""
    # Simulate 40 messages from daemon (ASC by created_at)
    msgs = [
        {"id": i, "kind": "broadcast", "from_terminal": "lead",
         "to_terminals": ["b2"], "topic": None, "thread_id": f"t-{i}",
         "body_preview": f"msg {i}", "created_at": f"2026-05-11T01:{i:02d}:00Z",
         "acknowledged_at": None}
        for i in range(40)
    ]
    _run_hook_with_msgs(tmp_path, stubs_dir, msgs=msgs, role="b2")
    state_file = tmp_path / ".brisen-lab-bus-last-seen-b2.txt"
    cursor = state_file.read_text().strip()
    # RENDER_CAP=30 → shown = msgs[:30] → max(shown) = msgs[29]
    assert cursor == "2026-05-11T01:29:00Z", \
        f"cursor should be msgs[29] (rendered slice's max), got {cursor!r}"
    # Negative: cursor must NOT be msgs[39] (full slice's max)
    assert cursor != "2026-05-11T01:39:00Z"
```

(Adapt to existing `_run_hook_with_msgs` helper signature — read the test file first to mirror its pattern.)

## Out of scope

- No changes to `bus.py` / daemon (read-only consumer).
- No changes to `RENDER_CAP` value (stays 30).
- No changes to `limit=50` on curl (stays — caps daemon work).
- No changes to settings.json hook timeout.
- No new failure paths beyond the existing five.

## Ship gate

1. `bash -n ~/.claude/hooks/session-start-bus-drain.sh` — passes.
2. `pytest tests/test_bus_drain_hook.py -v` — 10/10 (was 9/9; +1 for the new regression).
3. PR description includes literal `pytest` stdout.
4. AH2 cross-lane review — one-line fix on a file AH2 already cleared in PR #183 + /security-review; expected fast turnaround.
5. **CRITICAL — user-global hook re-deploy:** after merge, B2 cp's the fixed `tests/fixtures/session-start-bus-drain.sh` to `~/.claude/hooks/session-start-bus-drain.sh` (the deployed user-global path B2 already established). Document in ship report. The drift-detection test in `test_bus_drain_hook.py` (PR #183 novelty) catches drift between in-repo fixture and deployed copy — so B2's cp step is the gate that closes drift.

## Files touched

**Modify (in-repo):**
- `tests/fixtures/session-start-bus-drain.sh` — single-line fix at line 377 (`msgs` → `shown`).
- `tests/test_bus_drain_hook.py` — remove unused `body_json` at line 647 + add `test_overflow_cursor_advances_to_rendered_max`.

**Modify (user-global, NOT in repo — re-deploy after merge):**
- `~/.claude/hooks/session-start-bus-drain.sh` — overwrite with merged fixture content.

**Do NOT touch:**
- `~/.claude/settings.json` — no edit needed (the hook command path + timeout are unchanged).
- `brisen-lab/` repo — no daemon change.
- `BRISEN_LAB_TERMINAL_KEYS` Render env — unchanged.

## Estimated complexity

Small · ~30 min · 1 PR · Tier-B follow-up correctness fix. No `/security-review` re-pass (cleared on parent PR #183; this is a 1-line semantic change in already-reviewed file).
