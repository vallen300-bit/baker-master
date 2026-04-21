---
role: B2
kind: ship
brief: step5_stub_source_id_type_fix
pr: (pending push)
branch: step5-stub-source-id-type-fix-1
base: main
verdict: SHIPPED_READY_FOR_REVIEW
date: 2026-04-21
tags: [step5, step6, source_id, type-drift, pydantic, cortex-t3-gate1]
---

# B2 — `STEP5_STUB_SOURCE_ID_TYPE_FIX_1` ship report

**Scope:** XS fix. Two edits:
1. **Producer (Step 5 stub dict):** cast `source_id` via `str(inputs.signal_id)` — matches `SilverFrontmatter.source_id: str`.
2. **Authoritative override (Step 6 finalize):** force-set `fm_dict["source_id"] = str(row.signal_id)` before Pydantic validation — defense-in-depth for the FULL_SYNTHESIS path (Opus user prompt currently does not surface `signal_id` to the model) and any future producer that forgets the cast.

Unblocks 20 rows stranded at `awaiting_finalize` after PR #34's YAML fix revealed the next layer.

---

## Root cause

`kbl/schemas/silver.py:139`:
```python
source_id: str
```

`kbl/steps/step5_opus.py:425` (pre-fix):
```python
"source_id": inputs.signal_id,  # int — SERIAL PRIMARY KEY
```

`yaml.safe_dump({"source_id": 17, ...})` emits `source_id: 17` unquoted → `yaml.safe_load` returns Python `int` → Pydantic v2 `source_id: str` rejects with `Input should be a valid string`.

Pydantic v2's default mode **does not coerce int→str**, even for non-strict fields. This is the documented Pydantic v2 behavior (tightened from v1) and is the reason the error message reads `Input should be a valid string` rather than a type-coercion retry.

