---
status: COMPLETE
brief: briefs/BRIEF_FAST_FOLLOW_NITS_BATCH_1.md
brief_id: FAST_FOLLOW_NITS_BATCH_1
target_repo: baker-master
working_dir: /Users/dimitry/bm-b1
working_branch: b1/fast-follow-nits-batch-1
dispatched_by: lead
dispatched_at: 2026-05-23T14:35:00Z
estimated_time: 30-45min
complexity: low
tier: B
ratified_by: Director
ratified_at: 2026-05-23 chat ("Bundle five small lingering needs")
shipped_pr: https://github.com/vallen300-bit/baker-master/pull/250
merged_at: 2026-05-23T15:40:22Z
merge_commit: b1421d829b46e436b216aa739203f8519eb8f57d
report: briefs/_reports/B1_fast_follow_nits_batch_1_20260523.md
---

# CODE_1_PENDING — FAST_FOLLOW_NITS_BATCH_1 — 2026-05-23

**Brief:** `briefs/BRIEF_FAST_FOLLOW_NITS_BATCH_1.md` (commit `f9091cd`)
**Working branch:** `b1/fast-follow-nits-batch-1`
**Working dir:** `~/bm-b1`
**Dispatched by:** `lead` (AH1-Terminal)
**Dispatched at:** 2026-05-23T14:35Z
**Estimated time:** ~30-45 min
**Complexity:** Low
**Tier:** B (Director-ratified 2026-05-23 chat)

Previous BAKER_VIP_MCP_EXPOSE_PROVENANCE_FIELDS_1 dispatch → PR #249 merged 00458e1 at 14:27:56Z. Gate chain cleared, no fast-follows from that one. Now bundle 6 outstanding nits from PR #248 + PR #246.

## Pre-requisites

- `git pull --rebase origin main` on `~/bm-b1` (you're at f9091cd — PR #249 merged + this brief committed).
- No env vars beyond what your current bm-b1 picker already has.
- `node --check` for JS syntax check optional (manual visual scan acceptable if node not available).

## Summary of 6 fixes (read brief for full detail)

1. **Fix 1 MEDIUM:** `triggers/substack_ingest.py:228` — `subject!r` → `json.dumps(subject)`. Mixed-quote subjects produce YAML-invalid frontmatter. Add `import json`.
2. **Fix 2 LOW:** `tests/test_substack_ingest.py` — add `test_ingest_handles_mixed_quote_subject` with `yaml.safe_load` round-trip assertion.
3. **Fix 3 LOW:** `scripts/backfill_nate_substack.py:73-77` — lift `_h()` helper out of loop to module scope.
4. **Fix 4 LOW:** `outputs/static/app.js:590` + `outputs/static/mobile.js:262` — narrow `catch (e) { break; }` to `catch (e) { if (!(e instanceof URIError)) throw e; break; }`.
5. **Fix 5 LOW:** `tests/test_md_scheme_allowlist.py` — add `[triple](///evil.com)` to `REJECT_CASES`.
6. **Fix 6 LOW:** `outputs/static/{app.js,mobile.js}` add `if (!trimmed) return '#';` fast-path; tighten `test_functional_empty_and_whitespace_input` to assert `out === '#'` for whitespace variants.

## Pre-verify (grep before edit — surface in ship report if any fails)

1. `grep -n "subject!r" triggers/substack_ingest.py`
2. `grep -n "def _h(name" scripts/backfill_nate_substack.py`
3. `grep -n "catch (e) { break; }" outputs/static/app.js outputs/static/mobile.js`
4. `grep -n "REJECT_CASES" tests/test_md_scheme_allowlist.py`
5. `grep -n "test_functional_empty_and_whitespace_input" tests/test_md_scheme_allowlist.py`

## Ship gate

- Literal `pytest tests/test_substack_ingest.py tests/test_md_scheme_allowlist.py -v` output in ship report.
- Syntax check Python files + `bash scripts/check_singletons.sh` clean.
- JS files: `node --check` or visual scan of edit context.

## Reporting

- Ship PR against baker-master `main` from branch `b1/fast-follow-nits-batch-1`.
- **Bus-post `lead` on PR open** with topic `ship/fast-follow-nits-batch-1` (`dispatched_by: lead` ⇒ ship-report to `lead`).
- Gate chain on PR open: Gate-1 (AH1 static) + Gate-2 (`/security-review` — touches `_safeHref` XSS-defense code) + Gate-4 (`feature-dev:code-reviewer` 2nd-pass — fires per Protocol trigger 1, `_safeHref` is the URL-scheme allowlist).
- Gate-3 (picker-architect) SKIPPED — no new UI / panel / modal; pure hardening on existing code.

## Out of scope (Do NOT touch)

- `_format_results` formatter (unchanged)
- `_should_skip_pipeline` (unchanged)
- New tests beyond the 4 specified additions
- Migration files
- Other Substack senders / other markdown contexts
- `outputs/dashboard.py` route handlers
- `baker_mcp_server.py`

## Anchor

Director-ratified 2026-05-23 chat ("Bundle five small lingering needs"; bundle expanded to 6 for accuracy — 3 from PR #248 + 3 from PR #246). Brief authored 2026-05-23 ~14:35Z by `lead` (f9091cd baker-master).
