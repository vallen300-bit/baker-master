# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-21 evening (post PR #33 merge — bridge healed, new Step 6 blocker)
**Status:** OPEN — STEP6_FRONTMATTER_YAML_ESCAPE_FIX_1

---

## Context

PR #33 deployed. Bridge healed — `hot_md_match` live column is TEXT, zero bridge errors in last 3 min, 19 fresh signals landed in `signal_queue`. Critical-path working as designed — until Step 6.

**New Step 6 blocker (4 rows in `status='opus_failed'`, including Hagenauer + Lilienmatt in-scope matters).** Pipeline tick error:

```
unexpected exception in _process_signal_remote: frontmatter YAML parse failed:
mapping values are not allowed here
  in "<unicode string>", line 1, column 20:
    title: Layer 2 gate: matter not in current scope
                       ^
```

Unquoted colon in the title string breaks YAML parse. Every out-of-scope signal hits this because Step 5's deterministic stub emits the same title.

## Root-cause pointer (for you to verify)

`kbl/steps/step5_opus.py:391`:

```python
title = "Layer 2 gate: matter not in current scope"
```

This string is written into frontmatter downstream (probably Step 6's finalize emitter), and the emitter is building YAML via string concat / `f"title: {title}\n"` rather than `yaml.safe_dump`. Any unquoted colon in title or other scalar fields triggers the "mapping values not allowed" error.

## Scope

1. **Locate emitter:** grep repo for where frontmatter is composed from Step 5's `title` field. Most likely `kbl/steps/step6_finalize.py` — frontmatter assembly before commit write.
2. **Fix direction:** switch the emitter to `yaml.safe_dump({...}, default_flow_style=False)` so scalars are quoted when required. OR, narrower fix: force-quote the title via `json.dumps(title)` or `yaml.dump` on the title scalar. Prefer the structured `safe_dump` path — any future frontmatter field gets proper escaping for free.
3. **Recovery:** 4 opus_failed rows need to be re-attempted on the fix landing. Not a Tier A pattern — surface the recovery SQL in your ship report and AI Head will authorize before running.
4. **Regression test:** frontmatter emitter unit test with title containing colon + backslash + newline; assert roundtrip parse via `yaml.safe_load` succeeds.
5. **Migration-vs-bootstrap rule:** N/A — no DB columns touched.
6. **Audit adjacent frontmatter fields:** primary_matter, signal_type, summary, etc. — any field that can contain a colon or other YAML-special character MUST flow through the structured emitter. List any at-risk fields in the ship report.

## Deliverable

- PR on baker-master, branch `step6-frontmatter-yaml-escape-fix-1`, reviewer B3.
- Ship report at `briefs/_reports/B2_step6_frontmatter_yaml_escape_fix_20260421.md`.
- Include: emitter location, before/after snippet, regression test output, recovery SQL for the 4 stranded `opus_failed` rows (AI Head runs post-merge).

## Cross-reference

Today's 4-bug drift cluster (all column-drift) closed with PR #33. This is a distinct bug class — encoding/escape drift between producer and parser. Worth flagging in the ship report that the post-Gate-1 `STEP_SCHEMA_CONFORMANCE_AUDIT_1` should expand scope to cover emitter-to-parser roundtrip fuzz tests, not just schema type/existence drift.

## Constraints

- **XS effort (<1h).**
- No touch to Step 5 logic — only the emitter that consumes its output.
- No touch to bridge, pipeline_tick, or step1-5 consumers.
- **Timebox: 45 min.**

## Working dir

`~/bm-b2`. `git pull -q` before starting.

— AI Head
