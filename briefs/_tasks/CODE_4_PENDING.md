# CODE_4 — DISPATCH (CORTEX_MULTI_MATTER_GATE_1)

**Status:** PENDING — B4 build
**Brief:** `briefs/BRIEF_CORTEX_MULTI_MATTER_GATE_1.md`
**From:** AI Head A (cross-lane assist drafted by B1 per AI Head A request, 2026-04-29)
**Wave:** 1 / Track 2 (V3 rev 4 roadmap)
**Trigger class:** HIGH (cost-bearing gate change → RA-24 review required)
**Re-route:** Originally assigned to B3 (commit `9e0636b`); re-routed to B4 by Director 2026-04-29 — B3 busy.

**Prior CODE_4 task** AO_PM_EXTENSION_1 (2026-04-22) shipped historical. Mailbox overwrite per §3 hygiene; ship report preserved at `briefs/_reports/B4_AO_PM_EXTENSION_1_20260422.md`.

## Scope (TL;DR)

`triggers/cortex_pre_review_gate.py`:
1. Add `matter_has_cortex_config(matter_slug)` — checks `BAKER_VAULT_PATH/wiki/matters/<slug>/cortex-config.md`
2. Add `_read_cost_estimate(matter_slug)` — line-based frontmatter parse for `cost_estimate_dollars` (default `$4`)
3. `post_gate()` early-returns False when no config; Slack DM cost reflects frontmatter
4. 7 new tests (extend `tests/test_cortex_pre_review_gate.py` from 10 → 17)
5. Verify `triggers/cortex_pipeline.py` no-config path is safe (per builder judgment — see brief §File 2)

## Working dir

`~/bm-b4`

```bash
cd ~/bm-b4 && git checkout main && git pull -q
cat briefs/BRIEF_CORTEX_MULTI_MATTER_GATE_1.md
```

## Order of work

1. Read brief end-to-end
2. Baseline: `pytest tests/test_cortex_pre_review_gate.py -v` (10/10 PASS pre-change)
3. Implement helpers + `post_gate` diff
4. Add 7 tests; verify 17/17 PASS literal
5. `bash scripts/check_singletons.sh` clean
6. Regression: `pytest tests/test_cortex_pipeline.py tests/test_alerts_to_signal_cortex_dispatch.py -v` PASS
7. py_compile clean
8. Push to `b4/cortex-multi-matter-gate-1` branch + PR

## Pass criteria

- 17/17 gate tests PASS literal (Test 10 unfurl=False still green)
- HMAC + idempotency + record_decision contracts unchanged
- AO matter still gates (config exists); hagenauer-rg7 / kitzbuhel-six-senses signals would log-skip until Tracks 3/4 land their configs

## Lane rule

- **Out of scope:** `outputs/dashboard.py` (Brief 1 / Track 1 / B1 owns it — do not race)
- **Out of scope:** `orchestrator/cortex_runner.py`, `kbl/bridge/alerts_to_signal.py`

## Ship report target

`briefs/_reports/B4_cortex_multi_matter_gate_1_<YYYYMMDD>.md` — include all 6 QC outputs + `_secret`/`already_decided`/`record_decision` contract-unchanged confirmation + `triggers/cortex_pipeline.py` review note (modified or no-modification rationale).

## Review path (Tier A — HIGH)

PR opens → B1 formal section-by-section review → AI Head A `/security-review` + structural → Tier A auto-merge on dual clear.

## Coordination with parallel tracks

- **Track 1 (B1) — CORTEX_MANUAL_INVOKE_1:** independent file scope (`outputs/dashboard.py` + new module); zero overlap. Both can ship concurrently.
- **Tracks 3+4 (B2 App / AI Head 2 App) — `cortex-config.md` seeds:** baker-vault repo. After they land configs for `hagenauer-rg7` / `nvidia-corinthia`, the new gate whitelist will accept them automatically.

## Co-Authored-By

```
Co-authored-by: Code Brisen #4 <b4@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
