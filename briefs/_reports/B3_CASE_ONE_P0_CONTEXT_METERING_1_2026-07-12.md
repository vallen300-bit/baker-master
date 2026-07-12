# B3 SHIP REPORT — CASE_ONE_P0_CONTEXT_METERING_1

**Date:** 2026-07-12
**Brief:** `briefs/BRIEF_CASE_ONE_P0_CONTEXT_METERING_1.md` @c042fb81
**Dispatched by:** lead (#9722/#9727) · design ruled #9733 (Option B + B2)
**PRs:** baker-master #540 · brisen-lab #123 (branch `b3/case-one-p0-context-metering-1` in both)
**Gate:** lead reviews design+diff → non-author test-run → lead merges → deploy → deputy verifies live.

## Design decisions (ruled by lead #9733)
- **Option B** — advisory context-band store, SEPARATE from brisen-lab's TokenPressure enforcement meter (which auto-kills via Hermes). Reusing token_pressure would arm P2's kill loop early + conflate two meters. Two meters, not one.
- **B2 emit** — Stop hook writes a local band file; heartbeat carries it. Network I/O stays out of the hook (exit-0 contract). ≤45s staleness acceptable for advisory data.

## Done rubric — answered
1. **Single shared band computation, no drift** ✅ — `context_meter.compute` factored from the Stop hook; the hook calls it. Unit test proves hook≡module band on BOTH the measured-usage and bytes/4 fallback paths.
2. **Machine band field live in status posts** ✅ — Stop hook writes `{context_percent,band,measured,window_tokens,session_id}` to `~/forge-agent/context-band/<session_id>.json` (atomic, every band incl. ok); heartbeat-ticker carries it in `/api/heartbeat`; daemon ingests it.
3. **Universal seat wiring + fail-loud coverage audit** ✅ — `scripts/rollover_fleet.py audit|install`, enumerated from `SNAPSHOT_TERMINALS`. Audit is fail-loud (nonzero + names every gap); never silent-skips.
4. **Lifecycle exposes per-seat band queryable by dispatcher** ✅ — `brisen_lab_seat_context_band` + `GET /lifecycle/seats-over-band?band=hard` (advisory; stale>15min excluded; never triggers a roll).
5. **Live AC + `POST_DEPLOY_AC_VERDICT v1`** ⏳ **PENDING DEPLOY** — fresh-seat=ok / full-seat=hard behavior needs the code merged + deployed (Render baker-master + brisen-lab daemon). Gated post-merge per the gate plan; deputy verifies as bus-health owner.

## Live audit finding (P0-critical — validates brief Problem #2)
`rollover_fleet.py audit` → **7/21 pickers wired, 14 NOT** (exit 1):
- `NO_SETTINGS`: `~/baker-vault` (19 seats: CM-1..4, aid, ao/movie/bb/hag/brisen/origination desks, codex, codex-arch, deep55, ben, librarian, researcher, russo-ai), `~/bm-clerk` (clerk, clerk-haiku).
- `MISSING_HOOK`: every cowork App seat (AID/AO/ARM/BB/Hagenauer/Librarian/MOVIE/Origination/Researcher/Russo), `~/bm-designer`, `~/bm-publisher`.
- `WIRED`: bm-aihead1/2, bm-arm, bm-b1..4.

The fleet **sweep** (running `install` + distributing the hook script to each picker) is a deploy-step ops action, not auto-run from the build. Flagged to lead for the deploy step.

## Tests — literal runs
- **baker-master: 39 passed** (`test_worker_rollover.py` 19 unchanged + `test_context_meter.py` 12 + `test_rollover_fleet.py` 8). Includes the no-drift proof and the fail-loud audit assertions.
- **brisen-lab:** pure band-rank + guards verified directly (ok<soft<hard, unknown=-1, unknown-band short-circuits before any DB call); DB + heartbeat-ingest + route tests written, auto-skip locally without `TEST_DATABASE_URL` (repo convention — run under reviewer/CI test DB). brisen-lab has no CI, so the non-author test-run needs a test DB.

## Files
- baker-master: `.claude/hooks/context_meter.py` (new), `.claude/hooks/context-threshold-check.sh`, `scripts/forge-agent/heartbeat-ticker.sh`, `scripts/rollover_fleet.py` (new), `tests/test_context_meter.py` (new), `tests/test_rollover_fleet.py` (new).
- brisen-lab: `db.py`, `app.py`, `tests/conftest.py`, `tests/test_context_band_p0.py` (new).

## Notes for reviewer
- No DB columns added in baker-master. brisen-lab: new table only, via bootstrap `CREATE TABLE IF NOT EXISTS` (no ALTER on an applied table) — Lesson #50 clear.
- Migration-edit rules untouched. No secrets. Hooks not bypassed.
- Next lane after this closes: ITEM-10 PDF-extraction (deputy #9855), sequencing approved by lead #9889.
