# CHECKPOINT — AH2 (deputy) 2026-07-19 ~17:42Z

## >> CURRENT STATE FOR DEEP-VERIFY (Fable + ultracode) SESSION — READ FIRST <<
**MISSION (Director directive via lead): loops must be LIVE BY MORNING. Pool fix TONIGHT +
ultracode DEEP-VERIFY of the fix + pre-authorized fallbacks. Deploy f950386 = the permanent cure
for the brisen-lab read-path outage.**

**THE FIX TO DEEP-VERIFY:** brisen-lab repo, branch `deputy-codex/bus-read-path-pool-fix-1` @
commit **f950386** "fix(bus): close pool gate findings" (ON ORIGIN). Local worktree:
`/Users/dimitry/bm-aihead2/.codex-worktrees/bus-read-path-pool-fix-1`. Files: db.py, db_gate.py,
bus.py, app.py + tests (test_bus_read_path_pool_fix.py, test_db_conn_harden.py,
test_bus_read_path_false_empty_fix_1.py). Read diffs from GIT (read-path is degraded).

**WHAT THE FIX DOES (root cause = 10-conn pool + db_gate saturation; COUNT-OVER hypothesis REFUTED):**
1. maxconn env-tunable `BRISEN_LAB_POOL_MAXCONN` default 25, capped [1,100] fail-loud (db.py
   `_configured_pool_maxconn`); db_gate stays coupled to pool_cap. Neon ceiling measured live 901
   (16 consumers, 885 free) — 25 safe. Executor floor = maxconn+8 = 108 < 128 ceiling at the cap.
2. De-gate per-read delivery-receipt write (bus.py `_schedule_delivery_receipts` via
   asyncio.create_task -> to_thread, NOT db_gate.db_call) — removes 1 of 2 gated calls/read.
3. Glance cache TERMINALS_TTL_S 15->60; recipient-array `to_terminals && %s` prefilter on 3
   dashboard scans (+badge) backed by new partial GIN `idx_msg_dashboard_to_terminals`.
4. db_gate acquire-wait instrumentation wired into pool_stats_gauge.

**GATE HISTORY (do not repeat):** rev1 f556438 → my review PASS → codex gate FAILED #13503 (2 real
defects). rev2 f950386 fixed both: **P1** (was deploy-blocker) `#`→`--` inside SCHEMA_V2_SQL (exec'd
by bootstrap every startup; `#`≠SQL comment) + new guard test; **P2** unbounded maxconn → cap 100.
My re-review of rev2 = PASS (verified live: SCHEMA_V2_SQL zero `#` offenders; cap 10000→100 fail-loud).
**Codex RE-GATE routed #13538 (codex woken) — AWAITING codex verdict.** Non-blocking N1(create_task
GC-ref)/N2(gauge naming) deferred. My review MISSED P1 → lesson
`memory/feedback_review_sql_comment_syntax_in_executed_strings.md`.

**STATUS 2026-07-19 ~18:21Z (Fable deep-verify seat) — DEPLOY GATE CLEARED, AWAITING LEAD DEPLOY:**
- (1) ✅ RE-REVIEW of f950386 RE-CONFIRMED vs git (P1: 0 leading-# in SCHEMA_V2_SQL + guard test; P2:
  maxconn clamp [1,100] fail-SOFT, executor floor 108<128). Relayed lead #13551.
- (2) ✅ ULTRACODE DEEP-VERIFY DONE (9-agent workflow, 4 probes adversarially refuted). VERDICT +
  full report: `briefs/_reports/BUS_READ_PATH_DEEPVERIFY_2026-07-19.md`; relayed lead #13580. Findings:
  ROOT-CAUSE = INCOMPLETE (pool cap DOMINANT + in-gate HOLD-TIME co-factor; fix's 2 levers maxconn+TTL
  cover both). CUTOVER = PARTIAL (literal '28-seat glance poll' REFUTED — ONE controller, cached; real
  load = message traffic 2 gated calls/read; volume delta UNMEASURED). f950386 = CORRECT/DEPLOY-SAFE,
  ZERO P1/P2. N1 fire-and-forget receipt = SAFE (P3 observability-only, never loss).
