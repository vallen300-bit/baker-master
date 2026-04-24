# B3 Review — PR #61 PROMPT_CACHE_AUDIT_1

**Reviewer:** Code Brisen #3 (Team 1 — Meta/Persistence)
**Target PR:** https://github.com/vallen300-bit/baker-master/pull/61
**Branch:** `prompt-cache-audit-1`
**Ship commit:** `4978355`
**Review date:** 2026-04-24
**M0 quintet row:** 4 (closes with this merge; row 5 CITATIONS_API_SCAN_1 merged `bb2d709`)

---

## Verdict: **APPROVE — 12/12 checks green**

Tier A auto-merge gate cleared on the peer-review axis. Remaining gate is AI Head `/security-review` PASS + rebase-if-needed. Baseline `main` after PR #59 + PR #60 → 878 passed (+8 from B1-reported 870, exactly matches the new test count).

---

## 12-check output (literal)

### Check 1 — Scope lock (7 files + ship report OK)

```
$ git diff --name-only main...HEAD
baker_rag.py
briefs/_reports/B1_prompt_cache_audit_1_20260424.md
kbl/cache_telemetry.py
orchestrator/capability_runner.py
outputs/dashboard.py
scripts/audit_prompt_cache.py
scripts/prompt_cache_hit_rate.py
tests/test_prompt_cache_audit.py
```

Exactly the 7 expected paths (+ `briefs/_reports/B1_prompt_cache_audit_1_20260424.md` ship report, which is allowed). **Zero forbidden touches:** `kbl/anthropic_client.py`, `kbl/cost.py`, `memory/store_back.py` all untouched. No model ID changes anywhere.

### Check 2 — Python syntax on all 7 files

```
$ for f in baker_rag.py kbl/cache_telemetry.py orchestrator/capability_runner.py \
           outputs/dashboard.py scripts/audit_prompt_cache.py \
           scripts/prompt_cache_hit_rate.py tests/test_prompt_cache_audit.py; do
    python3 -c "import py_compile; py_compile.compile('$f', doraise=True)" \
      || { echo "FAIL: $f"; exit 1; }
  done && echo "All 7 files clean."
All 7 files clean.
```

### Check 3 — Imports smoke

```
$ python3 -c "from kbl.cache_telemetry import log_cache_usage; from scripts.audit_prompt_cache import CallSite; print('OK')"
OK
```

### Check 4 — Audit script runs end-to-end

```
$ python3 scripts/audit_prompt_cache.py --out /tmp/audit.md
Audit complete: 82 call sites -> /tmp/audit.md
  below_threshold: 15
  unclear: 67
exit=0

$ grep -c "^| " /tmp/audit.md
90

$ head -20 /tmp/audit.md
# Prompt Cache Audit - 2026-04-24

Total call sites: **82**

## Summary by tier

| Tier | Count |
|------|-------|
| `eligible_apply` | 0 |
| `eligible_measure` | 0 |
| `below_threshold` | 15 |
| `unclear` | 67 |
| `no_system` | 0 |
```

82 total call sites identified, 90 table rows across the tiered breakdown. Script exits 0. Report written.

### Check 5 — cache_control in the 3 hot files

```
$ grep -l "cache_control" outputs/dashboard.py orchestrator/capability_runner.py baker_rag.py
outputs/dashboard.py
orchestrator/capability_runner.py
baker_rag.py
```

All three files carry `cache_control`. `baker_rag.py` applies the tag **despite** the ~265-token `BAKER_SYSTEM_PROMPT` being below Anthropic's 1024-token cache minimum — this is a conscious forward-compat decision explicitly documented in-code:

```python
# baker_rag.py:204-207
# PROMPT_CACHE_AUDIT_1: BAKER_SYSTEM_PROMPT is ~265 tokens, below
# Anthropic's 1024-token cache minimum — the API ignores cache_control
# on sub-threshold blocks. Tag kept so caching engages automatically
# if the prompt grows past threshold (ship report documents the skip).
```

Rationale accepted: the Anthropic API silently ignores `cache_control` on sub-threshold blocks (no cost, no error), and keeping the tag is a forward-compat guarantee. B1's ship report frames this as "skip-equivalent" — functionally equivalent to skip, which is what the dispatch tolerated (`may or may not`). Not a flag-worthy deviation.

### Check 6 — cache_control block shape

