# B2 — REMOVE_WAKE_TOPIC_GATE_1 (ship)

**Dispatch:** bus #3317 from `lead` + P0 escalation #3324 + status press #3328. Director 2026-06-18 TOP PRIORITY: *"If you receive the bus, you should wake up. A topic string should not decide priority — remove that feature."* / *"who decides low priority? remove it."* / *"restore waking, otherwise there is no autonomous work."*
**Repo:** brisen-lab (fleet runtime). **PR:** #78 — https://github.com/vallen300-bit/brisen-lab/pull/78
**Branch:** `b2/remove-wake-topic-gate-1`. **Commit:** `9399006`.

## Problem
The `BUS_WAKE_TOPIC_GATE_1` topic-prefix allowlist (PR #77) only woke recipients on
topics starting `dispatch/gate/blocker/ratify/request-changes`. Every other operational
topic (`post-deploy-ac/`, `investigation/`, `cleanup/`, `final-closeout/`, `fyi/`,
`heartbeat/`, `merge/`, `routing/`) was suppressed with `suppressed_reason='low_priority_topic'`
— ~19/26 recent wakes suppressed. That is the fleet-wide wake regression Director flagged:
a topic string was deciding priority, killing autonomous wake-on-receipt.

## Change (`bus.py`)
- Removed `WAKE_WORTHY_TOPIC_PREFIXES`, `WAKE_WORTHY_KINDS`, `_topic_is_wake_worthy`.
- `_is_wake_worthy(kind, topic)` now returns `True` unconditionally — every addressed
  message to a wakeable picker slug wakes. No `low_priority_topic` row is ever written.
- Kept `_is_wake_worthy` as the single wake-decision control point (call site +
  `wake_events` audit branch untouched) so a future re-gate is a one-function change.

## Kept intact (mechanical anti-runaway guards — containment, not priority judgment)
- per-slug 5s debounce · ping-pong loop auto-disable · `AUTOWAKE_MASTER_KILLSWITCH` ·
  `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS`.

## Raised
- Per-slug hourly cap default **20 → 120** (new constant `_DEFAULT_AUTOWAKE_CAP_PER_HOUR`;
  still env-overridable via `BRISEN_LAB_AUTOWAKE_CAP_PER_HOUR`) so it stays a pure
  runaway-backstop, never a routine suppressor now that every message is a wake candidate.

## Tests
- `tests/test_bus_wake_topic_gate.py` rewritten: `_is_wake_worthy` True for every
  kind/topic; a former low-priority topic (`merge/pr370`) now fires exactly one wake +
  NULL audit row; high-priority topic still fires; `ratify_required` still fires.
- `tests/test_bus_autowake_containment.py`: cap-default test asserts the new 120 and
  proves a sub-cap burst all fires with no breach. Debounce/loop/disabled-slugs/killswitch
  tests unchanged and green.
- **Full suite: 225 passed, 1 skipped** (pre-existing `test_a21_h7_auth` collision case,
  unrelated) against local Postgres 16.

```
======================== 225 passed, 1 skipped in 5.27s ========================
```

## Gate + bus
- Ship + G3 gate-request → `lead` #3330; P0 status reply with PR# → `lead` #3331 (topic `gate-request/pr78`).
- Lead to fast-merge + deploy on codex G3 PASS.

## Next
- After merge/deploy: emit `POST_DEPLOY_AC_VERDICT v1` — live check that a `merge/` or
  `heartbeat/`-topic message to a picker slug now fires an OS wake (formerly suppressed).

**Done rubric:** PR open + full suite green + G3 requested. Post-deploy AC pending merge.