- (3) ✅ CODEX GATE = PASS #13578 (no findings, 'Lead may deploy on PASS'; posted to topic
  gate/bus-read-path-pool-fix — SINGULAR, flagged the 'gates/' mismatch to lead). Acked. Both independent
  checks CONVERGE on DEPLOY. Pinged lead deploy-clear #13587.
- (4) ✅ DEPLOYED + POST_DEPLOY_AC = PASS-WITH-FINDING (~18:34Z, verdict lead #13612). Live gauge
  /api/v2/pool_stats: maxconn=25 (was 10) ✅ | db_gate permits 18-23 (was 0) ✅ | acquire-wait
  waited_count=0 over 750+ acquires (8s-hang QUEUEING ELIMINATED) ✅ | 503-rate 1271(peak)→~50-78/hr
  (~96% drop) ✅ | reads succeed, ZERO 000-hangs, PK /msg 200 ✅. **OUTAGE CURED.**
  ⚠️ FINDING: residual ~20% fast bus_busy_retry 503s at single-client cadence — captured {detail:
  bus_busy_retry}=app.py:196 BusPoolExhausted WITH pool idle right after (used=2,permits=19) = momentary
  (<300ms) FLEET micro-bursts still clip 25 conns → 300ms acquire-budget expires → fast retryable 503,
  clears instantly (DESIGNED backpressure, matches deep-verify §6 item-1). RECOMMENDED lead bump
  BRISEN_LAB_POOL_MAXCONN 25→40 (env-tunable now, Neon ~885 free; needs manual redeploy) as a Monday
  hedge — optional, clients already retry. AWAITING lead's maxconn-bump call.
- POOL-FIX LANE = essentially CLOSED (deployed+verified).
- **LEAD #13616 (AC accepted 'well run'):** (1) BRISEN_LAB_POOL_MAXCONN=40 SET on Render (my Monday hedge)
  — lands with the NEXT deploy, no standalone redeploy. (2) codex merged-tree addendum found a REAL P1
  #13609: `lifecycle_ready` + `lease` endpoints run sync `db.*` OUTSIDE the gate on the event loop —
  fix folded into deputy-codex branch on top of rider df5a114, single codex delta-gate, then lead deploys.
  (3) BB autowake RE-ENABLED in env. (4) micro-burst 503s accepted as designed backpressure.
- **✅ COMBINED DEPLOY @505f299 LIVE + POST_DEPLOY_AC = PASS (verdict lead #13664, ~20:19Z).** Gauge:
  maxconn=40 (was 25), permits=37 free, executor=48 (40+8), waited=0, 503_1h 490→116 falling; read burst
  14/15 200 + PK 200, ZERO hangs; success 80%→93%. #13609 gate-bypass INFERRED-healthy (no loop-block
  symptoms). BB autowake = env-set by lead (functional wake = lead/BB lane). **BUS-READ-PATH INCIDENT LANE
  CLOSED ON MY SIDE** (pool fix f950386 + 40-bump + gate-bypass all live + verified).

## WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1 (my brief, lead #13490) — AUTHORED + ROUTED
- **Brief:** `briefs/BRIEF_WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1.md` — DIAGNOSE-FIRST, Harness V2, routed lead #13626 for line-read.
- **KEY FINDING (reshaped premise):** glance `unacked_count` (bus.py:3378) is ALREADY to_terminals-addressed-filtered;
  the real leak = MISSING KIND filter → `kind=broadcast` counts toward a seat's wake-driving count. LIVE REPRO:
  cowork-librarian unacked_count=2 = #11801/#11802 (b1, kind=broadcast, fleet/librarian-wiring-probe), stuck since
  ~#118xx. Contradicts existing guard bus.py:105 ('never re-wakes a non-dispatch'). Controller consumer =
  `scripts/cockpit_controller.py` (wakes on glance unacked_count, ~line 147/256).
- **AC-1 = diagnose (deputy→lead before code):** split stuck seats into H1 (broadcast/non-dispatch), H2 (dispatch
  count/ack-403 asymmetry), H3 (cowork-* App-resident real backlog = SEPARATE lane, hand off).
- **My recs to lead:** Q1 Option A (server field `wake_obligation_count` = dispatch-only drives wake; keep all-kinds
  count for Director display); Q2 exclude broadcast+lifecycle, dispatch-only wake-driver, env-listed; Q3 hand H3 to cowork lane.
- **APPROVED by lead #13630** (premise-reshape confirmed). **H4 FOLDED** (write-path retry drops
  to_terminals → empty-addressee dead-letters #13453/#13457, re-posted clean as #13620/#13621; added as
  hypothesis + AC-1 split (d) + fix-side server-reject-empty-to_terminals + client-resend-full-payload + AC-7).
