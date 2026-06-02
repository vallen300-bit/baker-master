# CODE_1_PENDING — AUTOWAKE_MASTER_KILLSWITCH_1

status: COMPLETE
completed: 2026-06-02 — PR #52 merged 611349d; G0 codex (#1547+#1577) + G1 lead + G2 security-review (7 dims PASS) + post-deploy AC PASS (b1 #1588: KILLED suppresses + audits master_disabled, ENABLED fires; env-armed). Loop guardrail #2 LIVE. Spec writeback done (baker-vault 52a7673).
dispatched_by: lead
ship-report recipient: lead
repo: brisen-lab (your brisen-lab checkout, e.g. ~/bm-b1-brisen-lab)
task class: production implementation (daemon + dashboard UI)
gate plan: G0 codex (brief PASS, #1547) → G1 lead static → G2 security-review → G3 architect/code-reviewer
bus topics: ship/autowake-master-killswitch-1

## Context

Canonical brief (READ IN FULL FIRST): `~/baker-vault/_ops/briefs/BRIEF_AUTOWAKE_MASTER_KILLSWITCH_1.md` (committed 85af10e, codex G0 PASS #1547).

Build guardrail #2 of the ratified Autonomous Delegated Loop: a one-click, runtime, persisted master kill switch for autonomous bus-arrival wakes. Four of five guardrails already live in `BUS_AUTOWAKE_CONTAINMENT_1` — do NOT rebuild them. This adds only the master kill switch.

## Problem

Autonomous bus-arrival wakes can only be master-disabled via env var `BRISEN_LAB_AUTOWAKE_ENABLED` + a Render redeploy (Tier-B, slow). Need a dashboard one-click master kill, persisted so a redeploy can't silently re-enable autonomy.

## Files Modified

(per brief §Stable Paths) — `bus.py` (`_master_autowake_enabled()` + gate the auto-wake fire + audit `master_disabled`), `app.py` (`POST /api/autowake/master` origin-gated + `master_enabled` in `/api/wake_health`), `db.py` (bootstrap `brisen_lab_settings` table), `static/{index.html,app.js,styles.css}` (toggle UI + cache-bust), `tests/`.

Do NOT touch: existing containment primitives (rate cap, loop detector, env per-slug disable).

## Verification

Per brief §Verification + §Quality Checkpoints. Literal `pytest` output mandatory. Emit `POST_DEPLOY_AC_VERDICT v1` after the live-dashboard post-deploy check (Lesson #84 — real surface, not hand-run osascript).

## Quality Checkpoints

The load-bearing semantics (do NOT get these wrong — codex G0 blocker was here):
1. **Fail-SAFE precedence at hook time:** env `!= "true"` → disabled (hard backstop, no DB read); env `== "true"` → DB flag (off → disabled; on/missing-but-read-ok → enabled; **DB read FAILS → FAIL CLOSED disabled + log loud**). Never re-enable on a DB blip.
2. **Persisted** in `brisen_lab_settings`; in-memory cache ≤5s TTL allowed BUT **POST setter invalidates/updates cache before returning** so a kill takes effect on the very next hook call.
3. **Master gate placed BEFORE** per-slug/rate/loop checks in the auto-wake hook.
4. **Autonomous-only:** master-off must NOT block a manual `/api/wake` Director click.
5. Origin-gated like `/api/wake`; G2 reviews spoof risk.
6. Test AC (a)-(g) per brief — all literal pytest.

## Constraints

All DB calls in try/except with `conn.rollback()`. Fault-tolerant. No `--no-verify`. No secrets. Bootstrap table only (no migration runner). Ship report answers the done rubric (not just "tests pass") + carries the POST_DEPLOY_AC_VERDICT.
