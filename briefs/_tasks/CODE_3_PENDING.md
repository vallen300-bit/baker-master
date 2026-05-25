---
dispatch: BUS_AUTOWAKE_CONTAINMENT_1
to: b3
from: cowork-ah1
dispatched_by: cowork-ah1
status: PENDING
authored: 2026-05-25
brief: /Users/dimitry/baker-vault/_ops/briefs/BRIEF_BUS_AUTOWAKE_CONTAINMENT_1.md
target_repo: brisen-lab (vallen300-bit/brisen-lab)
branch: bus-autowake-containment-1
workdir: ~/bm-b3/brisen-lab
estimated_time: 6-8h
complexity: Medium
priority: tier-b
gate_class: MEDIUM
reply_to: cowork-ah1
prior_mailbox_state: superseded — gate-5 merged (baker-vault PR #114, completed 15:15Z 2026-05-25)
parallel_b4_work: BUS_AUTOWAKE_SESSION_HEALTH_1 (no file overlap — this touches bus.py + app.py + db.py; that touches wake-handler.applescript + static/*)
---

# B3 — BUS_AUTOWAKE_CONTAINMENT_1: bus-side rate cap, disable list, loop detector, audit log, health endpoint

Read brief at `~/baker-vault/_ops/briefs/BRIEF_BUS_AUTOWAKE_CONTAINMENT_1.md` for full spec.

## TL;DR

5 surgical containment primitives on top of PR #40's bus-arrival auto-wake. Director-ratified pre-mortem 2026-05-25 ~20:00Z. Replaces single global kill-switch with: per-slug hourly cap (default 20), per-slug disable env list, ping-pong loop auto-detect+disable, wake audit table, Director-visible `/api/wake_health` endpoint.

## Changes (4 files)

1. **`bus.py`** — 5 module-level state vars; expand hook block with cap+disable+loop checks; audit write call
2. **`app.py`** — new `/api/wake_health` GET endpoint
3. **`db.py`** — add `wake_events` table to SCHEMA_SQL
4. **`tests/test_bus_autowake_containment.py`** — NEW, 8 unit tests

## Ship gate

- pytest green (existing + new tests)
- Manual smoke: 25 rapid posts to b1 → 20 fired + 1 cap_breached alert
- Manual smoke: `BRISEN_LAB_AUTOWAKE_DISABLED_SLUGS=b1` env + redeploy → b1 messages skip + suppressed_reason='disabled_slugs' rows

## Reporting

On PR open: bus-post `cowork-ah1` topic `ship/bus-autowake-containment-1`. Include PR # + pytest output + branch sha.

## Gate chain

1. b3 self-test → PR open
2. AH2 (deputy) static review
3. `/security-review`
4. cowork-ah1 merge on PASS / PASS-WITH-NITS
