# BUS_CONGESTION_SOAK_CLOSEOUT_1 — Soak + POST_DEPLOY_AC_VERDICT

- **Date:** 2026-07-21
- **Seat:** B1
- **Dispatched by:** lead (file-drop `CODE_1_PENDING.md`, brief_id BUS_CONGESTION_SOAK_CLOSEOUT_1)
- **Repo/surface:** brisen-lab (https://brisen-lab.onrender.com)
- **Task class:** verification (soak + AC verdict; no code build)

## Deploy tip confirmed
- `GET /healthz` → `commit: a55a6c5` (the fresh-conn/probe-budget killer fix). ✅ matches brief tip.
- Pool config live: every soak sample + post-soak `/api/v2/pool_stats` show `maxconn=40`
  → `BRISEN_LAB_POOL_MINCONN=40` (== maxconn) deploy is live. ✅

## 30-min soak (12 samples, 14:50:27Z → 15:20:44Z, SOAK_COMPLETE)

| metric | observed across window |
|---|---|
| `503_1h` (all causes) | **0** in every sample — acquire_timeout=0, stale_probe_budget=0, all_stale=0, other=0 |
| pool used / 40 | 0–25 (free 15–40); never saturated |
| db_gate permits | 18–40 available |
| `wait_avg` | **0.005 ms** constant (from 15,903 ms pre-fix) |
| `wait_max` | ≤ 1 ms |
| acquisitions (`acq`) | 1,498 → 17,753 = **16,255 in ~30.3 min ≈ 32,200/hr** |

**Load vs baseline:** the soak sustained ≈32,200 pool acquisitions/hr — well above the
5,311/hr congestion baseline (#14402/#14407) — with **zero** congestion 503s and sub-ms
gate waits. The self-sustaining 503 storm (root: probe budget armed before acquire; fresh
Neon conns idle=inf → always probed → discarded → 503) is eliminated at the code tip
`a55a6c5`, and the minconn=40 change removed the 33–40 churn band (#14716).

Post-soak authed `/api/v2/pool_stats`: `pool{maxconn:40,used:1,free:39}`,
`db_gate{waited_count:0, wait_avg_ms:0.005, wait_max_ms:0.605}`, `bus_503_rate_1h{count:0}`.

## POST_DEPLOY_AC_VERDICT v1
```
POST_DEPLOY_AC_VERDICT v1
brief: BUS_CONGESTION_SOAK_CLOSEOUT_1
task_class: other
commit: a55a6c5
deploy: env BRISEN_LAB_POOL_MINCONN=40 (live, maxconn=40 confirmed in pool_stats)
surface_checked: brisen-lab /healthz + /api/v2/pool_stats (12-sample 30-min soak)
ac_result: PASS
evidence: 503_1h=0 all causes across 12 samples; wait_avg 0.005ms (from 15,903ms); pool 0-25/40 never saturated; ~32,200 acq/hr sustained > 5,311/hr baseline; post-soak pool_stats bus_503_rate_1h.count=0
done_state: DONE
writeback: complete
next_action: none (PR #170 DIAG_2 remains open for codex gate — lead-owned merge)
```

## Task 2 — PR #170 (DIAG_2)
No action taken; stays open for codex gate per brief (#14619). No regressions in soak, so
no further code work. `probe_timing` is null in live `/api/v2/pool_stats` (expected — that
field ships only when #170 merges).

## Appendix — Body-null read path (task 3)
Repro matrix against live tip `a55a6c5` with my b1 terminal key:

| probe | result | reading |
|---|---|---|
| `GET /msg/14708` (bare) | `{"detail":"reader_slug_mismatch"}` | by-design fence (brief noted) |
| `GET /msg/b1/14708` (my slug + my key) | **full body returned** (topic `ship/bus-congestion-keepalive-fix-1`, ~700-char body, `acked:true`) | per-message read path is **healthy — body NOT null** |
| `GET /msg/b1/14716` (my own sent msg) | `{"detail":"not_recipient"}` | correct — b1 was sender, not recipient |
| `GET /inbox/b1` (LIST) | `count: 0` (all acked) | LIST empty-body-by-design; no messages to render |

**Conclusion: NO read-path bug.** The earlier "bus bodies unreadable b1-side" (#14716)
was **storm-time mid-insert body loss**, self-documented by msg 14708 itself:
*"RESEND of #14643 (its body was lost to the storm mid-insert)."* Post-fix, per-message
reads with correct slug+key return full bodies. Not brief-worthy — no new bug.
