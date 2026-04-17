# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance, deepest brief context across R1/R2/R3)
**Previous report:** [`briefs/_reports/B1_kbl_a_r3_verify_20260417.md`](../_reports/B1_kbl_a_r3_verify_20260417.md) @ commit `db1ddf8` — R3 ratify verdict
**Task posted:** 2026-04-17
**Status:** OPEN — awaiting execution (BIG task, 12-16h budget)

---

## Task: IMPLEMENT KBL-A Infrastructure

### Authority

**Ratified brief:** [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md) @ commit `c815bbf` — Director Dimitry Vallen ratified 2026-04-17 after 3 review rounds.

**This task = build everything in that brief.** You've reviewed it 3 times; you know the scope. This task file is NOT a re-spec — it's the dispatch wrapper (branch strategy, commit discipline, PR handoff).

### Scope reminder (from ratified brief)

- 5 new PG tables + `signal_queue` additions (§5)
- Mac Mini install script + 4 LaunchAgents + newsyslog (§6, §12)
- yq-sourced config deployment (§7)
- flock-wrapped pipeline tick wrapper (§8) with Python orchestrator stub
- Gold promote queue drain worker with push-failure rollback (§9)
- Retry ladders + circuit breaker + runtime state (§10)
- Cost tracking with pre-call estimate + daily cap (§11)
- Logging + alert dedupe + heartbeat (§12)
- 9 Python modules under `kbl/*.py` (pipeline_tick, gold_drain, retry, cost, logging, runtime_state, heartbeat, db, whatsapp)
- 5 shell wrapper scripts under `scripts/`
- 4 LaunchAgent plists under `launchd/`

**`kbl/pipeline_tick.py` is a STUB per §17 — KBL-A just claims a signal and marks it `classified-deferred`. KBL-B replaces with actual 8-step pipeline logic. Do NOT implement pipeline logic.**

### Build strategy

#### Branch

Work on a branch, NOT main:

```bash
git checkout -b kbl-a-impl
```

**Why:** Render auto-deploys on `main` push. Every broken commit = Render deploy failure = restart loop. Branch isolates WIP until Director merges the PR at completion.

**Exception:** schema changes land on `main` via `_ensure_*` at Render startup. That means your branch must eventually merge for Phase 1 migrations to run. Don't merge mid-build — finish all phases + PR review first.

#### Phase-per-commit

Per brief §5-§12, there are 8 buildable phases. Commit each phase separately with semantic message:

```
feat(kbl-a): Phase 1 — schema migrations
feat(kbl-a): Phase 2 — Mac Mini install script
feat(kbl-a): Phase 3 — config deployment (yml + yq)
feat(kbl-a): Phase 4 — pipeline wrapper (flock + cron + orchestrator stub)
feat(kbl-a): Phase 5 — Gold drain worker
feat(kbl-a): Phase 6 — retry + circuit breaker + runtime state
feat(kbl-a): Phase 7 — cost tracking
feat(kbl-a): Phase 8 — logging + alert dedupe + heartbeat
```

Each commit body: brief 3-5 bullet summary + acceptance test results.

**Why per-phase:** reviewer (B2) can walk your PR commit-by-commit. Isolates bugs. Easier bisect if something regresses post-deploy.

#### Acceptance tests inline

Run per-phase acceptance tests as you go (from brief §14). Don't batch to the end — catch bugs near the commit that introduced them.

Where tests need real infrastructure (e.g., PG INSERT for signal_queue test, SSH to macmini for flock test):
- Use Director's DATABASE_URL env
- SSH to macmini via existing Tailscale (`ssh macmini`)
- Write test results in the commit body

### Per-phase notes

#### Phase 1 — Schema (Render)

- Extend `memory/store_back.py::SentinelStoreBack` with new `_ensure_*` methods per brief §5
- Reference pre-staged `briefs/_drafts/KBL_A_SCHEMA.sql` v3 (commit `8782813`) — inline FKs adopted, B2 already validated
- **Apply R2.NEW-B1 clarification:** kbl Python code does NOT use `SentinelStoreBack` — it uses the simple `kbl/db.py` direct psycopg2 contextmanager. `SentinelStoreBack` is ONLY for running the `_ensure_*` migrations at Render startup.
- Enforce ordering invariant: `_ensure_signal_queue_additions` runs BEFORE `_ensure_kbl_cost_ledger` + `_ensure_kbl_log` (FK target must exist)
- Test against Director's DATABASE_URL on a Neon branch if possible; else stage locally + verify via `\d` in psql

