---
role: B3
kind: review
brief: step6_frontmatter_yaml_escape_fix
pr: https://github.com/vallen300-bit/baker-master/pull/34
branch: step6-frontmatter-yaml-escape-fix-1
base: main
commits: [1767460, 16cf291]
ship_report: briefs/_reports/B2_step6_frontmatter_yaml_escape_fix_20260421.md
verdict: APPROVE
tier: A
date: 2026-04-21
tags: [step5, step6, frontmatter, yaml-escape, stub-emitter, cortex-t3-gate1, review]
---

# B3 — review of PR #34 `STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1`

**Verdict: APPROVE.** Tier A auto-merge greenlit. Zero blocking issues, zero gating nits. B2's scope deviation is correctly interpreted, the root-cause localization is accurate (Step 5 stubs, not Step 6 emitter), and the patch mirrors Step 6's canonical `yaml.safe_dump` call pattern exactly.

---

## Scope deviation — BLESSED

The brief pointed at Step 6's emitter and said "no touch to Step 5 logic". B2 instead fixed Step 5's two stub writers. **Correct call — the brief's pointer was off-by-one-step.**

**Independent verification of root-cause locality:**

1. Step 6's `_serialize_final_markdown` (line 526) already uses the canonical call:
   ```python
   yaml.safe_dump(dict(ordered), sort_keys=False, allow_unicode=True, default_flow_style=False)
   ```
   This is the *output* emitter for Gold-path final markdown, NOT the emitter for Step 5 stubs Step 6 receives as input.

2. Step 6's role on the stub path is **parsing**, not emitting: `_split_frontmatter` at line 290 calls `yaml.safe_load(raw_yaml)` and raises `FinalizationError("frontmatter YAML parse failed: …")` on malformed input. There is no Step 6 YAML emit between parse and validation that could be coerced to fix the bug.

3. Step 5's `_build_skip_inbox_stub` (pre-fix line 387) and `_build_stub_only_stub` (pre-fix line 411) compose YAML via raw f-string concat. The hard-coded skip-inbox title `"Layer 2 gate: matter not in current scope"` hits the parser mid-line, producing the exact reported error.

**Scope interpretation verdict:** B2 read "no touch to Step 5 logic" as "no touch to Step 5 business/routing logic". That's the right reading:

| Scope dimension | Pre-fix | Post-fix | Changed? |
|---|---|---|---|
| State flow (emit → decide → route) | Step 5 emits stub → routes via `step_5_decision` → Step 6 parses | Step 5 emits stub → routes via `step_5_decision` → Step 6 parses | No |
| Decision values (`SKIP_INBOX`, `STUB_ONLY`, `FULL_SYNTHESIS`, `CROSS_LINK_ONLY`) | unchanged | unchanged | No |
| Next-state transitions | `awaiting_opus → awaiting_finalize` | same | No |
| Dict shape (9 keys in fixed order: `title → voice → author → created → source_id → primary_matter → related_matters → vedana → status`) | same 9 keys, same order via f-string | same 9 keys, same order via `sort_keys=False` + dict literal | No (shape), No (order) |
| Dict values | same sources (`inputs.primary_matter`, `inputs.vedana or "routine"`, `_iso_utc_now()`, etc.) | same sources | No |
| Serialization mechanism | raw f-string concat (broken for YAML-special chars) | `yaml.safe_dump` (correct for all scalars) | **Yes** (intentional fix) |

Only the serialization mechanism changed. The `yaml.safe_dump` output is not *byte-identical* to the pre-fix f-string output for two fields:

- `created` field: pre-fix emitted unquoted (YAML parses as native datetime); post-fix emits quoted string (YAML parses as string; Pydantic `SilverFrontmatter.created: datetime` coerces from ISO-8601 string). Round-trip equivalent after Pydantic coercion.
- `related_matters` non-empty list: pre-fix inline `[a, b]`; post-fix block `- a\n- b`. Both valid YAML, both round-trip as `list[str]`.

