# SHIP REPORT — B4 / CORTEX_MULTI_MATTER_GATE_1

**Date:** 2026-04-29
**Builder:** B4 (`~/bm-b4`)
**Brief:** `briefs/BRIEF_CORTEX_MULTI_MATTER_GATE_1.md`
**Wave:** 1 / Track 2 (V3 rev 4 roadmap)
**Trigger class:** HIGH (cost-bearing gate change)
**Branch:** `b4/cortex-multi-matter-gate-1`
**Re-route:** Originally B3 (commit `9e0636b`); re-routed to B4 by Director 2026-04-29 — B3 busy.

---

## What shipped

`triggers/cortex_pre_review_gate.post_gate()` now whitelists by
`<vault>/wiki/matters/<slug>/cortex-config.md` presence. Without a config:
gate skips with info log, returns False — no Slack DM, no spend. With a
config: cost reflects per-matter `cost_estimate_dollars` from frontmatter
(default `$4.00` from `CORTEX_DEFAULT_COST_DOLLARS`).

### Files modified

- `triggers/cortex_pre_review_gate.py` — +95 LOC: 3 helpers (`_vault_root`,
  `matter_has_cortex_config`, `_read_cost_estimate`) + module constant
  `DEFAULT_COST_ESTIMATE_DOLLARS` + `post_gate` whitelist insertion + dynamic
  `${cost:.2f}` substitution.
- `tests/test_cortex_pre_review_gate.py` — +153 LOC: Tests 11-17 (7 new) +
  Test 10 minor adjust to set `BAKER_VAULT_PATH` + write `oskolkov/cortex-config.md`
  so the test reaches the Slack post path through the new whitelist.

### File 2 verdict — `triggers/cortex_pipeline.py` UNTOUCHED

The brief asked the builder to judge whether `maybe_trigger_cortex` needs an
explicit early-return for the no-config case. **Verdict: no change needed.**

Walk-through of the existing branch in `triggers/cortex_pipeline.py:64-92`
under the new behaviour, no-config matter:

1. `posted = post_gate(...)` → returns `False` (new whitelist branch fires
   BEFORE the secret check; logs `gate skipped — matter=… has no cortex-config.md`).
2. `if posted:` → False, skip.
3. `if already_decided(signal_id):` → `None` for a fresh no-config signal
   → skip.
4. `if _secret() is None:` → in production secret IS set, so this is
   False. Falls through to the `else` branch.
5. `else:` → `logger.warning("post_gate returned False with secret set; skipping cycle (no runaway). signal_id=%s", signal_id)` and `return`.

Net: **no Slack post, no cycle fire, no spend.** Existing logic correctly
handles the new no-config skip without modification. Adding a redundant
explicit early-return would duplicate the warning log and add code for no
behavioural gain.

Edge case (kill-switch path, gate disabled by removing secret OR setting
`CORTEX_GATE_ENABLED=false`): direct-fire is the documented pre-existing
fallback. Brief explicitly notes: *"caller falls through (legacy direct-fire
still respects `CORTEX_LIVE_PIPELINE` so this stays safe)."* Out of scope.

---

## QC outputs (all 6)

### 1. py_compile clean

```
$ python3 -c "import py_compile; py_compile.compile('triggers/cortex_pre_review_gate.py', doraise=True)"
OK
$ python3 -c "import py_compile; py_compile.compile('tests/test_cortex_pre_review_gate.py', doraise=True)"
OK
```

### 2. Full gate suite — 17/17 PASS

```
$ .venv-b3/bin/pytest tests/test_cortex_pre_review_gate.py -v
17 passed, 5 warnings in 1.39s
```

(Baseline pre-change confirmed as 10/10 PASS via the same harness; no
existing tests regressed.)

### 3. Regression — pipeline + dispatch suites PASS

```
$ .venv-b3/bin/pytest tests/test_alerts_to_signal_cortex_dispatch.py \
                     tests/test_pipeline_tick.py \
                     tests/test_bridge_pipeline_integration.py \
                     tests/test_cortex_slack_interactivity.py \
                     tests/test_cortex_trigger_endpoint.py -v
78 passed, 6 skipped, 6 warnings in 1.30s
```