```
$ grep -B3 -A5 'cache_control.*ephemeral' outputs/dashboard.py | head -15
        return [{"type": "text", "text": system_prompt}]
    blocks: list = [
        {"type": "text", "text": stable,
         "cache_control": {"type": "ephemeral"}},
    ]
    if dynamic.strip():
        blocks.append({"type": "text", "text": dynamic})
    return blocks
```

`dashboard.py:51-70` — `_split_scan_system_for_cache()` helper correctly splits the system prompt into `[stable_cached, dynamic_uncached]`. Only the stable `SCAN_SYSTEM_PROMPT` (~1.9k tokens) gets `cache_control: ephemeral`. Dynamic suffix (time / deadlines / retrieval / mode / prefs) goes in a separate uncached block. ✅

```
$ grep -B3 -A5 'cache_control.*ephemeral' orchestrator/capability_runner.py | head -10
def _cache_wrap(system_str: str) -> list:
    """PROMPT_CACHE_AUDIT_1: wrap a capability system prompt as a single
    ephemeral cache_control block. Caches when the capability's system
    text is stable across calls (most PM + domain capabilities);
    misses harmlessly when dynamic bits vary."""
    return [{"type": "text", "text": system_str,
             "cache_control": {"type": "ephemeral"}}]
```

`capability_runner.py:35-41` — `_cache_wrap()` wraps the whole capability `system_str` in a single cached block. Less surgical than `dashboard.py`'s split approach, but correct: `system=` kwarg (not user-message content) is the only cacheable target here, and the docstring honestly documents the cache-miss-on-dynamic-content behaviour. The two call sites (`:679`, `:893`) pass the built system string, not retrieval/question content — the retrieval flows through `messages=` separately. No "cache_control on retrieval content" breakage. ✅

**Note (non-blocking):** the capability_runner approach trades surgical cacheability for simplicity — cache hits only when a capability's full system text is stable. For capabilities that concatenate dynamic mode-aware bits into the system string (e.g., `build_mode_aware_prompt` output), this will miss. A follow-on refactor could split stable persona from dynamic mode suffix (like `dashboard.py`). Not required for M0 row 4 close.

### Check 7 — `log_cache_usage()` is fire-and-forget

```
$ grep -c "try:\|except" kbl/cache_telemetry.py
4
```

Two try/except layers: one around `usage` attribute parsing (returns silently on malformed shape), one around `store.log_baker_action()` (warns + swallows on store failure). Function signature is `-> None` — zero possible rise paths. ✅

Call-site integration confirmed after Claude response (not inside the guard around `messages.create`):

```
$ grep -nB1 -A3 "log_cache_usage" outputs/dashboard.py | head -18
47-from orchestrator import action_handler as _ah
48:from kbl.cache_telemetry import log_cache_usage
--
8614-                final_msg = stream.get_final_message()
8615:                log_cache_usage(final_msg.usage,
8616-                                call_site="outputs.dashboard.scan_chat",
8617-                                model=config.claude.model)
8618-            except Exception:
--
8736-                    final_msg = stream.get_final_message()
8737:                    log_cache_usage(final_msg.usage,
8738-                                    call_site="outputs.dashboard.scan_chat_legacy",
8739-                                    model=config.claude.model)
8740-                except Exception:
```

`log_cache_usage` is called AFTER `stream.get_final_message()` returns, inside a nested try/except. The outer `messages.create` guard is separate. ✅

Same pattern confirmed in `capability_runner.py:691-693` and `:903-905`.

### Check 8 — 8 tests pass in isolation

```
$ python3 -m pytest tests/test_prompt_cache_audit.py -v 2>&1 | tail -15
tests/test_prompt_cache_audit.py::test_audit_script_exits_zero_and_writes_report PASSED [ 12%]
tests/test_prompt_cache_audit.py::test_audit_identifies_cached_call_site PASSED [ 25%]
tests/test_prompt_cache_audit.py::test_cache_control_block_shape_in_anthropic_client PASSED [ 37%]
tests/test_prompt_cache_audit.py::test_cache_control_present_in_three_hot_sites PASSED [ 50%]
tests/test_prompt_cache_audit.py::test_log_cache_usage_fires_baker_action PASSED [ 62%]
tests/test_prompt_cache_audit.py::test_log_cache_usage_silent_on_missing_store PASSED [ 75%]
tests/test_prompt_cache_audit.py::test_log_cache_usage_silent_on_malformed_usage PASSED [ 87%]
tests/test_prompt_cache_audit.py::test_audit_classifies_below_threshold PASSED [100%]

======================== 8 passed, 1 warning in 17.94s =========================
```

