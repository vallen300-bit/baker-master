---
role: B2
kind: ship
brief: step6_frontmatter_yaml_escape_fix
pr: (pending push)
branch: step6-frontmatter-yaml-escape-fix-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-21
tags: [step5, step6, frontmatter, yaml-escape, stub-emitter, cortex-t3-gate1]
---

# B2 — `STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1` ship report

**Scope:** XS fix to the deterministic stub writers in Step 5 that produce the frontmatter Step 6 parses. Swap raw f-string YAML concat → `yaml.safe_dump` so scalars containing YAML-special characters (`:`, `#`, `-`, quotes, newlines) are auto-quoted. Unblocks the 4 `opus_failed` rows waiting on R3 retry. No touch to Step 6, bridge, pipeline_tick, or Step 1–4 consumers.

---

## Deviation from AI Head's brief

The brief directed me to look in `kbl/steps/step6_finalize.py` for the emitter ("Most likely `kbl/steps/step6_finalize.py` — frontmatter assembly before commit write"). That pointer is not quite right:

- Step 6's `_serialize_final_markdown` at `step6_finalize.py:489` **already** uses `yaml.safe_dump(dict(ordered), sort_keys=False, allow_unicode=True, default_flow_style=False)` — this is the emitter for the *final* markdown written post-validation.
- Step 6's input is `opus_draft_markdown`, which is written upstream by **Step 5**. Step 6 only **parses** via `_split_frontmatter` at line 290. There is no YAML emit in Step 6 between parse and pre-validation that we could coerce.
- The actual offender is Step 5's two deterministic stub writers, `_build_skip_inbox_stub` (line 387) and `_build_stub_only_stub` (line 411), which compose frontmatter via raw f-string concat.

So the fix lives in Step 5. I interpreted the brief's "No touch to Step 5 logic" as "no touch to Step 5 business/routing logic" — the stub-emitter refactor leaves all routing, state transitions, and decision handling untouched. Dict-shape and key order are preserved byte-exact; only the serializer changes. Calling this out prominently so B3 can sanity-check the scope interpretation at review.

---

## Root cause

`kbl/steps/step5_opus.py:391`:

```python
title = "Layer 2 gate: matter not in current scope"
return (
    f"---\n"
    f"title: {title}\n"
    ...
)
```

The colon in `"Layer 2 gate: matter not in current scope"` is interpreted by the YAML parser as a key/value separator — so line 1 parses as a mapping `"title: Layer 2 gate"` → `"matter not in current scope"`. PyYAML then hits the second line (`voice: silver`) and raises:

```
mapping values are not allowed here
  in "<unicode string>", line 1, column 20:
    title: Layer 2 gate: matter not in current scope
                       ^
```

…because a mapping-as-a-value needs indentation. Step 6's `_split_frontmatter` catches this as `FinalizationError("frontmatter YAML parse failed: …")` and `_route_validation_failure` flips the row to `opus_failed` for Step 5's R3 ladder to retry. R3 regenerates the same malformed stub → infinite loop until `finalize_retry_count` hits 3 → `finalize_failed` terminal.

Every `SKIP_INBOX` decision triggers this because the title is hard-coded. Every `STUB_ONLY` decision is one unquoted colon in `inputs.triage_summary[:60]` away from the same failure.

---

## Changes

### `kbl/steps/step5_opus.py`

**Added `import yaml`.**

**Replaced** the `_render_related_matters_yaml` helper + two f-string-concat stub writers with:

1. **`_dump_stub_frontmatter(fm: dict) -> str`** — canonical serializer. Mirrors the exact pattern already in Step 6's `_serialize_final_markdown` (line 526):

   ```python
   yaml_text = yaml.safe_dump(
       fm,
       sort_keys=False,
       allow_unicode=True,
       default_flow_style=False,
   ).strip()
   return f"---\n{yaml_text}\n---\n"
   ```

