# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2 (app instance)
**Previous report:** [`briefs/_reports/B2_pr1_review_20260417.md`](../_reports/B2_pr1_review_20260417.md) @ `f7402c9` — verdict REQUEST CHANGES
**Task posted:** 2026-04-17
**Status:** OPEN (WAITING) — standby for B1 revision push, then narrow re-review

---

## Task: PR #1 Narrow Re-Review (after B1 revisions)

### Standby phase

B1 is actively revising PR #1 based on your R1 review. Expected: 10 new commits on `kbl-a-impl` branch addressing BLOCKER B1 + all 5 SHOULD + 4 of 6 NICE.

**Do not start re-review until B1 signals completion.** Their chat ping will include the new branch head SHA.

When the signal arrives, proceed to the review phase below.

---

## Review phase (when B1 signals done)

### Target

**PR:** https://github.com/vallen300-bit/baker-master/pull/1 (same PR, new commits)
**New branch head:** `<SHA from B1 ping>`
**Expected added commits:** 10 (semantic prefixes `fix(kbl-a): B2.B1`, `B2.S1` through `B2.N4`)

### Scope — ULTRA-NARROW

Verify the 10 specific fixes landed as intended. **Do NOT re-review the rest of the PR** — you already did that in the R1 review.

| # | Fix | What to verify |
|---|---|---|
| **B2.B1** | LaunchAgent env-file plumbing | `scripts/kbl-pipeline-tick.sh` (+ 3 other wrappers) source `~/.kbl.env`. Install script creates template + chmods 600. |
| **B2.S1** | Gold drain single-tx | `drain_queue` holds SELECT-FOR-UPDATE lock through filesystem + commit + push. No early commit. |
| **B2.S2** | Cost alert UTC date | `kbl/cost.py:~197` uses `datetime.now(timezone.utc).date().isoformat()` not `date.today()` |
| **B2.S3** | Gemma short-circuit when Qwen active | `call_gemma_with_retry` skips to Qwen path if `qwen_active==true`. Recovery probe implemented (every Nth OR opportunistic). |
| **B2.S4** | git subprocess error path | Either `drain_queue` catches `CalledProcessError`, OR `_commit_and_push` re-raises as `GitPushFailed`. |
| **B2.S5** | Health-check model configurable | `kbl/retry.py:~105` reads via `cfg("circuit_health_model", "claude-haiku-4-5")`. `env.mac-mini.yml` template + brief §16 updated. |
| **B2.N1** | Circuit-open log dedupe | `kbl/pipeline_tick.py:~53-58` routes through `kbl_alert_dedupe` with 15-min bucket OR downgrades to local-only. |
| **B2.N2** | Frontmatter refusal | `kbl/gold_drain.py` `promote_one` returns `"error:no_frontmatter"` for headerless files. |
| **B2.N3** | Vault branch configurable | `kbl/gold_drain.py:~206` `cfg("vault_branch", "main")`. yml + brief updated. |
| **B2.N4** | `was_inserted` strict check | `kbl/logging.py:~141` uses `is True` not `bool(...)`. |

### Structured output

Same format as your R1 review. Scope is ~20 min of verification not 60-90.

```markdown
## Verification Results

| # | Fix | Status |
|---|---|---|
| B2.B1 | ... | ✓ / ⚠ / ✗ |
...

## BLOCKERS
## SHOULD FIX (new)
## NICE TO HAVE (new)

## Verdict: APPROVE / REQUEST CHANGES / BLOCK
```

### Pass criteria

| Result | Next step |
|---|---|
| All 10 land clean, 0 new issues | **APPROVE** → Director merges PR → Render deploys → install on macmini |
| 1-2 incomplete or buggy fixes | REQUEST CHANGES narrow — B1 patches those specifically |
| ≥3 fixes wrong or new blockers | BLOCK — something in v2 went sideways |

### File report

`briefs/_reports/B2_pr1_rereview_20260417.md` per mailbox pattern.

Header:
```
Re: briefs/_tasks/CODE_2_PENDING.md commit <SHA>
PR: https://github.com/vallen300-bit/baker-master/pull/1 (new branch HEAD <SHA>)
Re-reviewing: briefs/_reports/B1_kbl_a_pr1_revisions_20260417.md (B1's fix report)
```

Chat one-liner on completion:
```
PR #1 re-review complete. Report at briefs/_reports/B2_pr1_rereview_20260417.md, commit <SHA>.
TL;DR: <N>B/<M>S/<K>N, verdict <approve|request-changes|block>.
```

### Time budget

**20 minutes max.** This is verify-only on 10 specific diffs, not full review.

---

## Parallel context

- **B1:** currently revising PR #1 (60-90 min budget). Will ping when done.
- **B3:** running Director's D1 eval labeling (independent).
- **Director:** context-switching between labeling and dispatching.

---

*Task posted by AI Head 2026-04-17. Previous: full PR review (f7402c9). Next: narrow verify of B1's 10-commit revision response.*