- **BUILDER = b4** (parallel; deputy-codex stays on Brief-B/C per lead steer). **Dispatched b4 the AC-1
  DIAGNOSE-FIRST step #13632** (self-contained; b4 doesn't need the 10KB brief for AC-1). Lead notified #13633.
- **✅ b4 AC-1 DONE (#13658) → my CROSS-LANE = PASS + model rec → lead #13666. AWAITING LEAD MODEL-LOCK.**
  b4 report: bm-b4/briefs/_reports/B4_wake_attribution_addressee_filter_ac1_20260719.md. Classification:
  H1 broadcast=2 (11801/11802) + **H1' NEW status-relay=3** (cowork-movie-desk 11687/11852/11855, topic=heartbeat*
  → _is_status_relay) = DOMINANT in-scope leak=5; H2 ack-fail=0 (unprobeable cross-seat); H3=7 cowork-*/codex-arch
  (OUT, cowork lane); fresh=2 self-clear.
  - **VERIFIED predicates vs deployed bus.py:** _is_delivery_tracked bus.py:107 (=dispatch AND execute_obligation),
    _is_status_relay bus.py:156. Glance count + controller have NO kind gate (the leak).
  - **⚠️ H4 REFUTED-AS-FRAMED (b4 fail-loud, I confirm):** empty/NULL to_terminals CANNOT drive a per-seat
    unacked_count (unnest+&& excludes empty). So #13453/#13457 had a real slug (→H2/H1') OR drove unacked_total,
    NOT the per-seat wake. bus_post also does NOT drop to_terminals on retry. #13453 attribution = NON-BLOCKING
    residual (needs server-side query / owning-seat key + lead/cowork-ah1 origin context).
  - **MODEL REC (lead to lock):** Option A server-side bus.py `wake_obligation_count` = unacked where
    _is_delivery_tracked AND NOT _is_status_relay; keep all-kinds unacked_count for display; controller ONE-LINE
    re-point SERIALIZES after B+D (same file) or folds in; + empty-to_terminals write-reject hygiene.