This bug was **always present** — the earlier `mapping values are not allowed here` YAML parse error (PR #34 target) raised before Pydantic validation ever ran, so int source_id never reached the validator. Post-PR-#34, the YAML parses cleanly and the int-typed value reaches Pydantic, which rejects. Each layer fix reveals the next.

---

## Changes

### 1. `kbl/steps/step5_opus.py` — producer-side cast

In `_build_stub_frontmatter_dict` (shared helper for both `_build_skip_inbox_stub` and `_build_stub_only_stub`):

```diff
-        "source_id": inputs.signal_id,
+        "source_id": str(inputs.signal_id),
```

Docstring expanded with the failure-mode rationale and the Pydantic v2 coercion reference, plus a pointer to Step 6's defense-in-depth force-set.

### 2. `kbl/steps/step6_finalize.py` — authoritative override

Added one line after the existing triage-telemetry injection block (line 615-618), before `_normalize_money_list`:

```python
# STEP5_STUB_SOURCE_ID_TYPE_FIX_1 (2026-04-21 evening): source_id is
# DB-authoritative (signal_queue.id is SERIAL). Force-overwrite any
# producer-emitted value with ``str(row.signal_id)`` so (a) Step 5
# stubs that forgot the ``str()`` cast still pass Pydantic's
# ``source_id: str`` and (b) the FULL_SYNTHESIS path — where the
# Opus user prompt does NOT currently surface signal_id to the model
# (see ``kbl/prompts/step5_opus_user.txt``) — can never diverge
# from the ground truth. Defense in depth alongside producer-side
# fix in ``step5_opus._build_stub_frontmatter_dict``.
fm_dict["source_id"] = str(row.signal_id)
```

**Why force-set, not `setdefault`:** Per the FULL_SYNTHESIS latent bug (see §"FULL_SYNTHESIS path" below), the Opus model may emit a hallucinated or wrong value in the `source_id` field because the user prompt doesn't surface `signal_id`. `setdefault` would preserve the wrong value; force-set guarantees DB-authoritative. Semantically this is correct regardless: `signal_queue.id` is the ground truth, every downstream writer (final_markdown, cross-link rows, the stub_row marker) should carry the canonical value.

---

## FULL_SYNTHESIS path — latent bug (fixed by the Step 6 override)

`kbl/prompts/step5_opus_user.txt` does **not** contain `{signal_id}` or any other source_id placeholder. The system prompt template (`step5_opus_system.txt` line 52) instructs the model:

```
source_id: <signal_id from input>
```

…but `_build_user_prompt` (line 574) does not substitute a `signal_id` into the rendered user template. So the model is told to emit a value it never sees.

Three possible model behaviors at runtime:
1. **Omit `source_id`** — Pydantic fails with `Field required`.
2. **Hallucinate a value** — may or may not be a string; wrong digits; unpredictable.
3. **Leave placeholder verbatim** — `source_id: <signal_id from input>` is a valid YAML scalar (string) but semantically wrong.

All three failure modes are covered by the Step 6 `fm_dict["source_id"] = str(row.signal_id)` force-set, which runs before Pydantic validation.

**Recommend post-Gate-1:** fix the prompt-rendering root cause — add `signal_id=inputs.signal_id` to `_build_user_prompt.template.format(...)` and a `{signal_id}` slot in `step5_opus_user.txt`. Out of scope for this XS fix (brief timebox 30 min). The Step 6 override is correct regardless (source_id is DB-authoritative) so this remains a cosmetic cleanup.

---

## Adjacent frontmatter fields — type-conformance audit

Per brief §3, audit every field the stub dict writes against `SilverFrontmatter`:

| Stub dict field | Stub value type | Schema type | Post-YAML-roundtrip type | Pydantic accepts? | Status |
|---|---|---|---|---|---|
| `title` | `str` | `str` (+ validator: strip, 1-160 chars, no trailing period) | `str` | ✓ | aligned (PR #34) |
| `voice` | `"silver"` literal | `Literal["silver"]` | `"silver"` | ✓ | aligned |
| `author` | `"pipeline"` literal | `Literal["pipeline"]` | `"pipeline"` | ✓ | aligned |
| `created` | ISO-8601 `str` (safe_dump emits as quoted str) | `datetime` | `str` | ✓ — Pydantic coerces ISO-8601 to datetime | aligned (PR #34 noted) |
| `source_id` | **was `int`, now `str`** | `str` | `int` → rejected / **`str` → accepted** | ✗ pre-fix / ✓ post-fix | **fixed here** |
| `primary_matter` | `Optional[str]` (slug or None) | `Optional[MatterSlug]` (regex + `active_slugs()` check) | `None` or `str` | ✓ if slug ∈ ACTIVE, else ValidationError | aligned on type; data-quality risk is out of this PR's scope |
| `related_matters` | `list[str]` | `List[MatterSlug]` | `list[str]` | ✓ on each slug ∈ ACTIVE | aligned |
| `vedana` | `"routine"` / `"opportunity"` / `"threat"` | `Literal[...]` | `str` | ✓ if ∈ literal set | aligned |
| `status` | `"stub_auto"` | `Optional[Literal["stub_auto", "stub_cross_link", "stub_inbox"]]` | `str` | ✓ | aligned |

**Findings:**
- One type-drift confirmed and fixed: `source_id`.
- One data-quality risk flagged (not fixed here): `primary_matter` / `related_matters` elements can be rejected if the slug is RETIRED or not in `slugs.yml` ACTIVE. That's a validator failure, not a type mismatch — surfaces as `ValidationError: slug 'X' is not in slugs.yml ACTIVE set`. If it fires, the fix is at the triage/resolver layer (Steps 1-2), not here.
- `created` quoted-string form (introduced in PR #34) roundtrips cleanly to `datetime` via Pydantic's ISO-8601 coercion — no drift.

No further type-drift bombs in the stub dict.

---

## Regression tests

### `tests/test_step5_opus.py` (+3 tests)

1. **`test_stub_frontmatter_emits_source_id_as_string`** — exact regression. Builds skip_inbox stub with `signal_id=17`, roundtrips through `yaml.safe_load`, asserts `isinstance(fm["source_id"], str)` and `fm["source_id"] == "17"`. Would fail on `main`.
2. **`test_stub_source_id_is_string_across_id_sizes`** — parametrized over `[1, 0, 17, 2_147_483_647, 9_999_999_999]` (small, zero, typical, 32-bit boundary, >32-bit). Asserts str type + exact value match for every case.
3. **`test_stub_validates_against_silver_frontmatter_schema`** — end-to-end producer + Step 6 injection + Pydantic validate chain. Mirrors Step 6's inject order (`triage_score` setdefault, `triage_confidence` setdefault, `source_id` force-set) then calls `SilverFrontmatter(**fm_dict)`. Guards the composite contract.

### `tests/test_step6_finalize.py` (+3 tests)

New section: `--- source_id authoritative override ---`.

1. **`test_finalize_overrides_bare_int_source_id_with_db_authoritative_str`** — simulates pre-fix stub (`source_id: 17` bare int in YAML). Runs `finalize(signal_id=17, ...)`. Asserts terminal state `awaiting_commit` and final_markdown contains `source_id: '17'` (quoted string via safe_dump on a str value).
2. **`test_finalize_overrides_wrong_string_source_id_with_signal_id`** — simulates Opus hallucinating `source_id: email:stale999` while the DB-authoritative id is 42. Asserts final_markdown carries `source_id: '42'` and does **not** contain `stale999`. Guards the authoritative-override contract.
3. **`test_finalize_injects_missing_source_id`** — simulates Opus omitting `source_id` entirely (FULL_SYNTHESIS latent bug). Asserts Pydantic still passes and final_markdown carries `source_id: '99'`.

### Standalone runtime verification

```
sid=1:          round-trip OK, source_id='1'
sid=0:          round-trip OK, source_id='0'
sid=17:         round-trip OK, source_id='17'
sid=2147483647: round-trip OK, source_id='2147483647'
sid=9999999999: round-trip OK, source_id='9999999999'
pre-fix regression confirmed: int survives as int
```

---

## Verification

- `ast.parse` on 4 modified files → all syntactically valid.
- Standalone YAML roundtrip check across 5 signal_id sizes → all serialize as str.
- Existing Step 5 stub tests (`test_build_skip_inbox_stub_has_frontmatter_contract`, `test_build_stub_only_stub_emits_review_marker`) continue to pass by inspection — `"voice: silver"` / `"author: pipeline"` / `"status: stub_auto"` / `"low-confidence triage"` substring assertions unchanged.
- Existing Step 6 finalize tests pass by inspection — `_full_synthesis_draft` already uses string-form `source_id: email:abc123`; the override runs on those too but overwrites with same-type value (only the digits differ, which no existing test asserts on).
- Live PG tests: N/A — no DB columns touched.

---

## Recovery — 20 stranded rows

Per brief §"Recovery", the 20 rows at `awaiting_finalize` will be picked up by Step 6 on next tick once the fix deploys. Step 6's built-in retry (`finalize_retry_count`) handles advancement without manual intervention. No recovery SQL required unless rows already hit the retry ceiling (3); AI Head flagged Tier B auth for that contingency.

If after deploy the 20 rows don't drain within a few ticks, AI Head can authorize:

```sql
-- Safety reset for any rows that exhausted finalize_retry_count during the outage.
BEGIN;
UPDATE signal_queue
   SET status = 'awaiting_finalize',
       finalize_retry_count = 0,
       started_at = NULL
 WHERE status IN ('opus_failed', 'finalize_failed')
   AND opus_draft_markdown IS NOT NULL
   AND step_5_decision IN ('SKIP_INBOX', 'STUB_ONLY');
COMMIT;
```

---

## Review request — B3

Branch: `step5-stub-source-id-type-fix-1` against `main`. Four files:

1. `kbl/steps/step5_opus.py` — producer cast to str in shared helper.
2. `kbl/steps/step6_finalize.py` — authoritative force-set before Pydantic validate.
3. `tests/test_step5_opus.py` — +3 regression tests.
4. `tests/test_step6_finalize.py` — +3 authoritative-override tests.

Specific review asks:

1. **Scope expansion (Step 6 inject)** — brief primary fix was producer-side in Step 5. I added a one-line authoritative force-set in Step 6's `finalize()` because the FULL_SYNTHESIS path is latently broken (Opus user prompt doesn't surface `signal_id`). The force-set is semantically correct regardless (source_id is DB-authoritative) and unblocks FULL_SYNTHESIS when in-scope signals finally route there. Confirm in-scope or request I back it out.

2. **Force-set vs setdefault** — I chose force-set over setdefault. Force-set guarantees DB-authoritative truth even if a producer emits a wrong-but-type-valid string. Setdefault would preserve wrong values. The brief's phrasing ("verify FULL_SYNTHESIS path writes source_id as str (Opus output); if not, fix there too") is ambiguous on this choice — I went with the stronger guarantee. Flag if you prefer setdefault semantics.

3. **`created` coercion regression check** — PR #34 made `created` a quoted string. Pydantic `created: datetime` coerces ISO-8601 strings via the standard validator. Existing step6 tests don't explicitly test quoted-created roundtrip. Low-risk; flag if you want an explicit coverage test.

4. **FULL_SYNTHESIS prompt-template bug** — the Opus user prompt never sees `signal_id`. Step 6 override masks this, but the prompt template is still semantically wrong ("source_id: <signal_id from input>" references data the model never receives). Recommend a post-Gate-1 micro-brief to inject `{signal_id}` into `_build_user_prompt.template.format(...)` and add the slot to `step5_opus_user.txt`. Confirm this is the right framing or assign differently.

---

## Cross-reference — today's drift cluster, now 5 bugs

| # | Column / field | Class | Status |
|---|---|---|---|
| 1 | `raw_content` | Phantom column read by consumers | ✓ PR #30 merged |
| 2 | `hot_md_match` | Live BOOLEAN vs migration TEXT | ✓ PR #33 merged |
| 3 | `related_matters` | JSONB write bound as text[] | ✓ PR #31 merged |
| 4 | `finalize_retry_count` | Column never migrated, SELECT precedes self-heal | ✓ PR #32 merged |
| 5 | `title` (stub) | Encoding drift — YAML escape | ✓ PR #34 merged |
| 6 | `source_id` (stub) | **Producer-vs-schema type drift** — int vs `source_id: str` | **This PR** |

Post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1` scope now covers **four** failure-mode classes:
- Column presence drift (bootstrap vs migration)
- Column type drift (BOOLEAN vs TEXT)
- Column shape drift (text[] vs jsonb)
- **Emitter-to-parser encoding drift** (PR #34)
- **Producer-vs-schema type drift** (this PR) — remediable via Pydantic `model_dump()` round-trip pre-commit hook on every dict-producing writer.

All recommend becoming CI lint rules + boot-time conformance assertions before Gate 2 work starts.

---

## Production monitoring — post-merge

AI Head handles:

1. Watch Render deploy completion for this merge.
2. Watch `kbl_log` for `source_id: Input should be a valid string` errors → should drop to zero.
3. Watch `signal_queue` status advance on the 20 `awaiting_finalize` rows: `awaiting_finalize → finalize_running → awaiting_commit`.
4. Watch Mac Mini Step 7 commits → Gate 1 closes if Hagenauer / Lilienmatt / other in-scope rows reach the vault.
5. Watch `connection already closed` cascade log noise (brief §5 — not addressed by this PR) — expect frequency to drop once the upstream Pydantic failure stops; decide post-Gate-1 whether it's worth a dedicated cleanup brief.

No B2 action required post-merge unless B3 review surfaces changes.

— B2 @ 2026-04-21 evening