Both deltas are **load-equivalent** (same Python object on `yaml.safe_load` + Pydantic coercion). No downstream consumer observes the raw text shape. B2's "byte-identical … only serialization changed" claim is correct on semantic grounds; the literal byte diff is confined to the YAML serialization of those two value classes, which is the intended change.

**Scope ruling: deviation accepted.** Fixing Step 6's non-existent emitter would have been impossible; the brief's pointer was off-target.

---

## Focus items — 7/7 green

### 1. ✅ Scope deviation bless (see above)

### 2. ✅ Root-cause correctness — independently confirmed

- Step 6's canonical `yaml.safe_dump` at `step6_finalize.py:526` verified. Args exactly as claimed: `sort_keys=False, allow_unicode=True, default_flow_style=False`.
- Step 5's pre-fix stub writers were raw f-string concat (can reproduce from `git diff main...HEAD -- kbl/steps/step5_opus.py`): `f"title: {title}\n"` etc. with hard-coded `"Layer 2 gate: matter not in current scope"` at the fixed line.
- Grepped `kbl/steps/` for f-string YAML fence patterns; exactly two matches (Step 5 post-fix line 408, Step 6 line 532), both wrapping pre-serialized `yaml.safe_dump` output. No surviving f-string-YAML-field concat in the steps pipeline.

### 3. ✅ Patch correctness — mirrors Step 6 call pattern

Step 5 `_dump_stub_frontmatter` (new, line 402-408):
```python
yaml_text = yaml.safe_dump(
    fm,
    sort_keys=False,
    allow_unicode=True,
    default_flow_style=False,
).strip()
return f"---\n{yaml_text}\n---\n"
```

Step 6 `_serialize_final_markdown` (line 526-532):
```python
yaml_text = yaml.safe_dump(
    dict(ordered),
    sort_keys=False,
    allow_unicode=True,
    default_flow_style=False,
).strip()
return f"---\n{yaml_text}\n---\n\n{doc.body.rstrip()}\n"
```

Args identical. Fence shape identical — Step 5 returns `---\nYAML\n---\n` from the helper, then appends the body with `f"{_dump_stub_frontmatter(fm)}\n{body}"` (the extra `\n` yields the `\n\n` separator Step 6 emits natively). Same on-disk shape.

Key order via `sort_keys=False` + dict literal ordering is preserved. Non-ASCII via `allow_unicode=True`. Block-style via `default_flow_style=False`. Every arg carries its intended contract.

The shared dict-builder `_build_stub_frontmatter_dict` is a clean refactor — eliminates field-list duplication between the two stub writers and makes `sort_keys=False` the single source of truth for order. Good factoring.

### 4. ✅ Regression tests — 4/4 solid

| Focus-4 requirement | Test function | Key assertions |
|---|---|---|
| (a) colon-in-title parse | `test_skip_inbox_stub_frontmatter_parses_cleanly_despite_colon_in_title` | `_yaml.safe_load` succeeds; `fm["title"] == "Layer 2 gate: matter not in current scope"` round-trips verbatim; `primary_matter is None` (Python None from YAML null), `related_matters == []`, body preserved |
| (b) pathological triage-summary scalars | `test_stub_only_stub_frontmatter_survives_pathological_triage_summary` | Hostile string: `'RE: meeting @ 14:00 — "urgent" #priority\n- item'`. Asserts title `[:60]` slice round-trips verbatim, related_matters list parses correctly, full hostile string appears in body |
| (c) field-order stability | `test_stub_frontmatter_field_order_is_stable` | Explicit `assert list(fm.keys()) == [9 keys in fixed order]` — would fail if anyone dropped `sort_keys=False` or reordered the dict literal |
| (d) end-to-end via Step 6's `_split_frontmatter` | `test_stub_parses_through_step6_split_frontmatter` | Imports Step 6's actual production function and runs it on a skip_inbox stub with the reported literal title. Exact regression gate against the reported field failure |

All 4 tests assert `yaml.safe_load` (or equivalent) succeeds AND dict shape matches expected. Non-trivial pass-checks: value equality on the `title` field (would fail on a pass-through stub that just strips frontmatter), list equality on `related_matters` (would fail on a stub that emits keys in wrong order), key-order equality (would fail on `sort_keys=True`), end-to-end via imported `_split_frontmatter` (exact production parse path).