(Brief named `tests/test_cortex_pipeline.py`; that file does not exist in
this repo — verified `ls tests/`. Substituted the closest dispatch / pipeline /
gate-adjacent suites; all green.)

### 4. Singleton CI guard — clean

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

### 5. Test 10 unfurl=False — STILL GREEN (no regression on contract)

```
$ .venv-b3/bin/pytest tests/test_cortex_pre_review_gate.py::test_post_gate_disables_slack_unfurl -v
1 passed in 0.02s
```

Test 10 still asserts `unfurl_links is False` AND `unfurl_media is False`.
The PR #66+#75 unfurl-suppression contract is preserved verbatim.

### 6. Contract-unchanged confirmation

- `_secret()` — body unchanged (env read; `len >= 32` floor preserved).
- `sign_token` / `verify_token` — bodies unchanged (HMAC-SHA256, b64url
  rstrip `=`, constant-time `compare_digest`, action whitelist
  `{approve, skip}`, expired check). Tests 1-5 still PASS.
- `already_decided` — body unchanged. Test 6 still PASS.
- `record_decision` — body unchanged (atomic `INSERT … SELECT WHERE NOT
  EXISTS … RETURNING id`, `json.dumps` payload, full PR #75 hardening
  intact). Tests 8 & 9 still PASS — atomic claim + race-loser-no-fire.
- Slack `unfurl_links=False` / `unfurl_media=False` — kwargs unchanged.
  Test 10 still PASS.

---

## Behaviour summary

| Matter | `cortex-config.md` | Behaviour |
|---|---|---|
| `oskolkov` (AO) | exists ✅ | gate fires; cost from frontmatter (or default `$4.00`) |
| `hagenauer-rg7` | absent (Track 3 lands it) | log-skip, no Slack DM, no spend |
| `kitzbuhel-six-senses` | absent | log-skip, no Slack DM, no spend |
| `nvidia-corinthia` | absent (Track 4 lands it) | log-skip, no Slack DM, no spend |
| `movie` | absent | log-skip, no Slack DM, no spend |

Once Tracks 3 & 4 land their respective `cortex-config.md` seeds in the
baker-vault repo, the gate accepts those matters automatically (no code
change required on this side).

## Lane discipline

- ✅ `outputs/dashboard.py` — UNTOUCHED (Track 1 / B1 lane).
- ✅ `orchestrator/cortex_runner.py` — UNTOUCHED.
- ✅ `kbl/bridge/alerts_to_signal.py` — UNTOUCHED.
- ✅ `baker-vault/slugs.yml` — UNTOUCHED (separate repo).
- ✅ No new env var beyond `CORTEX_DEFAULT_COST_DOLLARS` (optional, default `4.0`).
- ✅ No YAML import added (line-based frontmatter parse per brief).
- ✅ Frontmatter content beyond `cost_estimate_dollars` NEVER logged.

---

## Review path

Tier A — HIGH. PR opens → B1 formal section-by-section review → AI Head A
`/security-review` + structural → dual-clear auto-merge per `_ops/processes/b-code-dispatch-coordination.md`.

## Post-deploy verification (AI Head A — when DRY_RUN clears)

1. Confirm `BAKER_VAULT_PATH` set on Render to baker-vault-mirror checkout.
2. Insert fake `oskolkov` `signal_queue` row → expect Slack DM with
   `$X.XX` matching the matter's frontmatter (currently `$4.00` default).
3. Insert fake `kitzbuhel-six-senses` (config-less) row → expect NO Slack
   DM; logs show `gate skipped — matter=kitzbuhel-six-senses has no cortex-config.md`.
4. After Track 3 lands `hagenauer-rg7/cortex-config.md`, repeat with a
   `hagenauer-rg7` signal → expect Slack DM with the new matter's cost.
5. Audit:
   ```sql
   SELECT action_type, target_task_id, payload, created_at
   FROM baker_actions
   WHERE action_type LIKE 'cortex:gate:%'
     AND created_at > NOW() - INTERVAL '1 hour'
   ORDER BY created_at DESC LIMIT 10;
   ```
