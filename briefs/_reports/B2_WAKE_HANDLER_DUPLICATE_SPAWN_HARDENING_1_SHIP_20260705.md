# B2 SHIP — WAKE_HANDLER_DUPLICATE_SPAWN_HARDENING_1

- **Brief:** `briefs/_tasks/WAKE_HANDLER_DUPLICATE_SPAWN_HARDENING_1.md` (dispatched_by: lead)
- **Repo / PR:** brisen-lab → PR **#99** · branch `b2/wake-handler-duplicate-spawn-hardening-1` · commit `66660b4`
- **Reply-to:** lead (bus #5566, topic `ship/wake-handler-duplicate-spawn-hardening-1`)
- **Task class:** bug-fix / hardening. All changes in the **brisen-lab** repo (not baker-master).

## What shipped (all 4 fixes host-side, where nudge-vs-spawn is known)

| Fix | Where | Change |
|-----|-------|--------|
| **F1** api-key stall | handler | Spawn `.command` now `unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN` before the picker. Box auths via OAuth (`~/.claude.json` oauthAccount, no `customApiKeyResponses`), so CC falls back to OAuth and reaches its prompt unattended, zero keypresses. Only the two dialog-triggering vars stripped — not a blanket `*_API_KEY` wipe — so a Baker MCP key survives. |
| **F2** host-local liveness | handler + server | New read-only `GET /api/slug_live/<alias>` reports fresh cross-host liveness from `forge_sessions` (any host). Handler curls it **only on its spawn path** (after nudge + local `isAliasLive`) and skips **just the spawn** if live elsewhere. |
| **F3** no debounce | handler | Atomic spawn-lock TTL raised 45s→120s → doubles as the per-slug spawn cooldown. Further wakes within the window hit BUSY, not spawned. |
| **F4** silent drops | handler | Every skipped/deduped spawn (`live_elsewhere` / `spawn_cooldown`) appended to `~/.brisen-lab/wake-handler.log`. |

## Key design decision (surfaced to lead)
First built F2/F3 **server-side** (suppressing `wake_request` emission in the bus dispatch loop), then **reverted**. A server-side wake suppression would starve a LIVE *idle* session of its `check bus` nudge on new dispatches: the nudge and the spawn are both driven by the one `wake_request`, and only the host handler knows which of the two will happen. Both fixes belong host-side; the server only exposes the liveness **read**.

## Acceptance criteria
- **AC1** (burst → 1 spawn, rest deduped) — enforced host-side by the spawn lock; `wake-handler-regression-test.sh` gate B (5 concurrent → exactly 1).
- **AC2** (spawn reaches CC prompt, no api-key dialog) — F1; source-asserted in pytest + standalone. **Live Mini verification owed** (JOINT verify with lead).
- **AC3 / AC5** (local liveness; stale doesn't block) — existing `isAliasLive` ticker parent-pid check (regression gates A / 3), unchanged.
- **AC4** (live elsewhere → 0 spawns) — F2; `GET /api/slug_live` tests (fresh→true, stale/none→false).

## G1 self-check
- `py_compile` clean: `bus.py`, `app.py`, `tests/test_wake_duplicate_spawn_hardening.py`.
- `osacompile` clean: `wake-handler.applescript`.
- `bash -n` clean: `wake-handler-regression-test.sh` (TTL backdate 60→150s; gate C anchored to avoid `isAliasLiveElsewhere` collision; new gate C2 asserts F1–F4 markers).
- 416 tests collect clean.
- F1 source assertion verified standalone (unset precedes picker invocation on the spawn line).
- **DB/endpoint pytest cases auto-skip locally** (no `TEST_DATABASE_URL`) and run in **CI ephemeral Neon**. Deliberately NOT run against the shared build-pool DB — the `fresh_db` fixture TRUNCATEs `forge_sessions`, which would collide with b1/b3/b4.

## Deploy dependency (flagged loud)
- Server endpoint (`/api/slug_live`) ships on **Render merge**.
- Handler fixes F1/F2/F3/F4 need a **Mac Mini rebuild + install + adhoc re-sign** of `Brisen Lab Wake.app` to activate (per the 2026-06-22 forward-port pattern). That host step is **outside this PR**.

## Gate plan
codex G3 (correctness/security) → lead merge → Mini install + JOINT behavioral verify.
