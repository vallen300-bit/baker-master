# B2 ship — ClaimsMax worker_ sha256 recovery mapping (2026-07-09)

Dispatch: lead #7721 option 2 (ratified interim mitigation for the null-doc_id RCA in
`briefs/_reports/B2_CLAIMSMAX_NULL_DOCID_DIAGNOSIS_20260709.md`).
PR: #499 (branch `b2/claimsmax-worker-sha256-recovery`).
Bus ship: → lead, thread 82563ddd.

## Done rubric
- [x] Recovery mapping lives in `tools/claimsmax.py::_format_search_result`: rows with
      `doc_id is None` + filename `^worker_\d+_([0-9a-f]{64})\.` get a sibling `sha256`
      handle + `recovered_from: "worker_filename"`. `get_document` accepts that sha256.
- [x] `doc_id=None` semantics preserved (not overwritten) — the search index truly has
      no canonical id for the row; we add a fetchable handle, we don't fabricate an id.
- [x] Non-worker rows byte-identical (no new keys) — verified by test.
- [x] Tests-first: 7 cases added, all failing before impl, all green after.
- [x] No regressions: `test_claimsmax_client.py` 30/30; adjacent suites 57/57.
- [x] Compile-clean.

## Literal pytest output
```
$ python3.12 -m pytest tests/test_claimsmax_client.py -k format_search -q
7 passed, 23 deselected in 0.14s
$ python3.12 -m pytest tests/test_claimsmax_client.py -q
30 passed in 0.20s
$ python3.12 -m pytest tests/test_clerk_gmail_claimsmax_reads.py tests/test_mcp_baker_extension_1.py -q
57 passed, 2 warnings in 0.24s
```
(Interpreter: homebrew python3.12 — system python3.9 lacks the `mcp` module.)

## Scope discipline
- Only `tools/claimsmax.py` (+15 lines: regex + helper + loop) and its test file touched.
- Did NOT overwrite `doc_id` (rejected — dishonest; a recovered handle is not a search id).
- Did NOT filter/drop worker rows (rejected — would hide real matches from ranking).
- Does NOT fix the ClaimsMax index itself — that's option 1 (separate ClaimsMax-repo brief).

## Gates
codex G3 + deputy-codex G2 (parallel), lead merges. No migration, no auth, no secrets,
no persisted-state change → Harness-V2 done-gate: unit-test + gate review sufficient.

## Post-merge
Deploys with next Render push. CM seats immediately gain a fetchable handle on
worker-stage rows; no seat-side change required (the field just appears in search output).
