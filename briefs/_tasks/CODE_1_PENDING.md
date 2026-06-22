---
status: PENDING
brief_id: WAKE_BACKGROUND_NONINTRUSIVE_1
to: b1
from: cowork-ah1
dispatched_by: cowork-ah1
dispatched_at: 2026-06-22
reply_target: cowork-ah1 (bus)
task_class: fleet-infra / developer-tooling (brisen-lab repo + Mac-side AppleScript)
gate_plan: G0 codex-arch APPROVE #3586 + deputy-codex PASS-NITS #3732 + codex AG-202 PASS-NITS #3788 (ALL DONE) -> B1 build -> G1 pytest -> G3 codex code gate -> cowork-ah1 merge -> POST_DEPLOY_AC on Director's Mac
arc: STEALTH_FLIGHT (wake non-intrusive). Follow-on TURNAROUND (agent refresh) = separate brief.
harness_v2: applies
---

# WAKE_BACKGROUND_NONINTRUSIVE_1 ("Stealth Flight") — dispatch to B1

Full brief (this commit): briefs/BRIEF_WAKE_BACKGROUND_NONINTRUSIVE_1.md — READ IT, it is the source of truth.

## What
Agent bus-wakes stop foregrounding Terminal windows (Director's screen crowds). VISIBLE-vs-STEALTH role-split: director-facing agents foreground like today; worker agents wake in the BACKGROUND (no focus steal, `open -g`). High-priority (blocker/incident/needs-director topic, OR kind=ratify_required, OR tier_required=director_only) foregrounds for ALL; ack + heartbeat suppressed (audited).

## Design status: TRIPLE-REVIEWED, all green
- codex-arch G0 design APPROVE (#3586)
- deputy-codex 2nd-eyes PASS-WITH-NITS (#3732, folded)
- codex (AG-202) verify PASS-WITH-NITS (#3788, nit folded)

## Authority order inside the brief (read in this order)
1. ROLE-SPLIT (Director-ratified) — VISIBLE/STEALTH sets; classify from the GENERATED WAKEABLE_TERMINALS; default unclassified -> VISIBLE.
2. G0 RULINGS (codex-arch) — schema facts (kind enum, no priority field), Q1 hybrid spawn, Q2 suppress, Q3 foreground.
3. DEPUTY-CODEX NITS — `open -g` spawn, PARSE URL query BEFORE alias match, deploy = Render + build.sh + install.sh, rollback flag.
4. CODEX AG-202 FINDINGS — fired wake keeps suppressed_reason NULL (use existing async `_audit_wake_event(row["id"], sender_slug, recipient, reason)`); missing/invalid fg => FOREGROUND.

## Repos / deploy
- brisen-lab: bus.py (foreground compute + ack/heartbeat suppress audit), app.py (/api/wake foreground=true), wake-listener.py (?fg= passthrough) -> Render deploy/merge.
- Mac handler: tools/wake-handler/wake-handler.applescript (parse fg, `open -g` background, no frontmost/selected when fg=0) -> recompile via tools/wake-handler/build.sh.
- listener: tools/wake-listener/install.sh.
- Feature flag BRISEN_LAB_WAKE_ROLE_SPLIT_ENABLED default OFF -> emit foreground=true + skip suppress = fail to current behavior.

## Gates
G1 pytest (server pure + integration + listener unit + handler compile/static + preserve PR#80 guards: isAliasLive/acquireSpawnLock/spawn self-delete) -> G3 codex code gate -> cowork-ah1 merge -> POST_DEPLOY_AC_VERDICT v1 on Director's Mac (role-split + brief gate-set verified live).

## Reply
Ship report -> bus to cowork-ah1 (dispatched_by: cowork-ah1).