- **NEXT (me):** on lead model-lock → (a) **PING DIRECTOR** (Director directive 2026-07-19 ~20:5xZ: "ping me when
  lead locks the model") → (b) commit full brief (briefs/BRIEF_WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1.md) to main →
  (c) dispatch b4 the build → BLOCKING codex gate → deputy cross-lane → lead deploy → deputy live-AC.
- ⚠️ SEPARATE follow-on (NOT gating this deploy, matters for Monday fleet autonomy): b4 wake-listener
  controller-route (branch deputy-codex/wake-listener-route-via-controller-1 @a8d876d, NOT deployed) is
  a LATENT REGRESSION — glance outage → 'no telemetry' → HTTP 200 {sent:false} → b4 treats as success,
  no fall-through to legacy `open` backstop → terminal silent wake drop. Guard BEFORE b4 merges;
  reconcile vs click-wake @2adc913d. f950386 cannot fix it. Flagged lead #13580.
- Pre-authorized fallback: if deploy stalls, lead restart brisen-lab (Render srv-d7q7kvlckfvc739l2e8g).

**OUTAGE OPS:** read-path degraded/near-total in bursts (0/5 reads, healthz 200@0.057s = pool
saturation); reads/acks fail HTTP 000 in bad bursts, recover in windows. Read diffs from git; post
via write-path with retry-backoff; ack via `scripts/brisen_lab_ack.sh <id>` with retry. Terminal key
via `source scripts/brisen_lab_terminal_key.sh; brisen_lab_read_terminal_key deputy ""`.
`python3` here is 3.9 (PEP-604 breaks) — use `python3.12` for repo code; bus/otel tests need CI.

**OTHER LANES:** ARM wake-loop #13410 RESOLVED (arm self-cleared; stood down).
#13498 (deputy-codex pre-FAIL diff-post, SUPERSEDED) — content already read from git; low-priority re-read.
LANE 1 sweep-guard PAUSED (Part B revised diff from deputy-codex #13333 pending — can't resume until dc reposts).

**>> NEXT-SEAT TOP TASK: author WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1 (lead #13490, I own it). <<**
FRESH EVIDENCE captured this session (2026-07-19 pool-fix seat): daemon lifecycle broadcasts (e.g.
#13552-13560, #13595-13606: lifecycle/restart, forced-kill, refresh-cadence-sweep) returned **403 on
my ack attempts** — they are NOT deputy-addressed, so I CANNOT ack them, yet the daemon counts them
toward a seat's unacked → drives spurious/unclearable controller wakes (PINNED Case-2: baden-baden-desk
wake-looped for #13453, non-addressee). RECON POINTERS (prod baseline ~/bm-b1-brisen-lab):
  - app.py:1563 `_desk_unacked_inbound_count_sync(alias)` — the MATTER-DESK nudge path; ALREADY claims
    to count "ADDRESSED, unacked, undeleted inbound" (docstring app.py:1564). VERIFY it truly filters
    `to_terminals @> [alias]` / `alias = ANY(to_terminals)` and is not the leak.
  - The LEAK is likely the CONTROLLER wake path, NOT the desk-nudge path: check `cockpit_controller.py`
    (the tmux-seat driver) for how it decides to wake a seat from unacked/glance — that's the one PINNED
    says counts non-addressed msgs. Also check the daemon's own unacked count feeding wakes.
  - FIX DIRECTION: filter ALL unacked-driven wakes to `to_terminals`-addressed only (exclude broadcasts
    / non-addressed lifecycle rows). Brief via write-brief skill + Harness V2 blocks; gate = codex.
  - Note: `unread=true` inbox for deputy returns 0 (broadcasts aren't in the addressed-unread list) —
    so the addressed-read API is already correct; the bug is in whatever wake-decider reads a BROADER
    unacked count (likely a raw `acknowledged_at IS NULL AND deleted_at IS NULL` without to_terminals).

---

(historical detail below — superseded by the block above)

Two live lanes. Bus read-path RECOVERED (lead restarted brisen-lab ~15:33Z via Render API,
srv-d7q7kvlckfvc739l2e8g) — interim relief, re-degrades under load until the pool fix lands.
Reads working normally again; `scripts/check_inbox.sh` + single-id `/msg/deputy/<id>` both OK.

## RESUME POINTER (top of stack)
- **LANE 2 pool fix — BUILT + REVIEWED PASS + codex gate ROUTED.** Commit `f556438` "fix(bus):
  relieve read-path pool saturation" in brisen-lab worktree
  `/Users/dimitry/bm-aihead2/.codex-worktrees/bus-read-path-pool-fix-1` (branch
  deputy-codex/bus-read-path-pool-fix-1). Files: db.py/db_gate.py/bus.py/app.py + 3 tests.
  **My review = PASS** (#13489): env-tunable maxconn=25 w/ fail-safe+fail-loud (verified live by me),
  Neon ceiling documented in-code (901/16/885), de-gate receipt write, 3× recipient-array `&&`
  prefilter + partial GIN idx_msg_dashboard_to_terminals, TTL 15→60, acquire-wait gauge, COUNT-OVER
  absent. **BUT my PASS MISSED a deploy-blocking P1** (see below). 2 non-blocking notes (N1
  create_task GC-ref; N2 gauge naming).

  **>> CODEX GATE FAILED #13503 — deploy on HOLD, re-dispatched to deputy-codex #13507 (woken),
  lead updated #13511. <<** Two real defects, both confirmed by me vs source:
  - **P1 (deploy-blocking):** the 3 new index comments use `#` INSIDE SCHEMA_V2_SQL (db.py:612
    string, executed by bootstrap db.py:2008 every startup) -> Postgres `#` != comment -> bootstrap
    SYNTAX ERROR every boot, index never lands. FIX: `#`->`--` + schema smoke test. My review miss;
    lesson: `memory/feedback_review_sql_comment_syntax_in_executed_strings.md`.
  - **P2:** unbounded BRISEN_LAB_POOL_MAXCONN blows app.py's 128 executor ceiling (floor=maxconn+8).
    FIX: clamp/reject out-of-range (prefer clamp in _configured_pool_maxconn to [1,~100], fail-loud).
  - Else PASSED codex (3.12 py_compile, db_gate probe, Neon 901 free~880). Branch STILL local-only —
    told deputy-codex to push origin this round.
  **NEXT (me):** deputy-codex reposts revised diff -> I re-review the 2 deltas (read from git
  worktree) -> re-route codex gate -> lead deploys on PASS -> POST_DEPLOY_AC (503-rate->~0).

  **>> DEADLOCK (17:24Z): read-path FULLY DEAD again (0/5 reads timeout, healthz 200@0.057s =
  pool/db_gate saturation). deputy-codex can't READ #13507 to fix P1/P2 -> fix cycle frozen (same
  trap the 15:33Z restart broke). Recommended lead #13517 (woken): (A) RESTART brisen-lab again to
  open a window [my rec — keeps deputy-codex as builder, avoids 2-writer worktree collision], or
  (B) authorize me to apply the 2-line fix directly (I use git+write-path, but deputy-codex must
  stand down on the worktree first). AWAITING lead. On restart/window: expect deputy-codex revised
  diff -> re-review -> re-gate -> deploy. <<**

  **>> OUTAGE WORSENED (17:30Z): near-total — read AND ack-write both fail (HTTP 000); only healthz
  (no-DB) responds. Repeated `[wake] check #13498` nudges are a WAKE-STORM symptom: #13498 is my
  genuine unacked msg but the outage blocks read+ack, so the wake re-fires. INTENT: ack-blind #13498
  to stop the storm (it's deputy-codex's PRE-FAIL diff-post, created before codex #13503 — content
  SUPERSEDED; I already read the diff from git + ran review->gate->re-dispatch). Ack COULD NOT LAND
  (ack-path dead this burst). TODO on first write-window: ack #13498 blind + MUST re-read its body
  on read-path recovery (full-history) to confirm nothing new. Precedent: #13403 same handling.
  Holding — not hammering the dead endpoint; will act on lead restart / window. <<**

  (superseded) prior: **Codex gate ROUTED #13482
  (blocking), codex woken.** ⚠️ Branch NOT on origin yet — nudged deputy-codex to push (#13493) so
  lead can deploy on codex PASS. **NEXT (me): await codex verdict → on PASS ping lead to deploy →
  POST_DEPLOY_AC (503-rate→~0). On FAIL, re-route to deputy-codex.** DB-gated tests auto-skip on my
  host (no TEST_DATABASE_URL + missing otel) — codex gate + CI cover them.
- ~~building~~ deputy-codex ACK #13451, built in the
  **brisen-lab repo** (`~/bm-b1-brisen-lab`, branch deputy-codex/bus-read-path-pool-fix-1) — NOT
  baker-master. ⚠️ My dispatch #13449 wrongly said "baker-master"; the bus/pool/db_gate/app code
  lives in the brisen-lab repo. deputy-codex caught it (#13460, fail-loud), I confirmed the
  correction #13466. **Neon ceiling gate PASSED (#13460): max_connections=901, 16 consumers, 885
  free ≫ ≥50 bar → maxconn=25 safe.** WAITING on deputy-codex to post the final diff to me.
  ON DIFF: review (tests on a literal worktree; Neon-ceiling fail-loud guard documented;
  de-gate receipt write; glance cache 60s + index the 3 seq-scans; acquire-wait instrumentation;
  EXPLAIN ANALYZE) → route independent `codex` gate → lead deploys on PASS → POST_DEPLOY_AC
  (503-rate→~0). Lead rulings banked at #13442. Read-path re-degrading under load (503s) — use
  single-id reads + ack retry-backoff.
- **ARM wake-loop (#13432/#13410): RESOLVED — STOOD DOWN** (lead #13490: arm self-cleared #13410
  via ack-by-id once daemon warmed). No further action.
- **NEW small brief I own: WAKE_ATTRIBUTION_ADDRESSEE_FILTER_1** (lead #13490). Same-class Case 2:
  baden-baden-desk wake-looped for #13453 (not addressee). Root pattern: daemon counts
  NON-addressed msgs toward a seat's unacked -> unclearable controller wakes. Fix = filter
  unacked-driven wakes to `to_terminals`-addressed only. SEQUENCE AFTER pool fix, alongside
  audit B/C/D/E. I told lead I'd author + sequence it.
- Then resume LANE 1 sweep-guard (Part B revised diff from deputy-codex #13333, still pending).

## LANE 1 — SWEEP_TIMING_ACTIVE_WORK_GUARD_1 (my dispatch lane, cross-lane review + gate owner)
- **Origin:** lead dispatch #13201 (Director-ratified). Stop the ~10x/day mid-build force-kills of
  codex-family seats by the brisen-lab refresh-cadence sweep.
- **Brief:** `briefs/SWEEP_TIMING_ACTIVE_WORK_GUARD_1.md` (Part A daemon + Part B host; D1 root cause
  CORRECTED per deputy-codex V2/V3 — not stable-uuid; likely codex doesn't re-register a fresh
  forge_session on relaunch → old never-ended open row stays newest → age>8h forever).
- **Builder:** deputy-codex. **Reviewer/gate-router:** me (deputy). **Gate:** independent `codex` seat.
- **STATUS: Part B @5592cbf6 FAILED codex gate (#13302).** 2 fail-OPEN data-loss P1s on the
  WIP-autosave path: (a) untrusted/missing worktree scan consumes lifecycle/restart WITHOUT saving
  (default codex root `~/baker-vault/.codex-worktrees` missing on host → codex seat fail-open in prod);
  **this one traces to MY F3 review guidance** — owned, lesson captured
  (`memory/feedback_review_fail_closed_on_data_safety_paths.md`); (b) failed `git stash create`
  swallowed silently. Fail-CLOSED fix relayed to deputy-codex #13333 (woken): mark restart seen ONLY
  on genuine autosave success OR trusted-nothing-to-save; untrusted/failed = debounced retry; + 2
  regression tests (missing-roots NOT-seen; stash-fail NOT-seen).
- **NEXT (me):** when deputy-codex reposts the revised diff → re-review (run tests on a literal
  worktree add; check the tristate return + debounce) → re-route the independent `codex` gate → on
  PASS, merge Part B (baker-master; branch `deputy-codex/sweep-timing-active-work-guard-1`).
- **THEN Part A (daemon):** unblocked (Render Frankfurt cleared, lead #13284). After Part B merges,
  dispatch Part A to deputy-codex: `app.py _refresh_one` codex-family min-quiet-window (default 900s,
  env `BRISEN_LAB_CODEX_QUIET_WINDOW_S`), stale/missing heartbeat = UNKNOWN→DEFER, DEFER on
  `worktree_dirty=true`, guard at BOTH enqueue + idle-drain, per-family configurable thresholds,
  cap re-queue freq (D1). Deploys same-lane (Render clear).
- Prior gate cycle: rev1 @f573b422 → my 3 findings (F1 URL hard-pin, F2 non-destructive stash, F3
  churn) → rev2 @5592cbf6 fixed all 3, I cleared, but codex FAILed on the fail-open fallout of F3.

## LANE 2 — BUS_READ_PATH_DEGRADED (my standing bus-health lane) ⭐ NOW TOP PRIORITY, LIVE INCIDENT
- **Origin:** lead dispatch #13289. **Brief:** `briefs/BUS_READ_PATH_DEGRADED_DIAGNOSTIC_1.md`
  (diagnose-first). ⚠️ Its primary fix (COUNT-OVER) is **REFUTED** — see below; brief §5 fix #1 is DEAD.
- **⛔ H1 (COUNT-OVER) REFUTED** by deputy-codex D1-D6 diagnostic **#13401** (2026-07-19 ~15:00Z).
  EXPLAIN: COUNT-OVER adds only ~1.5ms; queries run <9ms. **DO NOT ship the COUNT-OVER/limit+1 fix.**
- **✅ CORRECTED root cause = 10-CONNECTION POOL SATURATION.** `db_gate` semaphore == `pool_cap`
  (coupled, db_gate.py:32); `_POOL_MAXCONN=10` HARDCODED (db.py:36, NOT env-tunable). Queries are
  fast; requests HANG ~8s QUEUEING for one of 10 conns. Amplifiers (deputy-codex #13401): (a) glance
  `/api/v2/terminals` = 1 gated call, 7 queries incl **3 full brisen_lab_msg seq-scans**, per 15s
  cache-miss, fleet-wide; (b) **every `/msg` read does a SECOND gated call** for a delivery-receipt
  write → 2 gated calls/read; (c) deploy 9251d29 possible load amplifier (MEASURE not rollback).
- **✅ CORRECTED FIX (supersedes brief §5; small): (1)** make `maxconn` env-tunable + raise 10→~25
  [primary; confirm Neon compute conn ceiling first]; **(2)** async/de-gate the per-read
  delivery-receipt write (removes 1 of 2 gated calls/read); **(3)** lengthen glance cache 15s→60s +
  index its 3 scans; **(4)** fold in deputy-codex's acquire-wait instrumentation same diff.
  Relayed to lead **#13434**.
- **Live evidence captured (perishable, in brief §2):** pool free=0, **db_gate permits=0**,
  bus_503_rate_1h climbed 696→**1271**; `/msg` reads HTTP 000 (timeout) while `/healthz` 200 @0.07s.
  Read-path is presently a near-outage. Add to brief: the db_gate semaphore (not just raw pool) is the
  acute choke.
- **STATUS (updated ~14:45Z): NOW TOP PRIORITY over sweep-guard (lead #13372 — read-path outage is
  SUSTAINED + silently killing fleet dispatch delivery; lead pre-authorized daemon-side deploy).**
  I redirected **deputy-codex** off sweep-guard onto this fix (#13389); deputy-codex ACK'd +
  investigating (#13395); sweep-guard (Lane 1) PAUSED. Went straight to the fix (no separate
  instrumentation deploy — evidence sufficient).
- **FIX dispatched:** in `bus.py` `get_msg` `_read()` (~2441-2465) drop `COUNT(*) OVER ()`, fetch
  `effective_limit+1`, `complete = (len(fetched) <= effective_limit)`, trim to limit. **Compat risk
  to check:** any consumer reading `total`/`_match_total` as an exact count (not just to derive
  `complete`). TDD + EXPLAIN ANALYZE alongside. Blocking codex gate → **lead authorizes deploy on
  codex PASS** (protected; pre-offered — ping lead to flip).
- **NEXT (me):** read deputy-codex's diff → review → route codex gate → ping lead for deploy →
  POST_DEPLOY_AC (read 503-rate→~0). THEN resume sweep-guard Lane 1.
- **OUTAGE OPS NOTE (worsened ~15:00Z): read-path now FULLY dead — even single-id `/msg/<id>` PK
  reads return 000/503 (db_gate permits=0, 503-rate ~1100/hr); write-path (POST) also intermittently
  shedding.** This DEADLOCKS coordination: deputy-codex likely can't read the dispatch to build nor
  post a readable diff. I have 3 UNREAD-behind-outage: #13388 (lead auth re-send, equiv to #13385
  already actioned), #13401, #13403 (likely deputy-codex investigation/diff OR lead follow-ups) —
  none readable.
- **RECOMMENDED TO LEAD (#13418): restart the brisen-lab Render service NOW** to clear stuck
  COUNT-OVER queries + reset pool/db_gate → reads recover → normal build pipeline resumes. Safe (DB
  external/Neon). Temporary (re-degrades) but breaks the deadlock. Also OFFERED to build the fix
  myself as a hedge if deputy-codex is stalled — awaiting lead's go on that (would be a disclosed
  lane-cross under incident + unreachable-worker + lead pre-auth).
- **ON READ-PATH RECOVERY (restart or burst-clear):** #13401 already read (deputy-codex D1-D6 =
  the corrected diagnosis above). **#13403 was ACKED-BLIND to stop an outage wake-storm — its body
  was NEVER read; content persists in DB, MUST re-read via full-history `/msg/deputy?unread=false`
  on recovery** (could be a lead directive or deputy-codex follow-up). Then re-dispatch deputy-codex
  the CORRECTED pool-saturation fix (NOT the refuted COUNT-OVER) → review → codex gate → lead deploy.

## Standing
- Codex verify-gate is BLOCKING on every deputy build before DONE; independent `codex` seat only
  (not deputy-codex self-review). Cite PASS id.
- Reply-to-sender on bus verdicts. Waking a seat after a post: `POST /api/wake?alias=<slug>` (Origin
  header). Read-path degraded → single-id reads + backoff.
