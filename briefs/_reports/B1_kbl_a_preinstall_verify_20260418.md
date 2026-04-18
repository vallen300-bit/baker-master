# KBL-A Pre-Install Verification Report

**From:** Code Brisen #1
**To:** AI Head (via Director relay)
**Re:** [`briefs/_tasks/CODE_1_PENDING.md`](../_tasks/CODE_1_PENDING.md) Deliverable 1
**Runbook:** [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md) (paired, same session)
**Date:** 2026-04-18

---

## TL;DR

**Verdict: CLEAR TO MERGE, BLOCKED ON MAC MINI PRE-INSTALL SETUP.**

Director can safely click merge on PR #1 **now**. Render deploys + schema migrations work without further action. **But** the post-merge Mac Mini install (runbook step 3) has 3 missing prerequisites and will fail at first run. Fixes are ~10 min of `brew install` + `pip install`. `config/env.mac-mini.yml` also needs to be committed to baker-vault (runbook step 5) before the flag can flip.

Read the runbook's "Pre-install setup" section before running `install_kbl_mac_mini.sh`.

---

## Section 1 — Render (baker-master service)

**Service:** `srv-d6dgsbctgctc73f55730` / Pro / Oregon / branch `main`, auto-deploy on commit. Currently `live` at commit `9a37da6` (today's task dispatch). When PR #1 merges, Render auto-deploys the merge commit.

| # | Check | Status | Notes |
|---|---|---|---|
| 1 | `BAKER_VAULT_PATH` env var set | ⚠️  UNKNOWN | Render MCP doesn't expose env-var reads. **Not needed by KBL-A itself** — the Render FastAPI app doesn't import `kbl.slug_registry`. Needed only post-SLUGS-1 merge if Render-side code ever runs the eval scripts. Not a KBL-A merge blocker. |
| 2 | `DATABASE_URL` env var set | ✅ PASS | Inferred: service status `live` requires PG access; `_ensure_*` bootstrap also requires it at startup. Baker app has been running continuously on this DB. |
| 3 | Current deploy = latest main | ✅ PASS | Deploy `dep-d7hdqvosfn5c73f7f5gg` at commit `9a37da6` (matches `git ls-remote origin main`). When PR #1 merges, the merge commit deploys automatically. |
| 4 | `yq` available on Render | ✅ N/A | **Not required on Render.** `yq` is only invoked by `scripts/kbl-pipeline-tick.sh` (Mac Mini only). Render's `build.sh` is `pip install -r requirements.txt` — no shell-level yml processing. |

**Fix recommendations:** none for KBL-A merge. When SLUGS-1 merges, verify `BAKER_VAULT_PATH` on Render dashboard if any Render-side script would import `kbl.slug_registry` (none today).

---

## Section 2 — Mac Mini (via `ssh macmini`)

**Overall:** host reachable, Ollama + models + claude CLI + git + python3 ✅. But **3 Homebrew binaries missing** and **all KBL Python deps missing** — install script will exit 1 at sanity checks.

### 2a. Homebrew prerequisites (`install_kbl_mac_mini.sh` sanity-check gates)

| # | Check | Status | Where it fails |
|---|---|---|---|
| 1 | `yq` on PATH | ❌ FAIL | Install script L26 — exits 1. Fix: `brew install yq` |
| 2 | `flock` on PATH | ❌ FAIL | Install script L27 — exits 1. Fix: `brew install util-linux` (ships GNU `flock`) |
| 3 | `ollama` on PATH | ✅ PASS | `/opt/homebrew/bin/ollama` 0.20.7 |
| 4 | Gemma 4 model pulled | ✅ PASS | `gemma4:latest` 9.6 GB (2026-04-17) |
| 5 | Qwen 2.5 14B pulled | ✅ PASS | `qwen2.5:14b` 9.0 GB (2026-04-18) |
| 6 | `claude` CLI | ✅ PASS | `/opt/homebrew/bin/claude` 2.1.112 |

### 2b. LaunchAgent runtime dependencies

LaunchAgent PATH is `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` (per plist). `launchd` does NOT source `~/.zshrc`. Checked with that exact PATH:

| # | Check | Status | Notes |
|---|---|---|---|
| 7 | `python3` | ✅ PASS | `/opt/homebrew/bin/python3` 3.14.4 |
| 8 | `git` | ✅ PASS | `/usr/bin/git` 2.50.1 |
| 9 | `psycopg2` importable | ❌ FAIL | Pipeline modules ImportError on tick 1. **Nothing in `pip freeze` except `mlx` and `wheel`.** |
| 10 | `yaml` (PyYAML) importable | ❌ FAIL | Same as #9. Required by `kbl.slug_registry` (post-SLUGS-1) and `config.settings`. |
| 11 | `anthropic` importable | ❌ FAIL | Same as #9. Required by retry + cost modules. |
| 12 | `requests` importable | ❌ FAIL | Same as #9. Required by Ollama HTTP client + Anthropic cost estimate. |

### 2c. Filesystem + config

| # | Check | Status | Notes |
|---|---|---|---|
| 13 | `~/baker-vault` clone | ✅ PASS | On branch `main` @ `05b1bc2`, clean working tree |
| 14 | `~/Desktop/baker-code` clone | ⚠️ BEHIND | On `main` @ `42ecb8b` (7 commits behind `origin/main` @ `9a37da6`). Director will `git pull` as part of install. |
| 15 | `~/.kbl.env` present | ✅ N/A | Expected pre-install. Install script creates the chmod-600 template. |
| 16 | `/var/log/kbl/` exists | ✅ N/A | Expected pre-install. Install script `sudo mkdir` + `newsyslog.d/kbl.conf`. |
| 17 | `/usr/local/bin/kbl-*` symlinks | ✅ N/A | Expected pre-install. Install script creates 5. |
| 18 | `~/Library/LaunchAgents/com.brisen.kbl.*` | ✅ N/A | Expected pre-install. Install script loads 4. |
| 19 | `~/.zshrc` mode | ⚠️ LAX | Currently 0644. Install script chmods to 0600. Not a blocker; just noted. |
| 20 | `~/Dropbox-Vallen` symlink | ✅ PASS | Points at `/Users/dimitry/Library/CloudStorage/Dropbox-Vallen`. Dropbox mirror target `~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs` reachable. |
| 21 | `BAKER_VAULT_PATH` env set | ⚠️ UNSET | Not needed by KBL-A itself (`KBL_VAULT` / `KBL_REPO` overrides are what the scripts read; defaults resolve). **Needed post-SLUGS-1** for `kbl.slug_registry`. Set via `~/.kbl.env` or `~/.zshrc` when that merges. |
| 22 | `psql` CLI | ❌ MISSING | Not required by pipeline (Python uses `psycopg2` → Neon over TLS). Only needed for brief §13 step 2 ("verify via psql"). Fix: `brew install libpq && brew link --force libpq`. |

### 2d. Fix recommendations (Mac Mini)

Bundle as one pre-install setup block (10 min):

```bash
brew install yq util-linux libpq
brew link --force libpq              # puts psql on PATH

# Pipeline Python deps. Simplest: system install since install script doesn't
# assume a venv. Safer: create a venv under baker-code and edit wrappers to
# activate it.
/opt/homebrew/bin/python3 -m pip install --user \
    psycopg2-binary pyyaml anthropic requests httpx pydantic
```

Alternative (Director preference): create a venv under `~/Desktop/baker-code/.venv`, then a follow-up patch makes `kbl-pipeline-tick.sh` + `kbl-heartbeat.sh` + `kbl-gold-drain.sh` + `kbl-dropbox-mirror.sh` + `kbl-purge-dedupe.sh` all source the venv before invoking Python. That's an out-of-scope code change — flag but don't block merge.

---

## Section 3 — baker-vault repo

**Remote:** `https://github.com/vallen300-bit/baker-vault.git`. Local clone at `~/baker-vault`.

| # | Check | Status | Notes |
|---|---|---|---|
| 23 | `config/env.mac-mini.yml` on `main` | ❌ NOT PRESENT | No `config/` directory on `origin/main` at all. Mac Mini pipeline-tick will log `WARN: env.mac-mini.yml not present yet. pipeline will idle` until this is pushed. **Blocks the flag flip** (runbook step 7) until committed. |
| 24 | `slugs.yml` on `main` | ✅ N/A | Lives on `slugs-1-vault` branch (SLUGS-1 PR #1). Will land on `main` when SLUGS-1 merges. Not a KBL-A blocker. |

### Fix recommendations (baker-vault)

Before runbook step 7 (flip flag): Director must commit `config/env.mac-mini.yml` in baker-vault. Use `config/env.mac-mini.yml.example` from the baker-master repo (on `kbl-a-impl`, will be on `main` after PR #1 merge) as the template. Copy to baker-vault, drop the `.example` suffix, review values (no secrets), commit + push.

Sample procedure + exact commands: runbook step 5.

---

## Side-effects / unexpected findings

### F1 — `BAKER_VAULT_PATH` vs `KBL_VAULT` / `KBL_REPO` env-var naming inconsistency

Three env-var names cover related concepts:

- `KBL_VAULT` — used by install script + wrappers (default: `~/baker-vault`)
- `KBL_REPO` — used by install script (default: `~/Desktop/baker-code`)
- `BAKER_VAULT_PATH` — used by `kbl/slug_registry.py` (SLUGS-1 PR)

The task deliverable-1 check list asked about `BAKER_VAULT_PATH`. KBL-A itself doesn't read it — the naming only converges after SLUGS-1 merges. **Not a KBL-A blocker** but worth a future harmonization pass (either rename SLUGS-1's env var to `KBL_VAULT`, or add it to the `env.mac-mini.yml` → yq-flattened keys so both come from the same source).

### F2 — Mac Mini's `~/Desktop/baker-code` clone has no venv, no site-packages

Baker CLAUDE.md memory says Python packages are installed on Mac Mini (line: "Python packages installed: qdrant-client, voyageai, psycopg2-binary, python-dotenv"). Current `pip freeze` shows only `mlx` + `wheel`. Either the memory is stale, or the Python interpreter changed under the hood (Homebrew python3 is now `3.14.4`; prior install may have been 3.11 or similar, and `brew upgrade` would have orphaned site-packages).

Either way: **real state matters more than memory.** Packages need re-installation before pipeline tick works. Memory is flagged for Director to prune.

### F3 — Mac Mini baker-code clone is 7 commits behind `origin/main`

Clone last touched at `42ecb8b` on 2026-04-17 when I was working on SLUGS-1 from MacBook. Mac Mini hasn't auto-pulled. This is fine — runbook step 3 can begin with `git pull` and everything works. Just noting the gap for operator awareness.

### F4 — Install script idempotency check (asked in task §1613)

Audit of `scripts/install_kbl_mac_mini.sh` (version on `kbl-a-impl` @ `f34fdef`):

| Block | Idempotent? | Behavior on re-run |
|---|---|---|
| Sanity checks (yq/flock/ollama/models) | ✅ | `command -v` / `grep` — re-pass is fast |
| `~/.zshrc` chmod 600 | ✅ | Re-applies mode; no-op if already 0600 |
| `~/.kbl.env` creation | ✅ | Creates template only if missing; re-chmods 600 on re-run. **Does NOT clobber populated file.** |
| `env.mac-mini.yml` vault check | ✅ | Non-fatal warn |
| Symlinks (`ln -sf`) | ✅ | `-sf` overwrites atomically |
| LaunchAgent plists | ✅ | `unload \|\| true` then `load` — always fresh |
| `/var/log/kbl` mkdir | ✅ | `if [ ! -d ]` guard |
| `/etc/newsyslog.d/kbl.conf` | ✅ | `if [ ! -f ]` guard |
| Dropbox mirror dir | ✅ | `[ -d ] \|\| mkdir -p` |

**Verdict:** fully idempotent. Safe to re-run. Failure modes are all loud (exit 1 on missing prereq).

### F5 — `.kbl.env` 5-secret enumeration (asked in task §1613)

Install script's `cat > ~/.kbl.env` heredoc creates a template with these 5 exports (all blank):

1. `DATABASE_URL` — Neon PG connection string (read by `kbl/db.py`, `memory.store_back`)
2. `ANTHROPIC_API_KEY` — Claude API key (read by retry + cost modules)
3. `QDRANT_URL` — Qdrant Cloud endpoint (read by `config.settings` at module import — required by the `outputs.whatsapp_sender` import chain even though pipeline stub doesn't use vectors yet)
4. `QDRANT_API_KEY` — Qdrant Cloud API key (same rationale)
5. `VOYAGE_API_KEY` — Voyage embedding key (same rationale)

Director populates all 5 with actual values from the existing Render env (cross-copy manually — one-time). The 3 Qdrant/Voyage keys are required because `config/settings.py` validates them at module load (via the `outputs.whatsapp_sender` import chain that `kbl.whatsapp` wraps). Without them, first Python tick ImportError's before any pipeline logic runs.

### F6 — `KBL_FLAGS_PIPELINE_ENABLED=false` initial-state flow (asked in task §1613)

Validated end-to-end:

1. `env.mac-mini.yml` has `flags: { pipeline_enabled: "false" }` under the top-level `flags` key.
2. yq expression in `scripts/kbl-pipeline-tick.sh` flattens `flags.pipeline_enabled` → `KBL_FLAGS_PIPELINE_ENABLED=false` exported to env.
3. `scripts/kbl-pipeline-tick.sh` checks `if [ "${KBL_FLAGS_PIPELINE_ENABLED:-false}" != "true" ]; then` after yq-source.
4. Bash exits cleanly — Python is never invoked, so missing packages don't matter at this stage.

First tick in a correctly-configured install WILL succeed even with missing Python packages, as long as yq + flock are installed. It just logs "pipeline disabled, exiting" and returns 0. That's the right safe-idle behavior.

**Corollary:** runbook step 6 ("verify first tick green") is a sanity check that yq + flock + env sourcing all work. It does NOT verify Python dependencies — those only matter after step 7 (flag flip). So the install can pass first-tick verification and still be broken for real signals.

### F7 — Flag-flip flow (asked in task §1613)

Documented path (matches brief §13 step 9):

1. Director edits `flags.pipeline_enabled: "true"` in `baker-vault/config/env.mac-mini.yml` (from MacBook via Obsidian, from web GitHub UI, or SSH to Mac Mini and edit there).
2. Director commits + pushes to `baker-vault` `main`.
3. At next Mac Mini cron tick (every 2 min per `pipeline_cron_interval_minutes`), `kbl-pipeline-tick.sh` step 1 `git pull --rebase -X ours origin main` pulls the change.
4. Same tick, step 2 yq-sources the new yml → `KBL_FLAGS_PIPELINE_ENABLED=true`.
5. Step 3 hard-kill-switch passes → Python is invoked.
6. From this tick forward, pipeline processes 1 signal per tick.

**No manual reload trigger needed** — the pull-on-tick pattern is self-propagating.

**Watchout:** if Director edits the yml on the MacBook via Obsidian but hasn't triggered the Git plugin's auto-push, the change never reaches Mac Mini. Director should confirm "auto-push: true" is set in Obsidian Git plugin, or manually `git push`.

---

## Verdict

**KBL-A PR #1 merge: CLEAR.** Render side works without further action.

**Post-merge install: BLOCKED on 3 items** that are quick to fix:

1. Mac Mini Homebrew prereqs: `brew install yq util-linux libpq && brew link --force libpq` (~3 min, not counting download time)
2. Mac Mini Python deps: `/opt/homebrew/bin/python3 -m pip install --user psycopg2-binary pyyaml anthropic requests httpx pydantic` (~2 min)
3. `config/env.mac-mini.yml` committed + pushed to `baker-vault` main (~3 min)

Fix all three in ~10 min of shell, then `scripts/install_kbl_mac_mini.sh` runs clean.

Director's path:

```
CLICK MERGE on PR #1
    → Render auto-deploys (no manual action)
    → SSH macmini → fix 3 prereqs above
    → follow runbook steps 3-7
```

The runbook at `briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md` bundles the prereqs as "Pre-install setup" before step 3.

---

## Unverified / flagged UNKNOWN

- Render `BAKER_VAULT_PATH` (no MCP read tool). Not needed for KBL-A merge. Worth checking before SLUGS-1 merges.
- Neon schema state after migrations run — can only verify post-merge. Runbook step 2 covers.
- First pipeline tick runtime — can only verify post-install. Runbook step 6 covers.

---

## Pointers

- **Ratified brief:** [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md) @ `c815bbf`
- **B2 PR approval:** [`briefs/_reports/B2_pr1_reverify_20260417.md`](B2_pr1_reverify_20260417.md)
- **B1 PR #1 revisions report:** [`briefs/_reports/B1_kbl_a_pr1_revisions_20260417.md`](B1_kbl_a_pr1_revisions_20260417.md)
- **B1 invariants handover:** [`briefs/_handovers/B1_20260417.md`](../_handovers/B1_20260417.md)
- **Runbook (this session):** [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md)
