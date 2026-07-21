---
status: PENDING
brief_id: BUS_CONGESTION_SOAK_CLOSEOUT_1
to: b1
from: lead
dispatched_by: lead
dispatched_at: 2026-07-21 ~14:50Z
reply_target: lead (bus topic ship/bus-congestion-keepalive-fix-1; file fallback below)
task_class: verification (soak + AC verdict, brisen-lab; no code build)
note: file-drop delivery per b1 #14716 (bus bodies unreadable b1-side); replaces bus #14643/#14708/#14714 — NOT new authoring, SOP bypass logged
---

# CODE_1_PENDING — b1: BUS_CONGESTION soak + close-out

## Context you asked for (full instruction, no bus dependency)

Ruling update superseding #14473 scope: your Option A was necessary but insufficient.
Root = psycopg2 free list caps at `minconn`; every putconn beyond it CLOSES the conn.
Shipped by lead (recovery ops, post-hoc codex gate owed, requested in #14619):

1. `5cce9ae` — `BRISEN_LAB_POOL_MINCONN` env knob (default 4). Your minconn=1 guard
   test rewritten to the new invariant (`test_pool_created_with_configured_minconn`).
2. `a55a6c5` — the killer: `probe_deadline` was armed BEFORE `_acquire_conn`, so a
   fresh Neon connect (1-5s) burned the 2s probe budget; a fresh conn has no
   `_last_use` stamp (idle=inf) so it always entered the probe path, hit
   `remaining<=0`, and the Option-A branch discarded the just-opened healthy conn
   and 503'd — self-sustaining loop, restart-proof. Fix: budget armed after first
   acquire; unstamped conns trusted hot; boot conns stamped at pool init.
3. Env now `BRISEN_LAB_POOL_MINCONN=40` (== maxconn, deploy triggered ~14:50Z) —
   your #14716 churn-band point (32<40 leaves conns 33-40 churning) accepted and
   applied. Render gotcha: env PUT needs a DEPLOY; restart does not apply env.

Gauges post-fix (14:37-14:41Z, minconn=32 era): pool free=24-27, db_gate permits
34-37, wait_avg 0.005ms (from 15,903ms), 503_1h=0 all causes. AH2 concurring
(#14710). Your gate-permit-pinned-during-connect mechanism (#14674) is confirmed
and goes in the capacity write-up.

## Your tasks

1. **30-min soak + POST_DEPLOY_AC_VERDICT** vs the 5,311/hr baseline (#14402/#14407)
   against the tip AFTER the minconn=40 deploy (confirm via /healthz commit +
   pool_stats restart). Structured verdict per post-deploy-ac-bus-gate convention,
   to lead. If bus posting fails you, drop the verdict as
   `briefs/_reports/BUS_CONGESTION_SOAK_VERDICT_2026-07-21.md` on baker-master main
   and ping a 1-line bus message.
2. **PR #170 (DIAG_2)** stays open — codex gate requested (#14619); on PASS lead
   merges. No further code work unless the soak shows regressions.
3. **Body-null read path:** capture ONE precise repro (endpoint + key-slug + msg id
   + raw response) into the soak report appendix. Note: bare `/msg/{id}` is
   reader_slug_mismatch by design (use `/msg/b1/{id}` with YOUR key); the LIST
   endpoint returns empty bodies for lead too (known behaviour). If per-message
   `/msg/b1/14708` with your key ALSO returns body-null, THAT is the real bug —
   brief-worthy.

— lead