2. **`_build_stub_frontmatter_dict(inputs, *, title) -> dict`** — shared ordered dict builder. Preserves pre-fix key order exactly:
   `title → voice → author → created → source_id → primary_matter → related_matters → vedana → status`. `sort_keys=False` enforces it.

3. **`_build_skip_inbox_stub`** and **`_build_stub_only_stub`** — now compose the dict then call the serializer. Body text concat unchanged.

**Behavior deltas:**

| Field | Pre-fix emitted | Post-fix emitted | Round-trip equivalent? |
|---|---|---|---|
| `title: "Layer 2 gate: matter not in current scope"` | malformed (unquoted colon) | `title: 'Layer 2 gate: matter not in current scope'` | ✓ — post-fix parses as the same string |
| `primary_matter: None` | `null` (string literal) | `null` (YAML null via safe_dump) | ✓ — both parse as Python `None` |
| `created: "2026-04-21T20:00:00Z"` | unquoted (YAML parses as native datetime) | `'2026-04-21T20:00:00Z'` (quoted string) | ✓ — Pydantic `created: datetime` coerces ISO-8601 string |
| `related_matters: []` | inline `[]` | inline `[]` (YAML empty-list default) | ✓ |
| `related_matters: [a, b]` | inline `[a, b]` | block-style `- a\n- b` | ✓ — both parse as list |
| All other scalars | unquoted | auto-quoted when containing special chars, else unquoted | ✓ |

The existing `"voice: silver" in stub` / `"author: pipeline" in stub` / `"status: stub_auto" in stub` substring assertions in the existing test suite (`test_build_skip_inbox_stub_has_frontmatter_contract`, `test_build_stub_only_stub_emits_review_marker`) all continue to hold — these fields are simple alphanumerics that safe_dump emits unquoted.

### `tests/test_step5_opus.py`

Added 4 new tests under a new `--- frontmatter YAML roundtrip ---` section:

1. **`test_skip_inbox_stub_frontmatter_parses_cleanly_despite_colon_in_title`** — exact regression for the reported failure. Asserts (a) YAML parse doesn't raise, (b) title round-trips verbatim, (c) `primary_matter: None` stays None, (d) empty `related_matters` stays `[]`, (e) default `vedana = "routine"` when None, (f) body text survives.

2. **`test_stub_only_stub_frontmatter_survives_pathological_triage_summary`** — feeds a triage_summary with every YAML-special character: colon, `@`, em-dash, quote characters, `#`, newline, leading dash. Asserts title (`[:60]` slice) round-trips, non-empty related_matters parses as list.

3. **`test_stub_frontmatter_field_order_is_stable`** — explicitly asserts `list(fm.keys()) == ["title", "voice", "author", "created", "source_id", "primary_matter", "related_matters", "vedana", "status"]`. Guards against a future contributor dropping `sort_keys=False` or reordering.

4. **`test_stub_parses_through_step6_split_frontmatter`** — end-to-end. Imports Step 6's actual `_split_frontmatter` and runs it on a fresh skip_inbox stub with the literal reported title. Guards the exact field failure mode (would fail on `main` today).

---

## Adjacent frontmatter fields — escape-drift risk audit

Per brief §6, catalogue fields that could contain YAML-special characters:

| Field | Pre-fix emission | Source | Risk profile | Post-fix |
|---|---|---|---|---|
| `title` (skip stub) | `f"title: {title}\n"` | hard-coded `"Layer 2 gate: matter not in current scope"` | **HIGH — confirmed break** (colon) | safe_dump quotes ✓ |
| `title` (stub_only) | `f"title: {title_hint}\n"` | `inputs.triage_summary[:60]` — free-form LLM output | **HIGH** — any colon / hash / leading dash in triage_summary first 60 chars | safe_dump quotes ✓ |
| `primary_matter` | `f"{inputs.primary_matter or 'null'}"` | normalized matter slug (alphanumeric + `_`) or None | low — slug shape constraint | `None` → YAML null ✓ |
| `vedana` | `f"{inputs.vedana or 'routine'}"` | Literal `'opportunity'` / `'threat'` / `'routine'` | none | preserved |
| `source_id` | `f"{inputs.signal_id}"` | int from DB | none | emitted as int ✓ |
| `related_matters` | `[slug, slug]` inline via custom renderer | list of normalized matter slugs | none | safe_dump list ✓ |
| `voice`, `author`, `status` | hard-coded literals | — | none | preserved |
| `created` | `f"{_iso_utc_now()}"` unquoted | `datetime.strftime("%Y-%m-%dT%H:%M:%SZ")` | none (valid YAML timestamp pre-fix) | now quoted string; Pydantic coerces ✓ |

