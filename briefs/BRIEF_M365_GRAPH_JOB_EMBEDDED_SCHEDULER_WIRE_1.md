---
brief: M365_GRAPH_JOB_EMBEDDED_SCHEDULER_WIRE_1
author: AH1-lead
dispatched_to: deputy-codex
dispatched_by: lead
harness_v2: true
task_class: small-targeted-bug-fix (single-file wiring, well-understood root cause)
created: 2026-06-05
---

# BRIEF: M365_GRAPH_JOB_EMBEDDED_SCHEDULER_WIRE_1 — Register graph_mail_poll in the LIVE scheduler

## Context

The Microsoft Graph mail poller is **dead in production**. Commit `dfdab00` (#292)
registered `graph_mail_poll` in `triggers/scheduler.py` — but that file is the
standalone `BlockingScheduler`, which production never instantiates. The LIVE
scheduler is `triggers/embedded_scheduler.py` (`BackgroundScheduler`, started by
`outputs/dashboard.py` on FastAPI startup). The job was never added there, so
even with `BAKER_USE_GRAPH=true` the Graph poller never ticks.

Business impact: Gmail→brisengroup forwarding was disabled (DMARC, deputy #1796),
so Baker is **blind to the Director's brisengroup mailbox** until the Graph poller
runs live. This brief wires the job into the live scheduler. The job lands
DORMANT (flag default `false`) — turning it on is a separate Tier-B env flip,
gated on Dennis's `.pfx` cert password. **This brief does NOT enable Graph.**

Why now: the scheduler-idle-harden work (`embedded_scheduler.py`, PR #296) is
merged, so editing this file no longer risks a concurrent-edit conflict.

### Surface contract: N/A — pure backend scheduler wiring; no clickable/UI surface, no new endpoint, no DOM.

## Estimated time: ~30 min
## Complexity: Low
## Prerequisites: none (main is at the merged scheduler-harden state)

---

## Fix 1: Mirror the #292 registration into embedded_scheduler.py

### Problem
`graph_mail_poll` exists only in the dead `BlockingScheduler` (`triggers/scheduler.py:74-87`).
The live `BackgroundScheduler` (`triggers/embedded_scheduler.py:_register_jobs`) has no
Graph job, so it never runs in prod.

### Current State
- Live registration function: `triggers/embedded_scheduler.py:_register_jobs()` at **line 153**.
- `email_poll` is registered at lines **172-179**, immediately followed by the WhatsApp
  comment at line 181. Verbatim (current):

```python
    # Email polling — every 5 minutes
    from triggers.email_trigger import check_new_emails
    scheduler.add_job(
        check_new_emails,
        IntervalTrigger(seconds=config.triggers.email_check_interval),
        id="email_poll", name="Gmail polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("email_poll", config.triggers.email_check_interval)
    logger.info(f"Registered: email_poll (every {config.triggers.email_check_interval}s)")

    # WhatsApp: migrated from Wassenger polling to WAHA webhook (Session 26)
    # whatsapp_poll job removed — inbound messages now arrive via POST /api/webhook/whatsapp
```

- The poll entrypoint already exists and is dormancy-safe:
  `triggers/graph_mail_trigger.py:102` — `def check_new_graph_messages():`
  Line 109 returns immediately (zero DB/health side effects) when
  `GraphClient(GraphConfig()).is_ready()` is False. It has its own try/except
  (lines 113-123) — independent of every other poller.
- Config already present: `config.triggers.graph_mail_check_interval`
  (`config/settings.py:315`, env `GRAPH_MAIL_CHECK_INTERVAL`, default 300s).
- Enable flag: `BAKER_USE_GRAPH` → `GraphConfig.enabled` (`config/settings.py:89`,
  default `"false"`).

### Implementation
In `triggers/embedded_scheduler.py`, **insert immediately after line 179**
(after the `email_poll` `logger.info`, before the line-181 WhatsApp comment) the
following block. Note it adapts the #292 snippet to the embedded-scheduler
conventions: `coalesce=True, max_instances=1, replace_existing=True` **and** the
mandatory `register_expected_job(...)` pairing (see Key Constraints).

```python
    # M365 Graph mail polling — every GRAPH_MAIL_CHECK_INTERVAL seconds.
    # Independent source adapter; inert unless BAKER_USE_GRAPH=true (the
    # check_new_graph_messages entrypoint returns with zero side effects when
    # GraphClient.is_ready() is False). Mirrors triggers/scheduler.py #292;
    # this is the LIVE registration (BlockingScheduler version never runs in prod).
    from triggers.graph_mail_trigger import check_new_graph_messages
    scheduler.add_job(
        check_new_graph_messages,
        IntervalTrigger(seconds=config.triggers.graph_mail_check_interval),
        id="graph_mail_poll", name="Microsoft Graph mail polling",
        coalesce=True, max_instances=1, replace_existing=True,
    )
    register_expected_job("graph_mail_poll", config.triggers.graph_mail_check_interval)
    logger.info(f"Registered: graph_mail_poll (every {config.triggers.graph_mail_check_interval}s)")
```

### Key Constraints
- **MUST pair `add_job` (IntervalTrigger) with `register_expected_job(...)`.**
  `embedded_scheduler.py:161-168` documents the SCHEDULER_JOB_LIVENESS_1 invariant:
  every `IntervalTrigger` `add_job` pairs with one `register_expected_job(...)`;
  an AST pre-flight test enforces this before merge. Omitting it = test failure.
- **No registration-time flag gate.** Mirror `email_poll`: register
  unconditionally; the entrypoint decides dormancy internally. Do NOT wrap the
  `add_job` in `if config.graph.enabled:` — that would make the job vanish from
  the liveness registry when disabled, and the dormancy is already handled in
  `check_new_graph_messages()` (line 109). This matches how the Gmail/Exchange
  pollers behave.
- **Do not change the interval, the job id, or the entrypoint signature.** Reuse
  the existing `graph_mail_check_interval` config and the existing
  `check_new_graph_messages` function as-is.
- Keep the poller independent — it already has its own try/except; do not chain
  it to `email_poll` or any other job (Lesson: sequential pollers must not block
  each other).

### Verification
1. Syntax: `python3 -c "import py_compile; py_compile.compile('triggers/embedded_scheduler.py', doraise=True)"`
2. Liveness invariant / full suite: `pytest tests/ -q` — the SCHEDULER_JOB_LIVENESS_1
   AST test must PASS (proves the add_job↔register_expected_job pairing is intact).
   Run the scheduler-specific tests explicitly too:
   `pytest tests/ -q -k "scheduler or liveness or graph" -v`
3. Registration proof (local, flag off — job still registers but stays dormant):
   load `_register_jobs` against a `BackgroundScheduler` and assert `graph_mail_poll`
   is in `scheduler.get_jobs()` ids, and that `register_expected_job` was called for it.

---

## Files Modified
- `triggers/embedded_scheduler.py` — add the `graph_mail_poll` registration block
  (+ `register_expected_job` pairing) after the `email_poll` block (~line 180).

## Do NOT Touch
- `triggers/scheduler.py` — leave the #292 block as-is. It is dead code in prod but
  harmless; removing it is out of scope (avoids blast radius). Optional cleanup can
  be a separate brief.
- `triggers/graph_mail_trigger.py` — the entrypoint is correct and dormancy-safe; no change.
- `config/settings.py` — flag + interval already exist; no change.
- `outputs/dashboard.py` — startup wiring already imports `embedded_scheduler`; no change.
- **Do NOT flip `BAKER_USE_GRAPH`.** Enabling Graph is a separate Tier-B env op,
  gated on the cert password — not part of this brief.

## Quality Checkpoints (post-deploy)
1. After Render deploys, confirm `graph_mail_poll` appears in the live scheduler's
   job list (scheduler status endpoint / `get_scheduler_status`), every ~300s schedule.
2. Confirm the scheduler-liveness sentinel lists `graph_mail_poll` as an expected job
   (no "missing expected job" alert, no spurious "unexpected job" alert).
3. Confirm `BAKER_USE_GRAPH` is still `false` in Render env (job present but dormant) —
   no `sentinel_health` row should claim graph_mail healthy while disabled.
4. Confirm no scheduler teardown/restart regression in the 15-min window post-deploy
   (the harden work must stay intact).

## Done rubric (Harness V2 — answer these, not "tests passed")
- [ ] `graph_mail_poll` registered in `embedded_scheduler.py` (the LIVE scheduler), not only `scheduler.py`.
- [ ] `register_expected_job("graph_mail_poll", ...)` pairs the add_job; SCHEDULER_JOB_LIVENESS_1 AST test PASSES.
- [ ] Full `pytest` run green on a literal run (paste the summary line; no "by inspection").
- [ ] With flag OFF: job is registered AND dormant (entrypoint returns at line 109, zero side effects).
- [ ] POST_DEPLOY_AC: job visible in live scheduler job list after deploy; flag still false; no teardown regression.

## Gate plan
- **G0 (design):** codex terminal — confirm the single-file wiring + liveness-pairing approach (this is a small fix; G0 may be a quick PASS).
- **G1 (lead):** AH1 runs literal `pytest` + syntax check; verifies the liveness AST test passes.
- **G2 (security):** `/security-review` on the diff (small surface; expected CLEAR).
- **G3 (judge):** codex terminal adversarial review of the final diff.
- **Merge:** AH1 on full green chain (Tier-A).
- **POST_DEPLOY_AC_VERDICT v1:** AH1 (or deputy-codex) posts the structured verdict to the bus after Render deploys — checkpoints 1-4 above.

## Verification SQL
N/A — no DB schema change. Verification is via the scheduler job list + liveness sentinel + (optionally) `sentinel_health` rows for `graph_mail` (must NOT appear healthy while flag is off).
