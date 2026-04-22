# B3 Review — PR #37 STEP4_HOT_MD_PARSER_FIX_1

**Reviewer:** Code Brisen #3
**Date:** 2026-04-22
**PR:** https://github.com/vallen300-bit/baker-master/pull/37
**Branch:** `step4-hot-md-parser-fix-1`
**Head SHA:** `df13283`
**Author:** B1
**Ship report:** `briefs/_reports/B1_step4_hot_md_parser_fix_20260422.md`

---

## §verdict

**APPROVE.** All 6 focus items green. Full-suite regression delta reproduced locally with cmp-confirmed identical failure set. Tier A auto-merge greenlit.

---

## §focus-verdict

1. ✅ **Regex correctness — section header.**
2. ✅ **Regex correctness — slug-line.**
3. ✅ **Test matrix quality.**
4. ✅ **No-ship-by-inspection — full-suite baseline reproduced.**
5. ✅ **Scope discipline.**
6. ✅ **Security / hardening.**

---

## §1 Section-header regex

- `kbl/steps/step4_classify.py:69-72` — new pattern `^##\s+Actively\s+pressing\b[^\n]*\n(?P<body>.*?)(?=^##\s|\Z)`.
- Live-shape match confirmed empirically (test #1 `test_parse_hot_md_live_parenthetical_header`).
- Backward-compat bare header matches (test #2 `test_parse_hot_md_bare_header_still_parses`).
- `\b` word-boundary guard blocks fake extension `## Actively pressings` — confirmed empirically (match=False).
- Body-capture termination at next `##`: confirmed — `## Watch list` in test #5 correctly truncates; `leak_slug` is absent from the resulting set.
- ReDoS surface: `[^\n]*\n` is linear; body lazy `.*?` is bounded by a fixed-anchor lookahead. 100KB pathological input scanned in 0.7ms locally. No nested quantifiers.

## §2 Slug-line regex + tokenizer

- `kbl/steps/step4_classify.py:78-82` — new pattern `^\s*[-*]?\s*\*\*(?P<inner>[^*\n]+)\*\*\s*:` + `_SLUG_TOKEN_RE = ^[A-Za-z0-9_\-]+$`.
- Downstream tokenizer at `kbl/steps/step4_classify.py:176-181` walks `inner.split("+")`, strips, lowercases, filters through `_SLUG_TOKEN_RE`. Dead-simple and auditable.
- Empirical coverage (run locally against the live functions):
  - Single-slug `**hagenauer-rg7**:` → `{hagenauer-rg7}` unchanged. (test #3)
  - Combo `**lilienmatt + annaberg + aukera**:` → all three. (test #4)
  - Garbage `**foo + bar (note) + baz**:` → `{foo, baz}`; `bar (note)` silently dropped.
  - Newline injection `**foo\ninjected: evil**:` → empty set. `[^*\n]+` refuses to span a newline, so no YAML/frontmatter injection surface.
  - Embedded star `**foo*bar**:` → no match. Fence integrity preserved.
  - Uppercase `**MATTER_ALPHA**:` → `{matter_alpha}`. `.lower()` applied before filter; filter is case-neutral — order doesn't alter acceptance but canonicalizes the set.
  - Empty-token `**foo + + bar**:` → `{foo, bar}`; empty silently dropped via `if token and ...` guard.
  - 100KB pathological slug inner → 2.4ms; linear-time.

## §3 Test-matrix quality

5 new tests in `tests/test_step4_classify.py:94-194`. Audit per test:

| # | Test | Pins | Non-trivial? |
|---|------|------|--------------|
| 1 | `test_parse_hot_md_live_parenthetical_header` | exact set `{hagenauer-rg7, ao}` | ✅ exact-set eq |
| 2 | `test_parse_hot_md_bare_header_still_parses` | exact set `{hagenauer-rg7, ao}` | ✅ exact-set eq |
| 3 | `test_parse_hot_md_single_slug_bullet_backward_compat` | exact set `{hagenauer-rg7, mo-vie-am, ao_holding}` | ✅ dash + underscore coverage |
| 4 | `test_parse_hot_md_multi_slug_combo_bullet` | exact set `{lilienmatt, annaberg, aukera}` | ✅ combo split |
| 5 | `test_parse_hot_md_mixed_single_and_multi_slug_bullets` | exact 9-slug union; `leak_slug` from following `## Watch list` MUST NOT appear | ✅ exact-set eq catches both leak and missing-slug failures |

All assertions are `== frozenset({...})` — exact-set equality. A body-capture leak to the next H2 would cause `leak_slug` to appear in the set and fail the equality; a missing slug would drop the count. Both failure modes caught by the same assertion shape. No `assert result is not None` / presence-only tests.

Known-bad shapes from the live bug covered: parenthetical header (test #1), combo bullet (test #4), dash-slug backward compat (test #3), next-H2 leak (test #5).

## §4 Full-suite regression delta

Reproduced locally in `/tmp/b3-venv` (python 3.12, `pip install -r requirements.txt` + `pytest` + `pytest-asyncio`).

```
main baseline (HEAD):    16 failed / 769 passed / 21 skipped / 19 warnings  (11.69s)
pr37 head (df13283):     16 failed / 774 passed / 21 skipped / 20 warnings  (19.50s)
Delta:                   +5 passed, 0 regressions, 0 new errors, 0 new skips
```

**Failure-set identity check:** `cmp /tmp/b3-main-failures.txt /tmp/b3-pr37-failures.txt` → IDENTICAL (no stdout, exit 0). The 16 pre-existing failures are the same test-name set on both runs.

`+5 passed` matches the 5 new tests in `tests/test_step4_classify.py` exactly. Zero tests moved from passing to failing.

My 16-failure count differs from B1's claim of 13 (+3 `tests/test_clickup_integration.py` failures from missing `VOYAGE_API_KEY` in my venv). This is a pure local-env artifact — the same 3 fail on **both** main and pr37 for me, so the delta is unaffected. B1's delta claim is independently validated.

Ship report carries full raw pytest output (§test-results block). `memory/feedback_no_ship_by_inspection.md` honored.

## §5 Scope discipline

- `git diff $(merge-base)..pr37 --name-only` → 2 files: `kbl/steps/step4_classify.py`, `tests/test_step4_classify.py`. Nothing else.
- No schema, no bridge, no pipeline_tick, no step1-3/5-7, no `claim_one_signal` touch.
- No new env vars, no migrations, no new dependencies. Imports unchanged (`grep -nE "^(import|from)" kbl/steps/step4_classify.py` = identical set pre/post).
- `_SLUG_TOKEN_RE` is `_`-prefixed → private module-level const, not a new public export.

## §6 Security / hardening

- **ReDoS:** both new regexes are linear-time. No nested quantifiers. 100KB pathological inputs scanned sub-3ms on both patterns.
- **YAML/frontmatter injection via slug-line:** `[^*\n]+` in the inner capture explicitly refuses newlines; `_SLUG_TOKEN_RE = ^[A-Za-z0-9_\-]+$` is strict-allowlist post-tokenization. A crafted `**foo\ninjected: evil**:` is neutralized at the regex layer before downstream ever sees it — empirically confirmed (empty set).
- **Case-folding ordering:** `.lower()` applied before `_SLUG_TOKEN_RE.match` on line 179. Filter is case-neutral, but pre-folding means the output set is canonicalized, so an uppercase-slug hot.md entry doesn't silently orphan against a lowercase `_SLUG_REGISTRY` downstream.
- **Author word-boundary guard:** `\b` after `pressing` blocks section-regex from binding to an accidentally-extended header (`## Actively pressings`). Confirmed empirically.

No gating findings.

---

## §non-gating

- **N1 — missing negative test for malformed-token combo.** No explicit test for a bullet like `**123 + invalid slug + ok**:` where the middle token contains a space (must be dropped, other tokens must pass). Empirical coverage via my local run confirms the filter handles it correctly; worth a 6th test row in a future tidy-up, but the invariant is fully exercised by the filter and not a gating omission.
- No other nits. Ship report is tight; 2-file scope is exemplary.

---

## §regression-delta

Raw logs at `/tmp/b3-main-pytest-full.log` and `/tmp/b3-pr37-pytest-full.log` (local). Failure set anchors:

```
$ wc -l /tmp/b3-main-failures.txt /tmp/b3-pr37-failures.txt
      16 /tmp/b3-main-failures.txt
      16 /tmp/b3-pr37-failures.txt

$ cmp /tmp/b3-main-failures.txt /tmp/b3-pr37-failures.txt && echo IDENTICAL
IDENTICAL
```

---

## §post-merge

- Tier A auto-merge (squash) proceeds.
- Tier B post-merge UPDATE (53 in-scope rows at `skip_inbox` with null-primary-matter → rewind to `awaiting_classify`) is AI Head ↔ Director out-of-band per §on-APPROVE of dispatch. Not gating.

— B3