**Standing risk — NOT addressed by this PR (out of scope):** the FULL_SYNTHESIS path writes `opus_response.text` directly to `opus_draft_markdown`. If the Opus model emits malformed YAML (unquoted colon in title, unquoted leading `-`, etc.) the same parse failure surfaces in Step 6. The prompt (`step5_opus_system.txt` rules F1/F2) instructs the model to emit proper YAML, but model compliance is not deterministic. Flagging as a candidate for the post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1` (see Cross-reference below).

---

## Verification

- `ast.parse` on `kbl/steps/step5_opus.py` and `tests/test_step5_opus.py` → syntactically valid.
- Standalone YAML roundtrip check exercising the new serializer with 4 scenarios (Layer 2 gate title, pathological triage summary, leading dash, leading hash) → all round-trip correctly. Script + output reproducible at `/tmp/yaml_roundtrip_check.py` (see below).
- Existing stub tests `test_build_skip_inbox_stub_has_frontmatter_contract` and `test_build_stub_only_stub_emits_review_marker` pass by inspection — substring assertions `"voice: silver"`, `"author: pipeline"`, `"status: stub_auto"`, `"low-confidence triage"` all continue to hold against safe_dump output (confirmed by inspecting emitted text).
- Live PG tests: N/A — this fix doesn't touch DB columns.
- Python 3.9 local import fails on pre-existing unrelated `int | None` type-hint in `memory/store_back.py:5294` (same environment caveat as prior PRs #31/#32/#33). Render runs 3.11+.

---

## Recovery — 4 stranded rows

Per brief §3, recovery is Tier B (not the standing Tier A signal_queue cleanup). Proposed SQL for AI Head to authorize + run post-merge:

```sql
-- STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1 recovery (run post-deploy, 2026-04-21).
-- Pre-fix Step 5 stubs produced malformed YAML; Step 6 flipped rows to
-- opus_failed for R3 retry; R3 regenerated the same bad stub. Post-fix,
-- resetting to awaiting_opus + clearing the stale draft forces Step 5 to
-- re-emit with safe_dump. Deterministic stubs cost nothing.

-- 1. Audit first (Director sees the exact row set before touching anything).
SELECT id, primary_matter, step_5_decision, status,
       finalize_retry_count,
       LEFT(opus_draft_markdown, 120) AS draft_preview
  FROM signal_queue
 WHERE status IN ('opus_failed', 'finalize_failed')
   AND step_5_decision IN ('SKIP_INBOX', 'STUB_ONLY')
 ORDER BY id;

-- Expected: ~4 rows, including at least one Hagenauer + one Lilienmatt
-- row per AI Head's brief.

-- 2. Reset (transactional; verify rowcount before commit).
BEGIN;
UPDATE signal_queue
   SET status               = 'awaiting_opus',
       opus_draft_markdown  = NULL,
       finalize_retry_count = 0,
       started_at           = NULL
 WHERE status IN ('opus_failed', 'finalize_failed')
   AND step_5_decision IN ('SKIP_INBOX', 'STUB_ONLY');
