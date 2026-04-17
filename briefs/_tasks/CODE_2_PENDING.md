# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous report:** [`briefs/_reports/B2_pr1_reverify_20260417.md`](../_reports/B2_pr1_reverify_20260417.md) — KBL-A PR #1 APPROVED, complete
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution
**Supersedes:** the KBL-A PR #1 re-review task (shipped)

---

## Task: SLUGS-1 Independent PR Review (reviewer ≠ implementer)

### Context (60-second read)

B1 implemented SLUGS-1 (matter slug registry, Option A from `briefs/_drafts/SLUG_REGISTRY_DESIGN.md`). Two paired PRs open:

- **baker-master PR #2:** https://github.com/vallen300-bit/baker-master/pull/2 — branch `slugs-1-impl` @ `b24b686` (5 commits code + 1 report)
- **baker-vault PR #1:** https://github.com/vallen300-bit/baker-vault/pull/1 — branch `slugs-1-vault` @ `367b7de` (the YAML data file)

B1's report: `briefs/_reports/B1_slugs1_impl_20260417.md` (on the branch — `gh api /repos/vallen300-bit/baker-master/contents/briefs/_reports/B1_slugs1_impl_20260417.md?ref=slugs-1-impl`).

B1's self-flagged review hints (§"Re-review hints for B2" in the report) are your starting points — they've pre-enumerated the 5 subtleties worth scrutinizing. Use them but don't be constrained by them: your job is independent verification.

**Why you, not B1:** reviewer-separation discipline. B1 wrote the code + the validator's original `MATTER_ALLOWLIST` that this PR subsumes. You wrote neither. You reviewed KBL-A PR #1 independently and structured the critique that landed cleanly — same posture here.

---

## Scope

**IN**
1. Line-by-line review of the 5 code commits on `slugs-1-impl` (see SHAs in the PR description)
2. Review of `baker-vault/slugs.yml` content — 19 slugs + aliases, stale alias fix, description coverage
3. Verify B1's 5 self-flagged hints (semantics of `score_row` guard, hint coverage expansion, prompt enum sort, seeded `__init__.py` bytes, `sys.path` convention)
4. Verify the 2 documented deviations (D1 README→CLAUDE.md, D2 seeded `kbl/__init__.py`)
5. Form a verdict on the 3 residual hardcoded slug sites (`benchmark_ollama_triage.py`, `present_signal.py`, `apply_label.py`) — fold into this PR or defer?
6. Re-run the tests in a fresh clone to confirm 9/9 green + 50/50 validator parity claim

