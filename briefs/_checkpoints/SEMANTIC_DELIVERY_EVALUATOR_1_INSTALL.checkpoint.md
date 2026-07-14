# CHECKPOINT — SEMANTIC_DELIVERY_EVALUATOR_1 (install/enforce phase, Option 2)

attempt: 1
seat: b2
branch: b2/semantic-delivery-evaluator-1 (brisen-lab, in ~/bm-b2/brisen-lab), off main @4f77475 (post-#136 merge)
created: 2026-07-14
updated: 2026-07-14

## Brief id
SEMANTIC_DELIVERY_EVALUATOR_1 — install/enforce phase. Code arc (PR #136) MERGED @4f77475.
Lead ruling #10915 (acked): OPTION 2 — server-side eval endpoint + thin custodian poller.
Reply topic: case-one/semantic-evaluator-status. Dispatcher: lead. Gate: G1 -> codex -> lead merge.

## RATIFIED DESIGN (lead #10915) — build this, no deviation
(a) Auth-gated READ-ONLY endpoint on the Render app (brisen-lab app.py) returning the evaluator
    verdict JSON. REUSE the evaluator module server-side, NO logic fork.
    - Route: GET /api/semantic_delivery  (JSONResponse of the verdict dict).
    - Auth: TERMINAL-KEY CLASS, NEVER unauthenticated. Do NOT reuse _bus_health_access_ok as-is
      (it allows same-origin browser WITHOUT a key). Write a strict gate: require
      auth_lab.resolve_terminal_key(X-Terminal-Key) -> slug (or Director), else 401. No browser bypass.
    - Degraded DB -> HONEST not-ok verdict (db_unreachable / db_evidence_incomplete), NEVER 200-empty.
      Mirror the CLI _run fail-loud path EXACTLY (reuse sde.SCHEMA / sde.iso / sde.gather_evidence /
      sde.evaluate).
(b) Thin custodian poller mirroring scripts/install_arm_cadence_job.sh:
    - fetch GET /api/semantic_delivery WITH X-Terminal-Key -> write ~/.brisen-lab/arm-alarm/markers/
      semantic.json ATOMICALLY (tmp+rename). Marker contract (b4 #10634, load-bearing): schema
      (startswith semantic_delivery_verdict_v1), evaluated_at (ISO8601), semantic_ok (bool).
    - fetch-fail -> DO NOT overwrite marker: stale marker ages out and pages (correct posture).
    - new script scripts/arm_semantic_poll.sh + scripts/install_arm_semantic_job.sh +
      scripts/launchd/com.baker.arm-semantic.plist. Mirror arm-cadence installer (deploy to
      "$HOME/Library/Application Support/baker", --check subcommand, KeepAlive, StartInterval).
      Poller NEEDS a terminal key -> inject like install_lease_heartbeat_emitter.sh (env, chmod 600,
      key via brisen_lab_terminal_key.sh). Interval: mirror cadence 1800s (or ARM_ALARM_SEMANTIC_MAX_AGE_S
      93600 informs staleness; poll well under that — 1800s fine).
- ENFORCE stays 0 until poller live + marker fresh. THEN install receipt to lead -> lead GOes the flip.
  DO NOT flip ARM_ALARM_SEMANTIC_ENFORCE=1 yourself (production alarm = lead's explicit GO).

## Server-side evidence mapping (all verified this session — no re-derivation needed)
sde.gather_evidence(conn, now, sla_s, receipt_epoch_env, canary_epoch_env, bus_health,
                    cadence_snapshot, canary_marker, prev_watermark):
- conn: get_conn() (app has DATABASE_URL). now: datetime.now(utc). sla_s: env BRISEN_LAB_DELIVERY_SLA_S/3600.
- receipt_epoch_env: os.environ BRISEN_LAB_RECEIPT_EPOCH. canary_epoch_env: os.environ BRISEN_LAB_CANARY_EPOCH.
- bus_health: server-internal {"seats":[{"seat":..,"oldest_age_s":..}]}. sde.oldest_unacked_from_bus_health
  only reads seats[].oldest_age_s. REUSE the seat computation /api/bus_health serves (bus_health_api._read
  in app.py ~L1937+). OPEN MICRO-DECISION: factor the seat SQL into a helper vs a small dedicated
  "MAX oldest unacked age per seat" query. Keep it read-only, canary-slug excluded (_CANARY_SLUG).
- cadence_snapshot: None server-side (custodian's cadence ok=true claim is NOT uploaded to a read-only GET;
  reported_ok -> None -> ok_true_contradiction check records "skipped". HONEST + no logic fork). Note this
  in the endpoint docstring + report so lead knows the reported_ok contradiction is a custodian-only check.
- canary_marker: from canary.latest_run_sync() (DB projection, server-side, NO custodian marker dep):
  {"checked_at": cr["started_at"], "ok": (cr["verdict"] == "pass")}  (verdict vocab: pass|fail, canary.py:212).
  None if no run yet -> evaluator handles absent canary via canary_epoch gate.
- prev_watermark: None (stateless endpoint -> monotonicity treated as first-run; STALENESS still enforced).
  Known limitation: run-to-run watermark REGRESSION detection is lost server-side (acceptable; staleness is
  the load-bearing signal). Note in report.

## Test plan (G1)
- tests_unit (pure, no DB): already 33/33 green post-#136. Add server-verdict-shape + fail-loud tests
  by calling the SAME sde funcs the endpoint calls (no DB): assert db-error evidence -> semantic_ok False;
  canary mapping helper (verdict=fail -> ok False). Keep endpoint auth test with a FastAPI TestClient if
  the suite already uses one (check tests/ for TestClient pattern before adding).
- Poller: bash -n syntax + a --check drift path mirroring arm_cadence installer's --check.

## What's DONE
- Fix arc PR #136 merged @4f77475 (cadence-snapshot wrapper unwrap, codex PASS #10878, 33/33).
- Escalation #10909 -> lead ruled Option 2 #10915 (acked).
- (a) ENDPOINT BUILT: brisen-lab GET /api/semantic_delivery (app.py, after bus_health_api) — strict
  terminal-key gate + _semantic_seat_oldest_ages() helper + reuse of sde.gather_evidence/evaluate +
  db_unreachable fail-loud fallback. Branch b2/semantic-delivery-endpoint-1 off origin/main e488f9d.
  PR brisen-lab #139 OPEN. tests_unit 35/35 (+2). app.py compiles.
- (b) CUSTODIAN SCRIPTS BUILT (baker-master repo ~/bm-b2/scripts): arm_semantic_poll.sh +
  install_arm_semantic_job.sh + launchd/com.baker.arm-semantic.plist. bash -n clean, plist parses,
  dry-run install OK. Poller: fetch authed endpoint -> atomic write semantic.json; fetch-fail = NO
  overwrite (stale ages out -> pages). Installer mirrors arm-cadence + lease-emitter key injection
  (chmod 600 plist). Seat identity default = 'daemon' (ARM_SEMANTIC_SEAT override) — CONFIG DECISION
  flagged to lead (reversible).
- Repo boundary CONFIRMED: endpoint = brisen-lab (gated PR #139); ARM scripts = baker-master (ops
  tooling, committed on work branch b2/semantic-delivery-evaluator-1, NOT the brisen-lab gate).

## Next concrete step
1. Request codex gate on brisen-lab PR #139 (hard-refresh main); point codex at the 3 baker-master
   script paths too. On PASS -> lead merges #139.
2. After #139 merge + Render deploy: run install_arm_semantic_job.sh locally (resolves daemon key,
   loads launchd job), let one poll fire, prove ~/.brisen-lab/arm-alarm/markers/semantic.json fresh
   (evaluated_at recent, semantic_ok present) -> send install receipt + marker-freshness proof to lead.
3. Lead GOes ARM_ALARM_SEMANTIC_ENFORCE=1 (NOT b2 — production alarm = lead's explicit GO).

## Claim discipline
Successor claims by the attempt:-bump commit on THIS checkpoint. If attempt already bumped, stand down.
At attempt >= 3, stop resuming + escalate to lead with this path + last error.