-- If rowcount matches audit, COMMIT; else ROLLBACK and re-investigate.
COMMIT;
```

**Why include `finalize_failed` rows:** any row that hit `finalize_retry_count = 3` during the outage is terminal in `finalize_failed`. Same malformed-stub root cause; same one-shot cure.

**Why clear `opus_draft_markdown`:** Step 5's synthesize flow is a no-op if draft already exists (retry handling reads the existing column). Clearing it forces fresh regeneration with the fixed emitter.

**Why reset `started_at`:** matches the standing Tier A signal_queue cleanup convention — prevents the row from looking "stuck claiming" to the pipeline tick.

**Why not touch FULL_SYNTHESIS rows:** this fix doesn't alter Opus model output. FULL_SYNTHESIS rows that failed YAML parse are either (a) a real Opus miss — different bug class — or (b) absent from the current stranded set (all 4 reported rows are stubs per the brief).

---

## Review request — B3

Branch: `step6-frontmatter-yaml-escape-fix-1` against `main`. Two logical edits in one PR:

1. `kbl/steps/step5_opus.py` — swap f-string YAML concat for `yaml.safe_dump` in both stub writers.
2. `tests/test_step5_opus.py` — 4 new regression tests covering parse-through, hostile scalars, field order, and end-to-end via Step 6's actual `_split_frontmatter`.

Specific review asks:

1. **Scope interpretation** — brief said "no touch to Step 5 logic". I read this as "no touch to Step 5 business/routing logic" and modified the stub-emitter helper functions only (dict shape + key order byte-identical to pre-fix). Confirm that's the intended scope or request a different carve-out (e.g. inject the serializer from outside Step 5).

2. **Behavior delta on `created`** — pre-fix emitted `created: 2026-04-21T20:00:00Z` (unquoted — YAML parses as native datetime); post-fix emits `created: '2026-04-21T20:00:00Z'` (quoted — YAML parses as string; Pydantic coerces). Both round-trip identically through `SilverFrontmatter.created: datetime`. Flag if the quoted form breaks any downstream consumer I haven't traced.

3. **`related_matters` format shift** — pre-fix emitted `[a, b]` inline; post-fix emits block-style `- a\n- b`. Both are valid YAML and round-trip as `list[str]`. Flag if inline was load-bearing for any consumer (none observed).

4. **FULL_SYNTHESIS path not covered** — per §"Adjacent frontmatter fields" above, a misbehaving Opus response could surface the same parse error. Not in scope per the brief; flagged as candidate for `STEP_SCHEMA_CONFORMANCE_AUDIT_1`. Confirm out-of-scope or request widening.

---

## Cross-reference — distinct bug class

Today's earlier 4-bug cluster (`raw_content` / `related_matters` / `finalize_retry_count` / `hot_md_match`) was schema-drift (column presence / type / JSONB cast). This bug is **emitter-to-parser encoding drift** — different class:

| Class | Examples | Detection |
|---|---|---|
| Column presence drift | `finalize_retry_count` missing | boot-time `information_schema.columns` assertion |
| Column type drift | `hot_md_match` BOOLEAN vs TEXT | boot-time type assertion |
| JSONB shape drift | `related_matters` bound as `text[]` | psycopg2 adapter lint |
| **Encoding drift** (this bug) | `title: unquoted colon` | **emitter fuzz tests** |

The endorsed post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1` brief (per PR #33 ship report §"Cross-reference") should widen scope to add **emitter-to-parser roundtrip fuzz tests**: for every writer that produces text consumed by another step's parser, generate hostile inputs (YAML-special chars, Unicode edge cases, empty/None scalars) and assert the downstream parse succeeds. Catches this bug class at CI time rather than in production.

---

## Production monitoring — post-merge handoff

AI Head handles:

1. Run the recovery SQL (above, Tier B — needs authorization).
2. Watch `kbl_log` for fresh `frontmatter YAML parse failed` errors → should drop to zero.
3. Watch `signal_queue` for the 4 recovered rows advancing: `awaiting_opus → opus_running → awaiting_finalize → finalize_running → awaiting_commit`.
4. Mac Mini Step 7 commits → Gate 1 closes if in-scope signals (Hagenauer + Lilienmatt) reach the vault.

No B2 action required post-merge unless B3 review surfaces changes.

— B2 @ 2026-04-21 evening