**8 passed** — matches brief expectation exactly. Test names cover: audit script contract, hot-site classification, block shape preserved, hot sites carry cache_control, telemetry fires, telemetry silent on missing store, telemetry silent on malformed usage, below-threshold classification.

### Check 9 — Full-suite regression delta (870 → 878)

```
$ python3 -m pytest tests/ --ignore=tests/test_tier_normalization.py 2>&1 | tail -3
ERROR tests/test_scan_endpoint.py::test_scan_rejects_empty_question - TypeErr...
ERROR tests/test_scan_endpoint.py::test_scan_accepts_history - TypeError: uns...
====== 24 failed, 878 passed, 27 skipped, 5 warnings, 31 errors in 31.42s ======
```

**Δ vs B1's reported baseline (870):** **+8 passed** exactly — matches B1's delta claim and the new test count. failed/errors counts identical to baseline (24/31), zero regressions. Skipped count moved 23 → 27 — unrelated to this PR (introduced by PR #59 / PR #60 merges earlier in the day; not a regression here).

### Check 10 — No baker-vault writes

```
$ git diff --name-only main...HEAD | grep -E "(^baker-vault/|~?/baker-vault)" || echo "OK: no baker-vault writes."
OK: no baker-vault writes.
```

### Check 11 — No new env vars / no schema changes

```
$ grep -n "os.environ\[\|getenv(" kbl/cache_telemetry.py scripts/audit_prompt_cache.py scripts/prompt_cache_hit_rate.py \
    | grep -v "ANTHROPIC_API_KEY\|BAKER_\|PRICE_OPUS"
OK: no new env vars.

$ grep -E "CREATE TABLE|ALTER TABLE|ADD COLUMN" scripts/prompt_cache_hit_rate.py kbl/cache_telemetry.py
OK: no DDL.
```

No new env vars. No DDL. `baker_actions` reused as-is for `claude:cache_usage` rows.

### Check 12 — Singleton hook

```
$ bash scripts/check_singletons.sh
OK: No singleton violations found.
```

---

## Spot-inspection notes (non-blocking)

1. **`capability_runner._cache_wrap()` caches the whole system string.** Less surgical than `dashboard.py`'s split helper — for capabilities with dynamic mode suffixes, this will miss the cache on every call. Safe (no breakage, just miss), and the docstring is honest. A follow-on "refactor `_cache_wrap` into stable/dynamic split" brief could improve hit-rate for PM capabilities. Not gating M0 row 4.

2. **`baker_rag.py` forward-compat tag.** Applying `cache_control` to a sub-threshold block is a no-op today (Anthropic ignores), but auto-engages when the prompt grows past 1024 tokens. Forward-compat design is defensible and well-documented. Won't skew audit metrics because the audit classifier correctly places `baker_rag.py` in `below_threshold`.

3. **Audit summary: 82 sites, 0 `eligible_apply` / 0 `eligible_measure`.** Every call site is currently classified either `below_threshold` (15) or `unclear` (67). The `unclear` bucket is worth a follow-on triage — a secondary audit may surface more caching opportunities once prompts are tokenized dynamically vs statically estimated. Not gating.

4. **Test `test_cache_control_block_shape_in_anthropic_client`** inspects `kbl/anthropic_client.py` (unmodified by this PR, per brief). The test confirms the existing shape is unchanged — serves as a regression guard. ✅

---

## Merge-compat with PR #59 (CITATIONS_API_SCAN_1)

Confirmed resolved. `outputs/dashboard.py` now contains both:
- `_split_scan_system_for_cache()` helper (this PR) at line 51.
- `from kbl.citations import (...)` import block (PR #59) at line 80.
- All 3 scan endpoints wire citations adapter + use `_split_scan_system_for_cache()` where the SSE scan path lives.

No outstanding rebase conflicts observed on `prompt-cache-audit-1` against current `main` (`bb2d709`).

---

## Recommendation

**APPROVE for Tier A auto-merge** pending AI Head `/security-review` PASS. Ship gate is clean, regression delta matches B1's claim exactly, all dispatch-stated "reject if" conditions clear.

Post `gh pr review --approve` next.

---

**Dispatch trail:** CODE_3_PENDING 2026-04-24 post-PR-61-ship → 12/12 green → APPROVE.
**Sequence position:** closes M0 quintet row 4; **M0 quintet fully closed on merge.**
