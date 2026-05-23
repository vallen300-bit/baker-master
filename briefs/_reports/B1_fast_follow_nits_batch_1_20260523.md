---
brief: briefs/BRIEF_FAST_FOLLOW_NITS_BATCH_1.md
mailbox: briefs/_tasks/CODE_1_PENDING.md
trigger_class: TIER_B_FAST_FOLLOW_HYGIENE_BUNDLE
target: b1
status: MERGED
shipped_at: 2026-05-23T15:18Z
merged_at: 2026-05-23T15:40:22Z
pr: https://github.com/vallen300-bit/baker-master/pull/250
branch: b1/fast-follow-nits-batch-1
commit_sha: fc20ad753d7310c5e0c8ca8432a654e79ed1de45
merge_commit: b1421d829b46e436b216aa739203f8519eb8f57d
ship_gate: PASS (literal pytest 33/33 GREEN under py3.12)
gate_chain: Gate-1 static + Gate-2 /security-review NO_FINDINGS + Gate-4 code-reviewer 2nd-pass PASS-WITH-NITS (Gate-3 SKIPPED — no UI surface)
---

# Ship report — FAST_FOLLOW_NITS_BATCH_1

## Summary

Six post-merge nits bundled from PR #248 (SUBSTACK_NATE_INGEST_1) +
PR #246 (MD_SCHEME_ALLOWLIST_1) per Director ratification 2026-05-23
chat ("Bundle five small lingering needs" — expanded to 6 for PR #248
accuracy).

| # | Sev | File | Fix |
|---|---|---|---|
| 1 | MEDIUM | `triggers/substack_ingest.py:228` | `subject!r` → `json.dumps(subject)` — mixed-quote subjects now produce YAML-valid frontmatter. Added `import json`. |
| 2 | LOW | `tests/test_substack_ingest.py` | Added `test_ingest_handles_mixed_quote_subject` with `yaml.safe_load` round-trip assert — locks Fix 1 against regression. |
| 3 | LOW | `scripts/backfill_nate_substack.py:73-77` | Lifted `_h()` helper out of the loop to module scope. |
| 4 | LOW | `outputs/static/app.js:590` + `mobile.js:262` | Narrowed `catch (e) { break; }` to `catch (e) { if (!(e instanceof URIError)) throw e; break; }` — silent-swallow of unexpected exceptions removed. |
| 5 | LOW | `tests/test_md_scheme_allowlist.py` | Added `[triple](///evil.com)` to `REJECT_CASES`. |
| 6 | LOW | `outputs/static/{app.js,mobile.js}` + test | Added `if (!trimmed) return '#';` fast-path; tightened `test_functional_empty_and_whitespace_input` to assert `out === '#'` for whitespace variants. |

## Hard ship gate — PASS

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_substack_ingest.py tests/test_md_scheme_allowlist.py
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b1
plugins: langsmith-0.7.38, anyio-4.12.1
collected 33 items

tests/test_substack_ingest.py ................                           [ 48%]
tests/test_md_scheme_allowlist.py .................                      [100%]

======================== 33 passed, 3 warnings in 0.58s ========================
```

33/33 PASS. No skips. No xfails.

## Pre-verify (grep before edit — all hit as expected)

| # | Grep | Result |
|---|---|---|
| 1 | `subject!r` in `triggers/substack_ingest.py` | hit @ line 228 — fixed |
| 2 | `def _h(name` in `scripts/backfill_nate_substack.py` | hit @ line 73-77 — lifted |
| 3 | `catch (e) { break; }` in `outputs/static/app.js`, `mobile.js` | hits @ 590, 262 — narrowed |
| 4 | `REJECT_CASES` in `tests/test_md_scheme_allowlist.py` | hit — added triple-slash case |
| 5 | `test_functional_empty_and_whitespace_input` in same file | hit — tightened assertion |

## Quality checkpoints

| # | Check | Result |
|---|---|---|
| 1 | `python3 -c "import py_compile; py_compile.compile('triggers/substack_ingest.py', doraise=True)"` | COMPILE_OK |
| 2 | `python3 -c "import py_compile; py_compile.compile('scripts/backfill_nate_substack.py', doraise=True)"` | COMPILE_OK |
| 3 | `pytest tests/test_substack_ingest.py tests/test_md_scheme_allowlist.py` (literal) | 33/33 PASS |
| 4 | `node --check outputs/static/app.js outputs/static/mobile.js` | clean |
| 5 | `bash scripts/check_singletons.sh` | OK: No singleton violations found. |
| 6 | `git diff --stat` | 8 files, +68/-27 — strictly within Out-of-Scope boundary |

## Gate chain (per AH1 bus dispatch @ 2026-05-23T15:40:35Z)

- ✅ **Gate-1** (AH1 static review) — PASS
- ✅ **Gate-2** (`/security-review`) — NO_FINDINGS (touches `_safeHref` XSS-defense)
- ⏭️ **Gate-3** (picker-architect) — SKIPPED per brief (no new UI surface)
- ✅ **Gate-4** (`feature-dev:code-reviewer` 2nd-pass) — PASS-WITH-NITS (mandatory_2nd_pass per Protocol trigger 1, `_safeHref` is URL-scheme allowlist)

## Merge

- PR #250 squash-merged into `baker-master:main` at **2026-05-23T15:40:22Z**
- Merge commit: `b1421d829b46e436b216aa739203f8519eb8f57d`
- 8 files changed (+68/-27)
- Render auto-deploy on push

## Files touched (within Out-of-Scope boundary)

```
outputs/static/app.js             |  5 ++++-
outputs/static/index.html         |  2 +-
outputs/static/mobile.html        |  2 +-
outputs/static/mobile.js          |  5 ++++-
scripts/backfill_nate_substack.py | 19 +++++++++++--------
tests/test_md_scheme_allowlist.py | 27 +++++++++++++--------------
tests/test_substack_ingest.py     | 32 ++++++++++++++++++++++++++++++++
triggers/substack_ingest.py       |  3 ++-
```

`index.html` + `mobile.html` cache-buster bumps only (asset versioning on
`app.js` / `mobile.js` edits).

## Notes for the record

- Fix 1's `json.dumps` choice over `repr()` is YAML-safe because YAML 1.2
  is a JSON superset — every `json.dumps` output is a valid YAML scalar.
  `repr()` was unsafe because Python repr emits single-quoted strings with
  embedded `"` un-escaped (or vice versa), producing YAML that fails parse.
- Fix 4's URIError narrowing preserves the existing `break;` short-circuit
  for malformed URIs (the documented behavior) while letting any other
  exception class propagate — protects against silent swallow of programmer
  bugs in the regex iterator.
- Fix 6's whitespace fast-path is symmetric across `app.js` + `mobile.js`
  (enforced by `test_link_regex_uses_safehref_callback[mobile.js]`
  parametrize — both implementations stay in lock-step).

## Bus thread

- Brief authored f9091cd (lead) → mailbox dispatched 05fa7a7 (lead) →
  shipped fc20ad7 (b1) → merge confirmation msg #753 (lead → b1) ACK'd
  at 2026-05-23T15:47Z this session.

## Anchors

- Director ratification 2026-05-23 chat ("Bundle five small lingering needs")
- PR #248 (SUBSTACK_NATE_INGEST_1) merge-time NITs queue → 3 fixes (1, 2, 3)
- PR #246 (MD_SCHEME_ALLOWLIST_1) merge-time NITs queue → 3 fixes (4, 5, 6)
- Lesson #8 (no "by inspection") — literal pytest output captured above
