---
brief_id: REPORT_RENDERER_SLUG_HARDEN_1
brief: briefs/BRIEF_REPORT_RENDERER_SLUG_HARDEN_1.md
status: SHIPPED
pr: https://github.com/vallen300-bit/baker-master/pull/215
branch: b4/report-renderer-slug-harden-1
commit: 4296cbc
shipped_at: 2026-05-17T14:48:00Z
shipped_by: B4
director_auth: 2026-05-17 chat — "go" (Tier-B fast-follow bundle authorization)
trigger_class: LOW (single-function harden + 1 test; no auth/DB/external surface)
matter_slug: claimsmax
---

# B4 Ship Report — REPORT_RENDERER_SLUG_HARDEN_1

## What shipped

`kbl/report_renderer.py::_matter_slug_from_json_path` now passes the recovered slug through `_validate_safe_slug` before returning. On validation failure, falls back to `"misc"` (silent — same shape as the non-conforming-path fallback already in place).

Closes AH2 cross-lane review #331 LOW from PR #213. Composes with PR #210 harden; applies Lesson #65.

## Diff

- `kbl/report_renderer.py` — +9/-1, one function (lines 314-335).
- `tests/test_report_renderer.py` — +25 lines, 4 new tests.

## Literal pytest output

```
$ /opt/homebrew/bin/python3.12 -m pytest tests/test_report_renderer.py -v
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/dimitry/bm-b4
plugins: langsmith-0.7.38, anyio-4.12.1
collected 29 items

tests/test_report_renderer.py::test_save_investigation_json_writes_parseable_file PASSED [  3%]
tests/test_report_renderer.py::test_save_investigation_json_creates_missing_parent_dirs PASSED [  6%]
tests/test_report_renderer.py::test_save_investigation_json_requires_args PASSED [ 10%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[..] PASSED [ 13%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[../etc] PASSED [ 17%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[a/../b] PASSED [ 20%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[..\\windows] PASSED [ 24%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[with/slash] PASSED [ 27%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[with\\backslash] PASSED [ 31%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[null\x00byte] PASSED [ 34%]
tests/test_report_renderer.py::test_save_investigation_json_rejects_path_traversal_slugs[.] PASSED [ 37%]
tests/test_report_renderer.py::test_convert_to_pdf_runs_pandoc_and_returns_path PASSED [ 41%]
tests/test_report_renderer.py::test_convert_to_pdf_missing_pandoc_raises_unavailable PASSED [ 44%]
tests/test_report_renderer.py::test_convert_to_pdf_pandoc_nonzero_exit_raises_unavailable PASSED [ 48%]
tests/test_report_renderer.py::test_convert_to_pdf_missing_json_raises PASSED [ 51%]
tests/test_report_renderer.py::test_convert_to_pdf_cleans_up_md_sibling_on_success PASSED [ 55%]
tests/test_report_renderer.py::test_convert_to_pdf_cleans_up_md_sibling_on_failure PASSED [ 58%]
tests/test_report_renderer.py::test_convert_to_pdf_pandoc_timeout_raises_unavailable PASSED [ 62%]
tests/test_report_renderer.py::test_convert_to_html_writes_under_docs_site PASSED [ 65%]
tests/test_report_renderer.py::test_convert_to_html_raises_when_docs_site_root_unset PASSED [ 68%]
tests/test_report_renderer.py::test_convert_to_html_uses_env_var_when_no_kwarg PASSED [ 72%]
tests/test_report_renderer.py::test_convert_to_html_raises_when_docs_site_parent_missing PASSED [ 75%]
tests/test_report_renderer.py::test_convert_to_html_falls_back_to_misc_when_path_not_under_research PASSED [ 79%]
tests/test_report_renderer.py::test_renderer_uses_stub_when_report_null PASSED [ 82%]
tests/test_report_renderer.py::test_renderer_raises_on_invalid_json PASSED [ 86%]
tests/test_report_renderer.py::test_matter_slug_from_json_path_returns_segment_before_research PASSED [ 89%]
tests/test_report_renderer.py::test_matter_slug_from_json_path_falls_back_when_no_research_segment PASSED [ 93%]
tests/test_report_renderer.py::test_matter_slug_from_json_path_rejects_parent_dir_candidate PASSED [ 96%]
tests/test_report_renderer.py::test_matter_slug_from_json_path_rejects_research_at_root PASSED [100%]

============================== 29 passed in 0.06s ==============================
```

29/29 green (25 pre-existing + 4 new). Compile-clean (`py_compile`).

## Acceptance criteria coverage

| Criterion | Status |
|---|---|
| `_matter_slug_from_json_path` validates via `_validate_safe_slug` | ✅ |
| Falls back to `"misc"` on validation failure (no exception) | ✅ |
| Test: normal path returns correct slug | ✅ `test_matter_slug_from_json_path_returns_segment_before_research` |
| Test: path with `..` segment → `"misc"` | ✅ `test_matter_slug_from_json_path_rejects_parent_dir_candidate` (path `/dropbox/foo/../research/x.json`, candidate is `..`, validator rejects) |
| Test: path with `/` in candidate segment → `"misc"` | n/a — `/` cannot appear inside a single `Path.parts` element (Path splits on it). Coverage instead by the existing parametrised `save_investigation_json` traversal test which exercises `_validate_safe_slug` directly with `with/slash` etc. |
| Test: path with no `research/` segment → `"misc"` (regression) | ✅ `test_matter_slug_from_json_path_falls_back_when_no_research_segment` + existing `test_convert_to_html_falls_back_to_misc_when_path_not_under_research` |
| Literal pytest output | ✅ above |

## Notes for review

- The `/` test case from the brief is structurally unreachable through `Path.parts` (a single part cannot contain the OS separator). The validator still gets exercised on that input pattern via the existing `[with/slash]` / `[with\\backslash]` parametrised tests at line 105-115. Documented in the table above; if reviewer prefers an explicit unit test calling `_validate_safe_slug("with/slash", field="matter_slug")` directly, happy to add as a fast-follow nit.
- L2 (`_DROPBOX_ROOT` env-var) and `/ask` endpoint remain out of scope per brief §"Out of scope".

## Next

Awaiting AH2 cross-lane review chain per dispatch (`/security-review` skip-eligible per trigger-class LOW). Will hold until AH1 merges.
