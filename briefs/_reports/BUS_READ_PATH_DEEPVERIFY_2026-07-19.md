# DEEP-VERIFY VERDICT — brisen-lab bus read-path incident (f950386)
AH2 (deputy), 2026-07-19. Director-authorized ultracode/max-depth adversarial verification (lead #13534 item 2).
Method: 4 probes (pool-completeness / cutover-multiplier / brief-C listener-fallback / f950386 defect-hunt), each adversarially refuted, then synthesized. 9 agents. Independent cross-check of lead's parallel 6-lens run.
Target: candidate f950386 (branch deputy-codex/bus-read-path-pool-fix-1) vs deployed prod 24577fe.

## 1. ROOT-CAUSE — INCOMPLETE (pool cap dominant, NOT the whole story)
Second load-bearing co-factor = in-gate connection HOLD-TIME. Gate == asyncio.Semaphore(pool_cap)==10 (db_gate.py:32, db.py:36); permit held for the FULL to_thread(fn), not query time (db_gate.py:54-55). 10 permits / <9ms queries = ~1100 op/s ceiling >> fleet load, so 8s queueing PROVES hold >> query time. Dominant always-on amplifier = the glance permit: ONE gated db_call wrapping ~7 serial queries incl 3 FULL brisen_lab_msg scans (bus.py:3314/3350/3387), fleet-wide per cache miss; + 2 gated calls per direct read (drain + receipt, bus.py:2493). The 8s queue itself = the UNBOUNDED async-semaphore wait (async with _sema has NO wait_for/timeout).
f950386 covers BOTH levers: maxconn 10->25 clears the cliff; TTL 15->60 (4x fewer glance misses) relieves the biggest hold amplifier.
REFUTED: the "~15s tcp_user_timeout charged to the permit" claim — that 15s is confined to a detached daemon reaper (db.py:263-289); gate-permit hold caps <=2.0s/request (db.py:357-362).

## 2. CUTOVER — PARTIAL (named mechanism REFUTED; corrected seat-scaling path real)
"28 seats each poll glance" is REFUTED by code: glance fetched by ONE cockpit controller (single com.baker.cockpit-controller.plist), cached 30s + Lab single-flight lock + 15s TTL => ~0.067 gated calls/s, INVARIANT in seat count. No per-seat Lab poller exists.
Real seat-scaling load = MESSAGE traffic, not polling: each direct read = 2 gated calls. Cliff arithmetic: deployed(10) saturates at ~5 concurrent direct reads x2 = 10 permits; fix(25) absorbs that comfortably but NOT 28 truly-simultaneous (56>25) — absorbs realistic staggered bursts. The actual volume delta from the cutover is UNMEASURED (no rate in code; live bus off-limits).

## 3. BRIEF-C (listener timeout -> legacy fallback) — YES real & independent, pool fix will NOT fix it, but LATENT today
The controller-route/legacy-fallback Brief-C names does NOT exist in prod (bm-b1 wake-listener.py only does `open brisen-lab://wake/<alias>`). It lives ONLY on un-deployed b4 branch deputy-codex/wake-listener-route-via-controller-1 @ a8d876d. f950386 touches ZERO wake code.
SHARPER FINDING (goes beyond brief): once b4 ships it is a GENUINE REGRESSION. Under a Lab-glance outage, glance.read()={} -> wake_skip_reason='no telemetry' -> controller returns HTTP 200 {sent:false}. The b4 listener treats 200/sent=false as SUCCESS and does NOT fall through to the glance-independent legacy `open` (which fires only on exception). Empty-glance also cached 5s. Net: b4 turns a glance outage into a TERMINAL SILENT WAKE DROP with no backstop — strictly worse than today.
FIX (separate brief, NOT a f950386 blocker): before b4 ships require ONE of (a) on sent=false && skipped=='no telemetry' fall through to _dispatch_legacy; or (b) add 'no telemetry' to the controller fresh-read retry set AND force_refresh() (bypass 5s cache).

## 4. f950386 FITNESS — CORRECT & DEPLOY-SAFE. Zero surviving P1/P2 blockers.
- P1 (#-in-SCHEMA_V2_SQL bootstrap crash): FIXED. 0 leading-# lines, 183 `--` lines; guard test test_schema_sql_uses_sql_comments_only.
- P2 (unbounded maxconn blows 128 executor ceiling): FIXED. _configured_pool_maxconn clamps [1,100], fails SOFT (log + fallback to 25, does NOT raise); executor floor pool+8 = max 108 <= 128; low env override clamps UP to floor (cannot starve executor).
  CORRECTION to my #13551: I called the clamp "fail-loud" — it is fail-SOFT (log-and-continue). Behaviorally safe; wording corrected.
- N1 fire-and-forget receipt de-gate: NOT a blocker; ship as-is. record_delivery_receipts_sync (db.py:1200) keeps bounded 3-attempt retry + get_conn() + ON CONFLICT idempotent upsert + drops LOUD on exhaustion (never hangs/crashes). Residual = P3 observability-only: consumes a raw pool conn OUTSIDE gate accounting (gate/pool divergence on hot path) + a narrow restart-correlated delivered_at-NULL window. Not message loss.

## 5. MISSED DEFECTS (new)
1. N1 = fix reintroduces a gate/pool divergence on the HOT read path (de-gated receipt write, raw pool conn outside gate). P3. Single most important new finding on the fix.
2. b4 controller-route latent wake REGRESSION (see §3). Guard before b4 ships. Independent of f950386.
3. Cockpit browser polls /api/agents every 4s (cockpit.js POLL_MS=4000) — local ttyd probing, NOT a Lab-pool driver; double cache absorbs Lab side.
4. _cached_response captures `now` before the lock (bus.py:3065) — present in BOTH deployed+fix (not a regression); slightly weakens "1 build/TTL".
5. Refresh-lock legitimately diverges pool free from gate permits (app.py:1360-1394, peak 2 checkouts) — pre-existing by-design; know it when reading pool telemetry.
6. Amplifier (c) deploy 9251d29 UNMEASURED (not in 24577fe git history; uninspectable from deployed tree). Needs a separate diff if a load-regression hunt stays open.

## 6. BOTTOM LINE
DEPLOY f950386 AS-IS — no pre-deploy change required. Zero surviving P1/P2. It attacks the real problem (maxconn clears the ~5-read cliff; TTL relieves the biggest hold amplifier), root cause INCOMPLETE = pool cap + hold-time both, both in the fix. N1 safe (P3 observability-only, never loss).
After deploy, 3 separable items, none gating the ship:
(1) MEASURE the burst recovers under load; tune BRISEN_LAB_POOL_MAXCONN up if 25 still saturates on a real 28-seat storm.
(2) File 3 P3 follow-ups: strong-ref the receipt create_task; add delivered_at sweep/ack-backfill; optional to_terminals ::text[] cast.
(3) DO NOT ship the b4 wake-listener controller-route until guarded (§3) — as written it turns a glance outage into a terminal silent wake drop; a real regression f950386 cannot fix. This matters most for Monday fleet autonomy (wake drops = seats don't wake).
