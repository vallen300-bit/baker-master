# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance, KBL-A implementer)
**Previous report:** [`briefs/_reports/B1_kbl_a_implementation_20260417.md`](../_reports/B1_kbl_a_implementation_20260417.md) @ `bbefea8`
**B2 PR review:** [`briefs/_reports/B2_pr1_review_20260417.md`](../_reports/B2_pr1_review_20260417.md) @ `f7402c9` — verdict REQUEST CHANGES
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution

---

## Task: KBL-A PR #1 Revisions (v2)

### Authority

**Target branch:** `kbl-a-impl` (add commits, don't force-push — PR #1 auto-updates)
**Ratified brief:** [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md) @ `c815bbf`
**Review source:** [`briefs/_reports/B2_pr1_review_20260417.md`](../_reports/B2_pr1_review_20260417.md) — read fully before starting

B2's review was structured, precise, and identified 1 blocker + 5 should-fix + 6 nice-to-have. Your revision addresses the blocker + all 5 should-fix + 4 of the 6 nice (N5 is AI Head's, N6 deferred).

### Scope (10 items — mostly small, one is structural)

#### BLOCKER — must fix

**B2.B1 — LaunchAgent environment missing secrets.**
- **Root cause:** `launchd` doesn't source `~/.zshrc`. Plists only set `PATH`. `kbl/db.py:27` does `os.environ["DATABASE_URL"]` bare subscript → `KeyError` at first Python import once `KBL_FLAGS_PIPELINE_ENABLED=true`.
- **Fix (B2's option 1 — preferred):** dedicated env file `~/.kbl.env` sourced by wrapper.
  - Add near top of `scripts/kbl-pipeline-tick.sh` (before the yq step):
    ```bash
    # Load secrets from dedicated env file (launchd doesn't source ~/.zshrc)
    [ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"
    ```
  - Same line also added to `scripts/kbl-heartbeat.sh`, `scripts/kbl-dropbox-mirror.sh`, `scripts/kbl-purge-dedupe.sh` — every wrapper that invokes Python needs it.
  - Update `scripts/install_kbl_mac_mini.sh` to:
    - Create `~/.kbl.env` if missing (template with 5 secret names, blank values)
    - `chmod 600 ~/.kbl.env`
    - Echo clear message: "Edit ~/.kbl.env to populate ANTHROPIC_API_KEY, DATABASE_URL, QDRANT_URL, QDRANT_API_KEY, VOYAGE_API_KEY before enabling pipeline."
  - Update brief §6 install script section + §8 wrapper section to reflect the new env-file pattern (I'll make the brief edit separately — you focus on code).

#### SHOULD-FIX (all 5)

**B2.S1 — Gold drain concurrent-drain race.**
- Keep the SELECT-FOR-UPDATE transaction open until after push succeeds. Single commit: the final `UPDATE processed_at`. Remove the early `conn.commit()` after the SELECT.
- Restructure `drain_queue` so the row locks protect the critical section through filesystem + commit + push.
- Cost: ~15 min refactor. Preserves SKIP LOCKED semantics for the full drain.

**B2.S2 — Cost-alert date boundary (UTC vs Europe/Vienna).**
- `kbl/cost.py:197` — change `date.today().isoformat()` → `datetime.now(timezone.utc).date().isoformat()` so the dedupe key aligns with DB `NOW()::date` (UTC).
- One line.

**B2.S3 — `call_gemma_with_retry` short-circuit when Qwen active + inline recovery.**
- Skip Gemma attempts 1-3 when `get_state("qwen_active") == "true"`. Go straight to Qwen.
- Occasionally probe Gemma for recovery — either (a) every Nth call (`cfg_int("qwen_recovery_probe_every", 5)`), or (b) opportunistic on successful Gemma attempt 1 in non-Qwen mode. B2 suggested both; I'd do (a) plus keep existing `maybe_recover_gemma` for count/hours triggers. Belt+suspenders.
- If opportunistic Gemma probe succeeds while Qwen-active, immediately trigger recovery path (clear `qwen_active`, reset counters, log).
- Cost: ~20 min.

**B2.S4 — Gold drain: `git add`/`git commit` error path not caught.**
- Broaden the `except` in `drain_queue` to catch `subprocess.CalledProcessError` in addition to `GitPushFailed`, OR catch `CalledProcessError` inside `_commit_and_push` and re-raise as `GitPushFailed`.
- Latter is cleaner — one type to catch in drain_queue.
- Cost: ~5 min.

**B2.S5 — Hardcoded health-check model.**
- Add `KBL_CIRCUIT_HEALTH_MODEL` to `env.mac-mini.yml` under `ollama:` section (no — better under a new `circuit:` or existing `pipeline:` section since it's Anthropic-side, not Ollama). Default `"claude-haiku-4-5"`.
- `kbl/retry.py:105` — read via `cfg("circuit_health_model", "claude-haiku-4-5")`.
- Also add to brief §16 env var table.
- Cost: ~5 min.

#### NICE-TO-HAVE (4 of 6 — skip N5 and N6)

**B2.N1 — Anthropic-circuit-open WARN log dedupe.**
- `kbl/pipeline_tick.py:53-58` — route through `kbl_alert_dedupe` with a 15-min bucket, OR downgrade to local-logger-only for this specific message.
- Cleaner: route through dedupe — consistent with cost alerts.
- Cost: ~5 min.

**B2.N2 — Frontmatter fabrication on headerless files.**
- `kbl/gold_drain.py:156-163` — if `content` doesn't start with `---\n`, return `"error:no_frontmatter"` instead of injecting frontmatter into a file that never had any.
- Cost: ~5 min.

**B2.N3 — Vault branch hardcode `main`.**
- `kbl/gold_drain.py:206` — `cfg("vault_branch", "main")` instead of literal `"main"`.
- Add `vault_branch` to `env.mac-mini.yml` template (under new `vault:` section or under `gold_promote:`).
- Add to brief §16.
- Cost: ~3 min.

**B2.N4 — `was_inserted` defensive type check.**
- `kbl/logging.py:141-145` — `cur.fetchone()[0] is True` instead of `bool(...)`.
- Prevents `bool('f') == True` trap if adapter returns string.
- Cost: ~1 min.

**SKIP:**
- B2.N5: brief doc drift "3 new columns" — AI Head fixes in separate commit
- B2.N6: install script venv check — defer, add to follow-up brief

### Commit strategy

**Single commit per fix**, semantic messages:
```
fix(kbl-a): B2.B1 — LaunchAgent env-file plumbing (load ~/.kbl.env)
fix(kbl-a): B2.S1 — gold drain: single tx for lock + commit + push
fix(kbl-a): B2.S2 — cost alert dedupe key uses UTC date
fix(kbl-a): B2.S3 — gemma retry short-circuit when qwen active + recovery probe
fix(kbl-a): B2.S4 — git subprocess errors caught in gold drain
fix(kbl-a): B2.S5 — circuit health-check model configurable via env
fix(kbl-a): B2.N1 — anthropic-circuit-open log dedupe
fix(kbl-a): B2.N2 — gold drain refuses headerless files
fix(kbl-a): B2.N3 — vault branch configurable via env
fix(kbl-a): B2.N4 — was_inserted strict True check
```

10 commits on top of current branch head. PR #1 auto-updates.

### Time budget

**60-90 minutes.** B2's estimate + my concurrence.

If you hit a snag (e.g., S3 restructure turns out to be harder than 20 min), commit what works and flag the remainder. Don't push broken code.

### Testing (do after all commits)

Re-run the 8 local tests from your first implementation:
- `python3 -c "import py_compile"` on all kbl/*.py
- `bash -n` on all scripts/kbl-*.sh
- `plutil -lint` on all launchd/*.plist
- Full `from kbl import ...` sweep
- Make sure nothing regressed

No deferred-to-deploy tests change — still Director/me after merge.

### File report at completion

`briefs/_reports/B1_kbl_a_pr1_revisions_20260417.md` per mailbox pattern.

Header:
```
Re: briefs/_tasks/CODE_1_PENDING.md commit <SHA>
PR: https://github.com/vallen300-bit/baker-master/pull/1 (branch kbl-a-impl @ new HEAD)
Revises: briefs/_reports/B2_pr1_review_20260417.md @ f7402c9
```

Summary: 10 commits, B2.B1 fix + B2.S1-S5 + B2.N1-N4, local tests pass.

Chat one-liner:
```
PR #1 revisions shipped. 10 commits on kbl-a-impl. Report at briefs/_reports/B1_kbl_a_pr1_revisions_20260417.md, commit <SHA>.
Awaiting B2 re-review.
```

### Pass criteria

| Result | Next step |
|---|---|
| B2 narrow re-review → 0 blockers | Director merges PR → Render deploys → install on macmini |
| B2 re-review → 1-2 blockers | Another small revision cycle |
| B2 re-review → ≥3 blockers | Diagnose (unlikely given scope is bounded) |

### Parallel context

- **B2:** standing by for re-review. Their task file will be updated to narrow-scope verify after you push.
- **B3:** running Director's D1 eval labeling (independent).
- **Director:** labeling with B3, occasional check-ins with me.

### Do NOT

- Force-push the branch (adds confusion to PR history)
- Address N5 (my brief fix) or N6 (deferred)
- Re-open B2's deviation accepts — all 3 stand
- Restructure beyond the 10 listed items — we're in narrow-fix mode

---

*Task posted by AI Head 2026-04-17. 10 fixes, ~60-90 min. Branch kbl-a-impl continues from your Phase 8 head; PR #1 auto-updates with each push.*
