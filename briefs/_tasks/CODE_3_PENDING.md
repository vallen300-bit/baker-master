# Code Brisen #3 — Pending Task

**From:** AI Head
**To:** Code Brisen #3
**Task posted:** 2026-04-22 (post-B1 ship)
**Status:** CLOSED — PR #37 APPROVE, Tier A auto-merge greenlit, Gate 2 blocker structurally cleared

---

## B3 dispatch back (2026-04-22)

**Verdict: APPROVE** — all 6 focus items green, zero gating nits. Full-suite regression delta reproduced locally with cmp-confirmed identical failure set.

Report: `briefs/_reports/B3_pr37_step4_hot_md_parser_fix_review_20260422.md`.

### Regression delta (focus 4) — reproduced locally

```
main baseline:       16 failed / 769 passed / 21 skipped / 19 warnings (11.69s)
pr37 head df13283:   16 failed / 774 passed / 21 skipped / 20 warnings (19.50s)
Delta:               +5 passed, 0 regressions, 0 new errors
```

Pre-existing failure SET identical (`cmp -s /tmp/b3-main-failures.txt /tmp/b3-pr37-failures.txt` → exit 0). My absolute counts differ from B1's 13-failure claim by +3 `test_clickup_integration.py` (missing `VOYAGE_API_KEY` in my venv) — pure local-env artifact, same 3 fail on both main AND pr37, delta unaffected.

### Per focus verdict

1. ✅ **Section-header regex.** `^##\s+Actively\s+pressing\b[^\n]*\n` matches live parenthetical header, bare backward-compat header, blocks `pressings` extension via `\b`, terminates body at next `##`. Linear-time; 100KB pathological input scanned in 0.7ms.

2. ✅ **Slug-line regex + tokenizer.** `[^*\n]+` inner is permissive; downstream `split("+") → strip → lower → _SLUG_TOKEN_RE.match` pipeline at `step4_classify.py:176-181` is auditable. Empirically verified: single-slug backward compat, combo split, garbage tolerance (`bar (note)` dropped), newline-injection refusal, embedded-star refusal, case-folding, empty-token drop. 100KB inner scanned in 2.4ms.

3. ✅ **Test-matrix quality.** 5 new tests, all `== frozenset({...})` exact-set equality — pins both leak failures AND missing-slug failures with one assertion. Next-H2 leak-check in test #5 catches body-capture leak via `leak_slug` absence. No presence-only asserts.

4. ✅ **No ship-by-inspection.** Full-suite baseline reproduced myself per gate. `feedback_no_ship_by_inspection.md` honored in ship report §test-results.

5. ✅ **Scope discipline.** 2 files, zero new imports, zero env vars, zero migrations, zero new deps. `_SLUG_TOKEN_RE` is `_`-prefixed private const.

6. ✅ **Security / hardening.** No ReDoS surface (both regexes linear). `[^*\n]+` refuses newlines → YAML/frontmatter injection neutralized at regex layer. `_SLUG_TOKEN_RE` is strict allowlist `^[A-Za-z0-9_\-]+$`. `.lower()` applied pre-filter for set canonicalization.

### N-nits parked (non-blocking)

- **N1:** No explicit test for `**123 + invalid slug + ok**:`-style malformed-middle-token bullet. Empirically the filter handles it; worth a 6th test row in a future tidy-up, not gating.

Tier A auto-merge proceeds. Tier B post-merge UPDATE (53 in-scope rows rewound to `awaiting_classify`) is AI Head ↔ Director out-of-band per §on-APPROVE.

Tab quitting per §on-APPROVE.

— B3

---

## Context