#### Phase 2 — Install script

- Shell script per brief §6
- Idempotent: re-run should not fail
- sudo prompts for `/var/log/kbl/` creation + newsyslog.d install
- Verify `yq`, `flock`, `ollama`, `gemma4:latest`, `qwen2.5:14b` all present
- Chmod 600 `~/.zshrc` (R1.N3)

#### Phase 3 — Config deployment

- Example `config/env.mac-mini.yml` template committed to `baker-vault` repo (separate PR on that repo — Director merges)
- yq flattening expression per brief §7, includes:
  - R1.B1+B2 corrections (paths recursion, array-to-CSV)
  - R1.S1 `select($p | last | type != "number")` filter
- `kbl/config.py` with `cfg()`, `cfg_list()`, `cfg_bool()`, `cfg_int()`, `cfg_float()` helpers

#### Phase 4 — Pipeline wrapper

- `scripts/kbl-pipeline-tick.sh` per brief §8
  - flock mutex
  - git pull --rebase -X ours (R1.B1/R2 correction)
  - yml guard (R1.M3)
  - Correct yq expression
- `kbl/pipeline_tick.py` STUB — claims 1 signal, marks `classified-deferred`, exits
- Single `__main__` block (R2.NEW-S1 — no duplicate)
- NOT writing heartbeat (R1.S7 single-owner)
- LaunchAgent plist `com.brisen.kbl.pipeline.plist`

#### Phase 5 — Gold drain

- `kbl/gold_drain.py` per brief §9
- R1.B4 transaction order: claim → apply filesystem → commit+push with retry → mark PG done ONLY on push success; push failure rolls back files
- R1.S3: `git add <specific paths>`, NOT `-A`
- R1.S4: commit message includes path + queue_id + wa_msg_id
- R1.N4: VAULT path from env `KBL_VAULT_PATH` with default
- R2.NEW-S3: error results → `emit_log("ERROR", ...)`; success results → stdlib local logger (bypass emit_log, no PG spam)
- `__main__` dispatcher per R1.B3

#### Phase 6 — Retry + circuit breaker

- `kbl/retry.py`, `kbl/runtime_state.py` per brief §10
- R1.B2: Qwen `active_since` uses `datetime.now(timezone.utc).isoformat()`, NOT literal `"NOW()"`
- R1.S8: Qwen recovery = either-condition (count OR hours elapsed)
- R1.S9: `_call_ollama` timeout=180s
- Circuit breaker with health check (skip_circuit flag, 10-min backoff)
- `kbl_runtime_state` key-value access with atomic UPSERT

#### Phase 7 — Cost tracking

- `kbl/cost.py` per brief §11
- R1.B6: `_model_key()` normalizer — raises `ValueError` on unknown model (stricter than silent $0)
- Pre-call estimate via Anthropic `count_tokens` endpoint + fallbacks
- Post-call actual logging
- 80%/95%/100% thresholds with dedupe via `kbl_alert_dedupe` table
- `daily_cost_circuit_clear` at UTC midnight (called by purge-dedupe script)

#### Phase 8 — Logging + dedupe + heartbeat

- `kbl/logging.py` per brief §12
- R1.B5: try/except around `FileHandler` at import
- R1.B3: `__main__` argv dispatcher (emit_critical, emit_info, emit_warn, emit_error)
- `kbl/heartbeat.py` sole heartbeat owner (R1.S7)
- `kbl/whatsapp.py` wraps existing `triggers/waha_client.py` (R1.S1)
- `kbl/db.py` direct psycopg2 contextmanager (R2.NEW-B1)
- `scripts/kbl-heartbeat.sh`, `kbl-dropbox-mirror.sh`, `kbl-purge-dedupe.sh`
- LaunchAgents: `com.brisen.kbl.heartbeat.plist`, `.dropbox-mirror.plist`, `.purge-dedupe.plist`

