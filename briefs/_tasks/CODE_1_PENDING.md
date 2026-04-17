# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous report:** [`briefs/_reports/B1_kbl_a_r2_review_20260417.md`](../_reports/B1_kbl_a_r2_review_20260417.md) @ commit `41d5fbf` — R2 verdict: fast v3 revision
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: R3 Narrow-Scope Verification on KBL-A v3

### Target

**File:** `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md`
**New commit:** `<HEAD>` (run `git pull` first)
**URL:** https://github.com/vallen300-bit/baker-master/blob/main/briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF_DRAFT.md

### Scope — ULTRA-NARROW (10-min spot-check max, per your own R2 recommendation)

V3 addresses exactly 4 items you flagged in R2. Verify only these:

| # | R2 Finding | V3 Fix Expected Location | What to verify |
|---|---|---|---|
| NEW-B1 | `kbl/db.py` spec referenced non-existent `.conn` | §2 Deliverables, `kbl/db.py` bullet | Spec now shows `psycopg2.connect(DATABASE_URL)` contextmanager; explicit statement that `SentinelStoreBack` is bypassed; no more `.conn` attribute reference |
| NEW-S1 | Duplicate `__main__` in `pipeline_tick.py` | §8 end of pipeline_tick.py block | Exactly ONE `if __name__ == "__main__":` block |
| NEW-S2 | Heartbeat test wording | §8 line ~720 + §14 acceptance test list | Both places reference dedicated LaunchAgent every 30 min, NOT "every tick" |
| NEW-S3 | Dead `"WARN" if error else "WARN"` ternary | §9 gold_drain.py after push-success marking | Error path uses `emit_log("ERROR", ...)`; success path uses stdlib logger directly (local-file-only, bypasses emit_log) |

### Do NOT

- Re-read the full brief
- Re-open R1 findings (all verified resolved in R2)
- Look for new issues outside the 4 R2 fixes — **unless** one of the v3 edits introduces an obvious new bug in immediate surrounding code

### Output structure

Same format. If all 4 fixes land clean: single-line verdict + no findings table needed. If anything regressed or a fix is wrong: structured findings.

### File your report

`briefs/_reports/B1_kbl_a_r3_verify_20260417.md` per mailbox pattern.

Chat one-liner:
```
R3 verify: <N> findings, verdict <ratify|v4|regression>. Report at <path>, commit <SHA>.
```

### Time budget

**10 minutes max.** This is a verify-only pass, not a review.

### Pass criteria

| Result | Next step |
|---|---|
| 0 findings | **Director ratifies KBL-A → dispatch implementation** |
| 1-2 new findings | Fast v4 revision, immediate re-verify |
| ≥3 findings or any blocker | Stop — something in v3 went sideways |

### After-verify action for YOU (if clean pass)

If 0 findings: report "R3 clean, recommend ratification" and standby. AI Head will prompt Director to ratify; ratification commit is AI Head's job.

### Parallel context

- B3 is running Director's D1 eval labeling session (~60 min interactive) — unrelated to this review.
- B2 idle.
- Director may be context-switching between labeling (B3) and ratification review (me). Don't block them with follow-up questions if possible — ultra-narrow verify.

---

*Task posted by AI Head 2026-04-17, after R2 fix push. Previous report: B1_kbl_a_r2_review_20260417.md (commit 41d5fbf).*