**OUT**
- Re-opening the 4 design §7 questions (AI Head judgment, ratified by Director — do not relitigate)
- The D1 eval retry (B3's thread — independent)
- Auto-merging either PR — Director merges

---

## Review structure (match KBL-A PR #1 review format)

File: `briefs/_reports/B2_slugs1_review_20260417.md`

Sections:

1. **Verdict:** APPROVE / REQUEST CHANGES / REJECT
2. **Blockers:** issues that must be fixed before merge
3. **Should-fix:** improvements worth landing in this PR
4. **Nice-to-have:** follow-up worthy but not merge-blocking
5. **B1 hints assessment:** per-hint verdict (your read matches / disagree / need more info)
6. **Deviations assessment:** D1 + D2 acceptable as-is / request adjustment
7. **Residual hardcoded slugs — verdict:** fold into this PR / follow-up ticket / ignore
8. **Test re-run evidence:** paste test output from your fresh clone

Follow the pattern from your `B2_pr1_review_20260417.md` — it was structured, precise, and actionable. Match it.

---

## Specific scrutiny points (on top of B1's hints)

### Security / robustness

- **`BAKER_VAULT_PATH` missing on deploy:** B1's loader raises `SlugRegistryError` on missing env — is that the right failure mode for first-boot on a fresh Render deploy where the config ordering might load `slug_registry` before `BAKER_VAULT_PATH` is sourced? Check the Render start command sequence against KBL-A's `_ensure_*` pattern.
- **YAML injection / malformed file:** if `slugs.yml` in baker-vault is later hand-edited and becomes malformed, does the loader fail cleanly without leaking partial state across threads (given the `threading.Lock`)? Eyeball the lock + cache invalidation on exception paths.
- **Alias case/whitespace normalization at load time:** B1 says aliases are lowercased + whitespace-collapsed. Does `normalize()` apply the same transforms to model outputs before lookup? Unicode? Tab characters? German umlauts on hypothetical future slugs?

### Semantic invariants

- **`score_row` guard preserves pre-refactor invariant:** B1's §"Semantic changes" §2 walks through a worked example. Construct your own counter-example: a label of `None` with a model output of `"Hagenauer"` (valid alias via normalization) — does `matter_ok` go True via the alias path, or False? Is that the right answer? (Yes, it should be True — the model found the slug even though the label is null, so the model is "right in a weird way". But confirm.)
- **Hint coverage expansion:** is the `sorted()` iteration in `build_eval_seed.py` stable across runs? If two aliases overlap (e.g., both `ao` and `brisen-lp` have keyword `"brisen"`), which slug wins the hint? Document the tiebreak.

### Deploy ordering

- **Deploy-order failure mode:** B1 says baker-master merging first causes `SlugRegistryError` at first call. Is that truly fail-loud and safe, or will the error be swallowed by a bare `except:` somewhere upstream (retry wrappers, sentinels, scheduler)? Trace call sites.

### Fold vs defer — residual scripts

The three residual slug sites B1 flagged:

- `benchmark_ollama_triage.py` — "semi-deprecated benchmark"
- `present_signal.py` — CLI labeling UI keypress map
- `apply_label.py` — CLI labeling UI keypress map

Form a verdict. My prior: **defer** (the UI keypress maps are legitimately different from the canonical list — a "1" → slug mapping is input shorthand, not a source of truth). But reasonable people could argue otherwise. State your call with reasoning.

---

## Test re-run procedure

```bash
cd /tmp/bm-b2   # or your standard clone
git fetch origin
git checkout slugs-1-impl
git pull
# Fetch the paired baker-vault branch so BAKER_VAULT_PATH has real data:
#   (or use the tests/fixtures/ vault for the test suite specifically)
.venv/bin/python3 -m pytest tests/test_slug_registry.py -v
# Validator parity claim:
BAKER_VAULT_PATH=<your baker-vault checkout at slugs-1-vault branch> \
  .venv/bin/python3 scripts/validate_eval_labels.py outputs/kbl_eval_set_20260417_labeled.jsonl
```

Report the actual output. If you see anything different from B1's claims, that's a REQUEST CHANGES trigger.

---

## Coordination notes

- **B3 D1 retry is in flight** — SLUGS-1 subsumes B3's manual prompt patch + alias fix. If B3 merges first, B1 rebases and takes SLUGS-1's side (structural > tactical). If SLUGS-1 merges first, B3's §2 alias fix becomes a no-op. Either order OK. Don't let B3-coordination paralyze review.
- **KBL-A PR #1 is still pending Director merge.** B1 seeded `kbl/__init__.py` in SLUGS-1 with KBL-A's exact bytes so the rebase auto-resolves. **Verify the byte-for-byte claim** — one of your scrutiny items.

---

## Estimated time

~1.5 hours:

- 45 min code review across 5 commits
- 15 min test re-run + parity verification
- 15 min `slugs.yml` content review
- 15 min writing the report

---

## Dispatch back

Chat one-liner via me:

> `B2 SLUGS-1 review complete — see briefs/_reports/B2_slugs1_review_20260417.md, commit <SHA>. Verdict: <APPROVE | REQUEST CHANGES | REJECT>.`

---

*Dispatched 2026-04-17 by AI Head. Git identity: `Code Brisen 2` / `dvallen@brisengroup.com`. Fresh clone recommended — don't review on a clone where you've been debugging other branches.*
