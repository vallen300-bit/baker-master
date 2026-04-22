# Code Brisen #2 — Pending Task

**From:** AI Head
**To:** Code Brisen #2
**Task posted:** 2026-04-22 ~11:15 UTC (post PR #40 merge + vault-integrity finding)
**Status:** OPEN — `CORTEX_GATE2_VAULT_INTEGRITY_DIAGNOSTIC_1` (Director-approved diagnostic, Cortex-launch-critical)

---

## Brief-route note (charter §6A)

Freehand diagnostic dispatch. Director said "dispatch as per your recommendation" to a finding AI Head surfaced at ~11:10 UTC. This is NOT a code-change brief — it is a pure investigation. Report-only. Output shape is a markdown evidence dossier, not a PR.

---

## Finding AI Head surfaced to Director (for context)

**"Completed" rows in `signal_queue` are not actually producing content in the vault remote.**

Evidence AI Head collected:

1. **46 rows** at `status='completed'` + `step_5_decision='full_synthesis'` have `opus_draft_markdown=''` AND `final_markdown=''`. Expected per `step7_commit.py:264` (`SET opus_draft_markdown = NULL, final_markdown = NULL` after successful commit — design is "DB releases bytes once vault has the file").

2. **Three recent `commit_sha` values do NOT exist in `/Users/dimitry/baker-vault`.** Tested via `git cat-file -t`:
   - `5991a70695eb8b70fbd5eaca8f10282e72748ed0` (id=72, committed_at 2026-04-22 10:57 UTC)
   - `9319c98bba0f68e3bc48bb5bdf29d557d5188a8c` (id=71, committed_at 2026-04-22 10:55 UTC)
   - `cf7716853face259a69bc3df916b10f2e61e8a22` (id=70, committed_at 2026-04-22 10:42 UTC, `step_5_decision='skip_inbox'`)

   All three: `fatal: git cat-file: could not get object info`.

3. **No commits to `github.com/vallen300-bit/baker-vault` in >8 hours.** `git fetch --all` shows nothing new; latest `origin/main` is `6eceb6e ops: add 8 AI-development brainstorming skills` (unrelated to pipeline).

4. **No files under `/Users/dimitry/baker-vault/wiki/` dated 2026-04-22.** The `target_vault_path` values (e.g. `wiki/hagenauer-rg7/2026-04-22_rg7-cash-call-…md`) don't exist on disk.

5. **`kbl_log` has zero entries for `component='step5_opus'` in last 48h.** Step 5 either doesn't log or uses a different component tag.

6. **Render env on `srv-d6dgsbctgctc73f55730` has only `BAKER_VAULT_PATH` + `GITHUB_VAULT_TOKEN`** — no `BAKER_VAULT_DISABLE_PUSH` or `BAKER_VAULT_MOCK_COMMIT` visible.

Prior handover claimed "Gate 2 closed mechanically — 43+ real vault files." That claim was based on DB column population (`target_vault_path` + `commit_sha` non-null), NOT on actual vault-file existence. **Cortex-launch premise is wrong if Cortex reads the vault repo.**

## Your job — answer 6 questions with hard evidence

Report-only. No code changes. One markdown file at `briefs/_reports/B2_cortex_gate2_vault_integrity_diagnostic_20260422.md`. Commit + push.

### Q1: Where is Step 7 actually running — Render, Mac Mini, or both?

**Evidence needed:**
- `rg "BAKER_VAULT_PATH|vault_path\s*=|cfg\.vault_path" kbl/steps/step7_commit.py kbl/config*.py kbl/poller.py kbl/pipeline_tick.py` — who reads `BAKER_VAULT_PATH` and from which process?
- The `pipeline_tick.main()` claim chain (PR #39): does it invoke Step 7 anywhere? Grep for `step7|finalize_remote|_process_signal_.*_remote`.
- Mac Mini side: `kbl/poller.py` — is this the Step 7 caller? What's its run cadence?
- Definitive answer: which process handles the `awaiting_commit → completed` transition?

### Q2: Does the commit_sha `5991a7069…` (id=72) exist anywhere reachable?

**Candidates to check:**
- Mac Mini local vault clone — if you have SSH creds (check `~/.ssh/config` on the B2 host; the handover mentions Mac Mini as "always-on Step 7 git-commit host"). Run `git cat-file -t <sha>` on Mac Mini's vault clone.
- A branch other than `main` on `origin` (I only checked main). `git ls-remote origin 'refs/heads/*'` + check for feature branches.
- Render service ephemeral filesystem — `BAKER_VAULT_PATH` on Render presumably points to a clone inside the container. If Render is the Step 7 host, the commit lives inside a container whose filesystem doesn't persist across deploys.

**Deliverable:** for each candidate, a one-line answer: "exists / does not exist / could not check (reason)".

### Q3: Is `_git_push_with_retry` actually pushing, or silently failing?

**Evidence needed:**
- Code read: `kbl/steps/step7_commit.py` lines ~625-680 (after `commit_sha = _git_add_commit(...)`). Trace the push path.
- Grep for `disable_push` in `kbl/config*.py` and any schema / env-loading module. **What is its default value when `BAKER_VAULT_DISABLE_PUSH` is unset?** AI Head suspects the default may be `True` (push disabled by default).
- Render logs: pull last 2 hours of service logs via Render API (`GET /v1/services/{service_id}/logs` or similar) and grep for `step7`, `push`, `commit_sha`, `disable_push`. Quote up to 20 lines of evidence.

### Q4: Why is `kbl_log component='step5_opus'` empty?

**Evidence needed:**
- `rg "emit_log\(" kbl/steps/step5_opus.py` — how many call sites? What component tag?
- Cross-check with `kbl/steps/step6_finalize.py` — confirm `emit_log("…", "finalize", …)` uses the string literal `"finalize"` (I observed this) and therefore Step 5's analogue would use `"step5_opus"`, `"opus"`, `"step5"`, or nothing.
- Query: `SELECT DISTINCT component FROM kbl_log WHERE ts > NOW() - INTERVAL '48 hours'` — full component list (AI Head saw: alerts_to_signal_bridge, commit, finalize, pipeline_tick). Where is Step 5?

### Q5: What actually runs end-to-end for signal_id=72?

**Evidence needed:**
- Full kbl_log scan for signal_id=72, all components, all levels, all timestamps: `SELECT ts, level, component, message FROM kbl_log WHERE signal_id=72 ORDER BY ts`. Produce the trace.
- Cross-reference with signal_queue row timeline: `SELECT created_at, started_at, processed_at, committed_at FROM signal_queue WHERE id=72`.
- Sanity: if commit is visible in logs, is there a "push succeeded" / "push failed" log line?

### Q6: If Step 7 commits are local-only (Mac Mini clone not pushing), what is the recovery path?

**No code fix; just enumerate the options:**
- A. Re-run Step 7 for the 46 rows after fixing push.
- B. Reset `signal_queue` to `awaiting_finalize` for the 46 rows and re-process.
- C. Accept local-only Gate 2 "closure"; gate Cortex launch on a vault-repo-sync verification.
- D. Other — if you find a cleaner path.

For each option, note: risk of data loss, operator effort, time to Cortex-launchable state.

## What NOT to do

- **No code changes.** Pure investigation.
- **No schema mutations** (no `UPDATE signal_queue` anywhere in this brief).
- **No ship-by-inspection** — every claim in your report cites a grep line number, SQL result, or log quote.
- **Do not resolve the vault push yourself.** Even if you find a one-liner (e.g. flip env flag on Render), do NOT ship it. Report the finding; AI Head + Director decide the fix scope.

## Ship shape

- Branch: none. No PR. Report commits directly to `main` (same pattern as B1 did for CLAIM_LOOP_ORPHAN_STATES_2 report).
- Report path: `briefs/_reports/B2_cortex_gate2_vault_integrity_diagnostic_20260422.md`.
- Commit message: `diagnostic(B2): CORTEX_GATE2_VAULT_INTEGRITY — evidence dossier`
- Close this task file with a `## B2 dispatch back` section — one-line summary + link to the report.

**Timebox:** 90 min. If you need SSH to Mac Mini and can't get it within 15 min, note that explicitly in Q2 and move on; don't burn the budget on access.

**Working dir:** `~/bm-b2`.

---

**Dispatch timestamp:** 2026-04-22 ~11:15 UTC (AI Head autonomous dispatch, Director-approved at 11:12)