Local smoke: `tests/test_step5_opus.py` → **29 passed in 0.38s**. New tests + existing tests all green.

### 5. ✅ FULL_SYNTHESIS risk flag — correctly out-of-scope

B2 flagged in ship report §"Adjacent frontmatter fields" and §"Cross-reference":
- FULL_SYNTHESIS writes `opus_response.text` directly to `opus_draft_markdown`. If Opus emits malformed YAML, the same Step 6 parse failure surfaces.
- The `step5_opus_system.txt` prompt (rules F1/F2) instructs the model to emit proper YAML, but model compliance is not deterministic.
- Flagged as a candidate for the post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1`.

Correctly out-of-scope for this PR:
- This PR's scope is deterministic stub emitters. FULL_SYNTHESIS is a model-output path.
- Fixing FULL_SYNTHESIS would require a post-parse auto-repair (e.g. second-pass `yaml.safe_load` → `yaml.safe_dump` retry) or a validator that asks Opus to fix its own YAML. Different design problem.
- The 4 stranded rows reported in the field are all stubs (`SKIP_INBOX`/`STUB_ONLY`), not FULL_SYNTHESIS. The recovery SQL correctly filters on `step_5_decision IN ('SKIP_INBOX', 'STUB_ONLY')`.

Confirmed: FULL_SYNTHESIS exposure is a real latent risk, correctly deferred to post-Gate-1 audit brief.

### 6. ✅ No scope creep

`git diff main...HEAD --name-only`:
```
briefs/_reports/B2_step6_frontmatter_yaml_escape_fix_20260421.md   — ship report
kbl/steps/step5_opus.py                                             — stub writers (2 functions) + 1 import + 2 new helpers
tests/test_step5_opus.py                                            — 4 new tests
```

`git diff main...HEAD -- kbl/steps/step6_finalize.py kbl/pipeline_tick.py kbl/bridge/ kbl/steps/step1_triage.py kbl/steps/step2_resolve.py kbl/steps/step3_extract.py kbl/steps/step4_classify.py` → **0 lines.** No Step 6, pipeline_tick, bridge, or step1-4 changes. Per brief constraint.

Within `step5_opus.py`: the modified functions are strictly the stub emitter helpers (`_build_skip_inbox_stub`, `_build_stub_only_stub`) and their new shared helpers (`_dump_stub_frontmatter`, `_build_stub_frontmatter_dict`). The deleted helper `_render_related_matters_yaml` becomes dead code (no remaining callers — verified via grep). The routing/decision/write paths (`synthesize`, `_write_draft`, `_mark_terminal`, `_write_cost_ledger`) are untouched.

### 7. ✅ Adjacent emitter audit

Grepped the broader repo (not just `kbl/steps/`) for frontmatter composition:

```
kbl/gold_drain.py:188:    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n"
kbl/steps/step5_opus.py:408:    return f"---\n{yaml_text}\n---\n"           (post-fix, safe)
kbl/steps/step6_finalize.py:532:    return f"---\n{yaml_text}\n---\n\n...   (canonical, safe)
```

**One adjacent emitter outside the steps pipeline:** `kbl/gold_drain.py:_format_frontmatter` (line 187-188). Uses `yaml.safe_dump(fm, sort_keys=False)` but does NOT pass `allow_unicode=True` or `default_flow_style=False`.

Functional impact: minor cosmetic only.
- `allow_unicode=False` (default): non-ASCII chars emit as `\uXXXX` escapes, still round-trip correctly on parse.
- `default_flow_style=None` (default): for flat scalar dicts, PyYAML picks block style automatically — same effective output for frontmatter.

No bug. But inconsistent with Step 5/6 canonical. Worth a one-line unification in a future cleanup brief — the call sites should all use the same 3-arg pattern. Flag as an adjacent candidate for post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1`:

