# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous report:** [`briefs/_reports/B1_slugs1_impl_20260417.md`](../_reports/B1_slugs1_impl_20260417.md) — SLUGS-1 shipped (PRs #2 + baker-vault #1 open)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** SLUGS-1 implementation task (shipped, awaiting B2 review)

---

## Task: KBL-A Pre-Install Verification + Merge Runbook

### Why you, now

KBL-A PR #1 is about to merge. Two things need to happen *before* Director clicks merge, and you're the only agent with the context + access to do them in parallel with B2's SLUGS-1 review and B3's D1 v3 retry.

**This is a parallelism play** — we're trying to compress the critical path. Don't block on B2/B3. Report when done.

### Scope (two deliverables, same ~1-hour session)

---

## Deliverable 1 — Pre-install verification report

### Goal

Prove that KBL-A's post-merge 7-step install sequence will not fail on hidden environment state. The merge has to succeed cleanly or Director + AI Head burn an hour debugging.

### Checks to run

**On Render (you can hit Render API via `gh`-style CLI or Render dashboard info in the codebase — if neither works, produce a checklist for Director to verify manually):**

1. `BAKER_VAULT_PATH` env var is set
2. `DATABASE_URL` env var is set (KBL-A migrations fail without it)
3. Current deployed commit on Render's `baker-master` service — confirm it's the latest main (post-PR#1 it'll be the merge commit)
4. Render has `yq` available (KBL-A wrapper uses it to flatten `env.mac-mini.yml`)

**On Mac Mini (via `ssh macmini` — Tailscale already wired per KBL-A):**

1. `BAKER_VAULT_PATH` env var is set in the production shell environment (not just your SSH session — check the LaunchAgent context or the actual env the pipeline tick wrapper inherits)
2. `/path/to/baker-vault` clone exists at whatever `BAKER_VAULT_PATH` points to
3. That clone is on `main` and up-to-date with `origin/main`
4. `ollama` binary is on PATH in non-interactive SSH context (Lesson #34 flagged `/opt/homebrew/bin` missing)
5. Gemma 4 8B + Qwen 2.5 14B models are pulled and warm
6. `claude` CLI is installed + authenticated
7. `flock` binary available (D5 mutex)
8. PostgreSQL client (`psql`) available for `_ensure_*` verification

**On baker-vault repo:**

1. `config/env.mac-mini.yml` file exists on `main` (not just in a PR) — or note if it's pending
2. `slugs.yml` exists on `main` OR on the `slugs-1-vault` branch (for the SLUGS-1 PR — note which)

### Output format

File at `briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`:

- Section per environment (Render / Mac Mini / baker-vault)
- Per-check: ✅ PASS / ❌ FAIL / ⚠️  UNKNOWN (with what the failure looked like)
- Overall verdict: CLEAR TO MERGE / BLOCKED ON <list>
- For any ❌ or ⚠️: a one-line fix recommendation (install this, set this env var, commit this file)

**Critical:** do NOT fix anything in this task. Report only. Director + AI Head decide whether to fix pre-merge or post-merge.

---

## Deliverable 2 — KBL-A merge runbook

### Goal

Translate KBL-A brief's 7-step post-merge install sequence (§1612 onwards + the handover's §"Action 2" recap) into a tight executable runbook. Director executes without re-reading the 1600-line brief.

### File

Path: `briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`

(If `briefs/_runbooks/` doesn't exist yet, create it. Add a tiny README.md explaining "runbooks = operator-facing procedures; briefs = design docs".)

### Structure

For each of the 7 post-merge steps:

1. **Step title** (e.g., "Step 3: SSH to Mac Mini + run install_kbl_mac_mini.sh")
2. **Precondition** — what must be true before starting this step
3. **Exact commands** — copy-paste-ready, no "adjust as needed" language
4. **Expected output** — what success looks like (sample output, grep pattern to confirm)
5. **Failure triage** — if this step fails, where to look (log path, common causes)
6. **Rollback** (if applicable) — how to undo this step's changes

Include the KBL-A brief sections you reference (e.g., "see §1612 for schema CHECK constraint details") so Director can jump to source-of-truth if needed.

### Specific scrutiny

- The install script `scripts/install_kbl_mac_mini.sh` — does it actually idempotent-safely? If re-run, does it fail noisily on already-installed pieces, or skip silently?
- The `~/.kbl.env` secret population — which 5 secrets? Name them. Not "populate 5 secrets" but "populate ANTHROPIC_API_KEY, POSTGRES_PASSWORD, ..."
- The `KBL_FLAGS_PIPELINE_ENABLED=false` start state — verify the env-source flow actually picks it up (yq flatten → env → Python config reader)
- The "flip flag when ready" final step — how does Director flip it? Edit `env.mac-mini.yml` in baker-vault, commit, push, wait for next pipeline tick to pull? Or a manual reload trigger? Document it.

### What NOT to include

- Design rationale (that's in the brief)
- Decision history (that's in DECISIONS_PRE_KBL_A_V2.md)
- Anything requiring a decision from Director mid-procedure — if you hit one, call it out + stop. Runbooks are straight-line execution.

---

## Dispatch back

Two chat one-liners to Director via AI Head when done:

> B1 done (1/2): pre-install verification at `briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`, commit `<SHA>`. Verdict: <CLEAR / BLOCKED on ...>.

> B1 done (2/2): merge runbook at `briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`, commit `<SHA>`. <line count> lines, 7 steps.

---

## Scope guardrails

- **Do NOT** fix any issues you find in verification. Report only.
- **Do NOT** touch the SLUGS-1 PRs (B2 is reviewing).
- **Do NOT** write KBL-B content — that's AI Head + B2 post-D1.
- **DO** flag surprises in the report's "Side-effects / unexpected findings" section.
- **Time-box:** ~1 hour total. If any single check takes >15 min, skip + flag UNKNOWN.

---

## Est. time

~1 hour:

- 25 min verification (Render + Mac Mini + baker-vault checks)
- 25 min runbook drafting
- 10 min report + commits + push

---

*Dispatched 2026-04-18 by AI Head. Git identity: `Code Brisen 1` / `dvallen@brisengroup.com`. Your standard terminal clone.*