### Testing

For each phase, run the acceptance tests in brief §14 that apply. Common gotchas you'll hit:

- **Non-interactive SSH + PATH:** `ssh macmini "ollama list"` fails because `/opt/homebrew/bin` isn't in non-interactive PATH. Use `PATH=/opt/homebrew/bin:$PATH` prefix OR full path.
- **DATABASE_URL:** for local testing, pull from macmini's zshrc via SSH one-liner:
  ```bash
  export DATABASE_URL=$(ssh macmini 'source ~/.zshrc 2>/dev/null; echo $DATABASE_URL')
  ```
- **Fresh clone required** for your B1 workspace if `01_build` is also 700+ commits behind (it probably is). Use `/tmp/bm-b1-impl` or similar disposable path.

### PR creation (at completion)

```bash
git push -u origin kbl-a-impl
gh pr create --base main --head kbl-a-impl \
  --title "KBL-A: infrastructure foundation" \
  --body "$(cat <<'EOF'
## KBL-A Implementation

Ratified brief: briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md @ c815bbf

### What's in this PR

- 5 new PG tables + signal_queue additions
- 9 Python modules (kbl/*)
- 5 shell wrapper scripts + 4 LaunchAgent plists
- Install script + newsyslog config + env.mac-mini.yml template

### Phase-per-commit

See git log --oneline for commit-per-phase breakdown.

### Acceptance tests

Per-phase tests passing (details in commit bodies).

### Deploy sequence (post-merge)

1. Render auto-deploys on merge → _ensure_* migrations run at startup
2. Director + Code run install_kbl_mac_mini.sh on macmini
3. Director commits config/env.mac-mini.yml to baker-vault repo
4. First pipeline tick fires — logs "pipeline disabled" (KBL_FLAGS_PIPELINE_ENABLED=false)
5. Director flips the flag when ready to go live

### Review by

Code Brisen #2 — see briefs/_tasks/CODE_2_PENDING.md for review task (will be written post-PR-open).

### Post-merge cleanup

- Delete kbl-a-impl branch after merge
- Update CODE_1_PENDING.md (me) to "standby / await KBL-B brief"
EOF
)"
```

After PR opened, report in chat:
```
KBL-A PR open: <URL>. Commit count: <N>. Per-phase acceptance tests: <N>/<N> pass.
Filed report at briefs/_reports/B1_kbl_a_implementation_20260417.md (or later date).
Awaiting B2 PR review.
```

### Time budget

12-16 hours wall-clock. Split across multiple sessions is fine — commit-per-phase means any handoff point is clean. If you hit a ceiling (context exhaustion, model rotation), commit current work, document state in commit body, next session resumes from clean state.

### Escalate to me (AI Head) immediately if

- Brief has contradictions you can't resolve (possible post-ratification; I'll write clarifying ADR)
- Acceptance test fails in a way that suggests the brief itself is wrong (not an implementation bug)
- Schema conflict with existing Cortex V2 code that the brief didn't account for
- Director is unreachable and a decision is needed for >2h (shouldn't happen — eval labeling is bounded)

Don't escalate for:
- Python import fixes (just solve it)
- Minor shell script differences between macOS BSD tools and Linux GNU expectations (adapt)
- Formatting / linting decisions (use repo's existing style — grep for examples)

### Parallel context

- **B2:** standing by. Will be tasked with PR review when your PR opens.
- **B3:** running D1 eval labeling with Director (independent critical path, ~60 min).
- **Director:** splits attention between B3 (labeling) and occasional check-ins with me/you.
- **SSH hardening:** still Director's 5-min task, bundled with install script sudo prompts — could do during Phase 2 acceptance testing.

### File your report after PR

`briefs/_reports/B1_kbl_a_implementation_<YYYYMMDD>.md` per mailbox pattern.

Contents: commits list with SHAs, acceptance test results per phase, known deviations from brief (if any), gotchas encountered, B2-reviewer hints.

---

*Task posted by AI Head 2026-04-17. Previous report: R3 verify clean. KBL-A ratified (c815bbf) by Director. Build 12-16h, phase-per-commit, PR-to-main for B2 review. Go.*