> Unify `yaml.safe_dump` call pattern across all emitters in `kbl/` to `sort_keys=False, allow_unicode=True, default_flow_style=False`. Currently `kbl/gold_drain.py:188` is missing the last two kwargs.

Non-blocking for PR #34. `gold_drain.py` is downstream of Step 7 commit (handles Gold-vault promotions), reads already-validated frontmatter, and its re-emission is lower-risk than Step 5's fresh emission. No stranded-row exposure today.

---

## Non-blocking N-nits

**N1.** The `_render_related_matters_yaml` helper that was replaced had tests at `test_step5_opus.py` (if any existed). Diff-scanned quickly; didn't find a direct test for it. If any test referenced it, those would now be dead. Not blocking; B2's removal is clean.

**N2.** The `_build_stub_frontmatter_dict` helper signature (`inputs: _SignalInputs, *, title: str`) uses a keyword-only arg — good Python style, and a useful guardrail against accidental positional-arg swap. Worth mirroring elsewhere in the stub path if refactoring grows.

**N3.** `created` field in the stub dict is emitted as `_iso_utc_now()` → a string. Pre-fix unquoted output was parsed by YAML as a native `datetime`; post-fix quoted output is parsed as a string. Pydantic `SilverFrontmatter.created: datetime` coerces the string to datetime on validation. Round-trip equivalent after Pydantic. No change needed.

---

## Recommendation

**Tier A auto-merge OK.**

Post-merge sequence:
1. Merge PR #34 to main.
2. Render auto-deploys (~3 min). Step 5 now emits safe frontmatter on both stub decisions.
3. **Tier B recovery SQL** (per brief §Gate — deviates from standing signal_queue cleanup pattern; AI Head authorizes separately):
   - Pre-flight SELECT audit to verify the ~4 affected rows (Hagenauer + Lilienmatt expected).
   - Transactional UPDATE: `status → 'awaiting_opus'`, `opus_draft_markdown → NULL`, `finalize_retry_count → 0`, `started_at → NULL` where `step_5_decision IN ('SKIP_INBOX', 'STUB_ONLY')` and `status IN ('opus_failed', 'finalize_failed')`.
   - COMMIT only if rowcount matches audit. ROLLBACK and re-investigate otherwise.
4. Watch `kbl_log` for fresh `frontmatter YAML parse failed` errors → should drop to zero.
5. Watch `signal_queue` for the 4 recovered rows advancing `awaiting_opus → opus_running → awaiting_finalize → finalize_running → awaiting_commit`.
6. Mac Mini Step 7 commits → Gate 1 closes when Hagenauer + Lilienmatt reach the vault.

**Post-Gate-1 follow-ups to schedule (additive to prior reviews):**
- `STEP_SCHEMA_CONFORMANCE_AUDIT_1` — expanded scope now covers **four drift classes**:
  1. Column presence drift (existence)
  2. Column type drift (e.g. BOOLEAN vs TEXT)
  3. JSONB shape drift (Python list → text[])
  4. **Emitter-to-parser encoding drift** (this bug)
  B2's §"Cross-reference" framing is clean: for every writer producing text consumed by a parser elsewhere, run hostile-input fuzz tests at CI (YAML-special chars, Unicode edge cases, empty/None scalars).
- Unification nit: one-line patch to `kbl/gold_drain.py:188` adding `allow_unicode=True, default_flow_style=False` to the existing `yaml.safe_dump`. Cheap consistency win, low risk.
- FULL_SYNTHESIS YAML-robustness pattern — auto-repair or re-prompt on `FinalizationError` from `_split_frontmatter`. Out of scope for this class of fix; candidate for a future dedicated brief once production data tells us the shape of real Opus-emitted YAML failures.

---

## Environment notes

- Review done on worktree `/tmp/bm-b3-pr34` against `origin/step6-frontmatter-yaml-escape-fix-1@16cf291`.
- Local py3.9 + fallback pytest: 29 passed in 0.38s (full step5 suite incl. 4 new tests).
- Worktree cleanup: `git worktree remove /tmp/bm-b3-pr34 --force` on tab close per §8.

Tab quitting per §8.

— B3