B1 shipped the fix for the Gate 2 blocker your own diagnostic helped scope (Step 4's hot.md parser was rejecting every in-scope signal because the section-header regex couldn't tolerate the parenthetical suffix on the live header, and the slug-line regex couldn't handle multi-slug combo bullets).

Live impact pre-fix: `_load_allowed_scope()` returned `[]`, all 57 non-null primary_matter signals routed to `skip_inbox` stubs. Post-fix (B1's local run): returns `['annaberg', 'ao', 'aukera', 'cap-ferrat', 'corinthia', 'hagenauer-rg7', 'lilienmatt', 'm365', 'mo-vie-am', 'nvidia']`.

Tier A auto-merge on your APPROVE. Tier B post-merge recovery follows (53 in-scope rows rewound to `awaiting_classify`).

## PR

- **PR #37:** https://github.com/vallen300-bit/baker-master/pull/37
- **Branch:** `step4-hot-md-parser-fix-1`
- **Head SHA:** `df13283`
- **Ship report:** `briefs/_reports/B1_step4_hot_md_parser_fix_20260422.md` (on main at `7dfdeea`)
- **Scope:** 2 files — `kbl/steps/step4_classify.py` (+38/-13), `tests/test_step4_classify.py` (+98/-0). Nothing else.

## Focus items (in order)

### 1. Regex correctness — section header change

- Old: `^##\s+Actively\s+pressing\s*$(?P<body>.*?)(?=^##\s|\Z)` — anchor at `\s*$` forbids trailing content on header line.
- New: `^##\s+Actively\s+pressing\b[^\n]*\n(?P<body>.*?)(?=^##\s|\Z)` — `\b` word-boundary guard + `[^\n]*\n` tolerates arbitrary trailing on the same line but stops at newline.

Verify:
- New regex matches the live header `## Actively pressing (elevate — deadline/decision this week)`.
- New regex matches the pre-fix bare header `## Actively pressing` (backward compat).
- `\b` prevents matching `## Actively pressings` (fake extension).
- No body-capture leak: next `##` boundary still terminates. A subsequent `## Watch list` (or any `## ...`) must not be absorbed.
- No ReDoS surface — the `[^\n]*\n` is bounded; the `(?:.*?)(?=^##\s|\Z)` lazy body is unchanged.

### 2. Regex correctness — slug-line change

- Old: `^\s*[-*]?\s*\*\*(?P<slug>[A-Za-z0-9_\-]+)\*\*\s*:` — rejected whitespace / `+` inside `**...**`.
- New: `^\s*[-*]?\s*\*\*(?P<inner>[^*\n]+)\*\*\s*:` — captures arbitrary non-`*`, non-`\n` inner content; downstream tokenizes on `+`, strips, lowercases, filters through `_SLUG_TOKEN_RE = ^[A-Za-z0-9_\-]+$`.

Verify:
- Clean single-slug bullet `**hagenauer-rg7**:` still round-trips to `{"hagenauer-rg7"}` (combo-split must not alter clean slugs — walking the Python, a single-token split yields one token which passes the filter unchanged).
- Combo bullet `**lilienmatt + annaberg + aukera**:` yields `{"lilienmatt", "annaberg", "aukera"}`.
- Garbage-tolerant: `**foo + bar (note)**:` silently drops `bar (note)` (fails `_SLUG_TOKEN_RE`) — no exception, no YAML injection surface.
- Case-folding is correct (`.lower()` applied before filter, so `**MATTER_ALPHA**:` → `matter_alpha`).
- Whitespace-only token is silently dropped.

### 3. Test matrix quality

5 new regressions in `tests/test_step4_classify.py` (see ship report §test-matrix):

1. `test_parse_hot_md_live_parenthetical_header` — reproduces the prod bug pre-fix
2. `test_parse_hot_md_bare_header_still_parses` — backward compat
3. `test_parse_hot_md_single_slug_bullet_backward_compat`
4. `test_parse_hot_md_multi_slug_combo_bullet`
5. `test_parse_hot_md_mixed_single_and_multi_slug_bullets` + next-H2 leak-check

Verify:
- Each test actually exercises what its name claims — read the bodies, not just the names.
- #5's leak-check on a subsequent `## Watch list` section is non-trivial. Confirm the assertion catches a body-capture leak (not just an empty-section pass).
- Negative cases present: does the suite cover a malformed slug bullet? (A `**123 invalid**:` token where only `123` would pass filter but the whole bullet should still not contribute invalid tokens.) If absent and you think it's a gating omission, flag it; if you think it's nice-to-have, note in "non-gating".
- No mocks where a string fixture + the real regex would do — hot.md parser is pure.

### 4. No-ship-by-inspection gate — reproduce the full-suite baseline

This is the hard gate. B1's §test-results claims **13 failed / 777 passed / 21 skipped**, and the 13 failures are all pre-existing on main (verified by running the four offending test files against main). You MUST independently reproduce the delta.

Spin up a Python 3.12 venv (B1's approach at `/tmp/b1-venv` works; your copy is yours), install `requirements.txt`, and:

```
pytest tests/ 2>&1 | tee /tmp/b3-pr37-pytest-full.log
```

Then stash B1's changes (checkout `main`), re-run just the four files B1 identified:
`tests/test_1m_storeback_verify.py tests/test_clickup_client.py tests/test_scan_endpoint.py tests/test_scan_prompt.py`
— confirm you get the same 13 failures. If any failure on the PR head is absent on main, flag it as a regression and REQUEST_CHANGES.

Anchor: `memory/feedback_no_ship_by_inspection.md` is the rule; PR #35 was the incident where "by inspection" masked a real blocker. Reproduce the baseline or we don't merge.

### 5. Scope discipline

- Only 2 files changed (confirmed via `gh pr view 37 --json files`). No schema, no bridge, no pipeline_tick, no Step 1-3 / 5-7 touch.
- No new env vars, no migrations, no new dependencies.
- The `_SLUG_TOKEN_RE` addition is a local const in the same file — not a new public export.

### 6. Security / hardening nits (non-gating unless material)

- Any ReDoS surface introduced by the new regexes? Both new patterns are linear-time on length; no nested quantifiers, no backtracking multipliers.
- Any YAML / frontmatter injection risk via the `_SLUG_TOKEN_RE` filter? (Filter is allowlist-only `^[A-Za-z0-9_\-]+$` — safe.)
- Case-folding early is correct (not after filter), so an uppercase-slug hot.md entry doesn't silently orphan.

## Deliverable

- PR review comment on #37: **APPROVE** or **REQUEST_CHANGES**.
- Review report: `briefs/_reports/B3_pr37_step4_hot_md_parser_fix_review_20260422.md`.
- Report sections:
  - §focus-verdict (one line per focus item 1-6)
  - §regression-delta (baseline vs PR head, with cmp-confirmed identical failure set)
  - §non-gating (any quality nits for a follow-up ticket, not blockers)
  - §verdict (APPROVE / REQUEST_CHANGES, with one-line reason)

## On APPROVE

AI Head auto-merges (squash) and runs the Tier B recovery UPDATE (53 in-scope rows → `awaiting_classify`) directly. You don't need to do anything post-approve.

## Working dir

`~/bm-b3`. `git checkout main && git pull -q` before starting.

— AI Head
