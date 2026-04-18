# KBL-A Merge Runbook

**Scope:** Execute the KBL-A PR #1 merge and the post-merge install sequence that brings the Mac Mini pipeline online.
**Outcome:** Mac Mini runs the 2-min pipeline tick; first real signal processes after flag flip.
**Est. time:** ~30–40 min wall clock (10 min Mac Mini prereq + 5 min merge-deploy + 15–20 min install + config).
**Paired report:** [`briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`](../_reports/B1_kbl_a_preinstall_verify_20260418.md) — read the "Verdict" section before starting.
**Brief source-of-truth:** [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md) @ `c815bbf`

---

## Before you start — prerequisites

### Merge-time PR state

- PR #1 (`kbl-a-impl` → `main`) is approved by B2.
- No `main` work in flight that would conflict (last `main` commit should be a dispatch/docs commit, not a large feature).

### Mac Mini prereqs (3 Homebrew binaries + 6 Python packages)

From the verification report §2d. Run these BEFORE step 3.

```bash
ssh macmini
brew install yq util-linux libpq
brew link --force libpq                 # puts psql on PATH
/opt/homebrew/bin/python3 -m pip install --user \
    psycopg2-binary pyyaml anthropic requests httpx pydantic
```

Verify:

```bash
which yq flock psql                      # all three should print a path
/opt/homebrew/bin/python3 -c 'import psycopg2, yaml, anthropic, requests' \
    && echo "python deps ok"
```

If any of these fail, **stop** — fix before continuing. Pipeline can't start without them.

### Secrets you'll need pasted into `~/.kbl.env` (step 4)

1. `DATABASE_URL` — copy from Render dashboard → baker-master → Environment
2. `ANTHROPIC_API_KEY` — same source
3. `QDRANT_URL` — same source
4. `QDRANT_API_KEY` — same source
5. `VOYAGE_API_KEY` — same source

Have the Render dashboard open in another tab so you can copy-paste.

---

## Step 1 — Merge PR #1 on GitHub

**Precondition:** Mac Mini prereqs above are green. Render dashboard open to `baker-master` service in another tab.

**Action:**

1. Open https://github.com/vallen300-bit/baker-master/pull/1.
2. Click **Merge pull request** → **Confirm merge** (use "Create a merge commit", not squash — the commit-per-phase history is load-bearing for post-hoc audit per R1 reviews).
3. Do NOT delete the `kbl-a-impl` branch yet; keep until step 6 passes.

**Expected output:** PR shows "Merged" with a new merge commit SHA on `main`.

**Failure triage:**

- "This branch is out-of-date" → merge `main` into `kbl-a-impl` first, re-run CI, re-merge.
- Merge conflict: highly unlikely (B2 verified mergeable on 2026-04-17). If surfaces, **stop** and ping B1 for resolution.

**Rollback:** `git revert <merge-commit-sha>` on `main` + force-push (allowed here because it's a revert, not a history rewrite). Then reopen PR #1.

---

## Step 2 — Render auto-deploy + schema migration verification

**Precondition:** Step 1 complete. Render auto-deploys on commit (verified `autoDeploy: yes` on service config).

**Action:**

1. Watch Render dashboard → baker-master → Deploys. Most recent deploy should show the new merge-commit SHA and transition through `building → live` in ~4 min.
2. Once `live`, verify schema migrations applied. Run from any shell with `DATABASE_URL` (Director's MacBook works — or SSH to Render instance):

```bash
psql "$DATABASE_URL" -c '\d kbl_runtime_state'
psql "$DATABASE_URL" -c '\d kbl_cost_ledger'
psql "$DATABASE_URL" -c '\d kbl_log'
psql "$DATABASE_URL" -c '\d kbl_alert_dedupe'
psql "$DATABASE_URL" -c '\d gold_promote_queue'
psql "$DATABASE_URL" -c '\d signal_queue'
```

**Expected output:**

- All 5 new tables + `signal_queue` show full column lists.
- `kbl_log.level` CHECK rejects `INFO` (see constraint: only `WARN|ERROR|CRITICAL` allowed — R1.S2 invariant).
- `signal_queue` has 4 new columns (`primary_matter`, `related_matters`, `triage_confidence`, `started_at`) + 3 new indexes.
- `kbl_cost_ledger.signal_id` and `kbl_log.signal_id` are FK to `signal_queue(id) ON DELETE SET NULL` (R1.B4 invariant).
- `kbl_runtime_state` has 6 seeded rows: `mac_mini_heartbeat`, `anthropic_circuit_open`, `anthropic_circuit_open_since`, `cost_circuit_open`, `qwen_active`, `qwen_active_since`.

```bash
psql "$DATABASE_URL" -c "SELECT key FROM kbl_runtime_state ORDER BY key"
```

Should print 6 rows.

**Failure triage:**

- Deploy fails with `_ensure_*` error → open Render logs, look for Python traceback. Most likely cause: `DATABASE_URL` unset (pre-deploy check). Set in Render dashboard → Environment → redeploy.
- Tables missing but deploy `live` → `_ensure_*` was skipped. Check `memory/store_back.py:184-191` still calls them in the bootstrap block. See [`briefs/_handovers/B1_20260417.md`](../_handovers/B1_20260417.md) §2 for invariant.
- FK constraint missing `ON DELETE SET NULL` → migration corrupted. Manual fix:

```sql
ALTER TABLE kbl_cost_ledger DROP CONSTRAINT kbl_cost_ledger_signal_id_fkey;
ALTER TABLE kbl_cost_ledger ADD CONSTRAINT kbl_cost_ledger_signal_id_fkey
    FOREIGN KEY (signal_id) REFERENCES signal_queue(id) ON DELETE SET NULL;
-- repeat for kbl_log
```

**Rollback:** `DROP TABLE` statements for all 5 new tables + reverse `signal_queue` alters. Full list in `memory/store_back.py:6310+` `_ensure_*` methods — each has a corresponding drop.

---

## Step 3 — SSH to Mac Mini + run install script

**Precondition:** Step 2 green (schema present). Mac Mini prereqs from "Before you start" are installed.

**Action:**

```bash
ssh macmini
cd ~/Desktop/baker-code
git fetch origin
git checkout main
git pull --ff-only origin main                    # pick up merge commit
./scripts/install_kbl_mac_mini.sh
```

**Expected output:**

- `OK: ~/.zshrc mode 0600 enforced`
- `CREATED: /Users/dimitry/.kbl.env (empty template, mode 0600)` — with a prominent banner telling you to populate 5 secrets
- 5 symlinks in `/usr/local/bin/kbl-*` (pipeline-tick, gold-drain, heartbeat, dropbox-mirror, purge-dedupe)
- 4 LaunchAgents loaded (`launchctl list | grep brisen.kbl` prints 4 lines)
- `/var/log/kbl/` created (mode 755, owner `dimitry:staff`)
- `/etc/newsyslog.d/kbl.conf` installed
- Final line: `=== KBL Mac Mini install complete ===`

Verify:

```bash
ls -la /usr/local/bin/kbl-*                       # expect 5 symlinks
launchctl list | grep brisen.kbl                  # expect 4 agents
ls -la /var/log/kbl/                              # expect dir with mode 755
ls -la ~/.kbl.env                                 # expect -rw------- (mode 600)
```

**Failure triage:**

- `FAIL: yq not installed` / `FAIL: flock not installed` / `FAIL: ollama not installed` → did not complete "Before you start" prereqs. Install, re-run script.
- `FAIL: gemma4 not pulled` / `FAIL: qwen2.5:14b not pulled` → `ollama pull gemma4:latest && ollama pull qwen2.5:14b`, re-run script.
- `sudo` prompts unexpectedly on CI → expected for `/var/log/kbl` creation + `newsyslog.d/kbl.conf` install. Director approves interactively.
- LaunchAgent load fails → `launchctl list | grep brisen.kbl` will be empty. Check plist syntax: `plutil -lint ~/Library/LaunchAgents/com.brisen.kbl.pipeline.plist`.

**Rollback:**

```bash
for plist in com.brisen.kbl.pipeline com.brisen.kbl.heartbeat \
             com.brisen.kbl.dropbox-mirror com.brisen.kbl.purge-dedupe; do
    launchctl unload ~/Library/LaunchAgents/${plist}.plist 2>/dev/null
    rm ~/Library/LaunchAgents/${plist}.plist
done
sudo rm /usr/local/bin/kbl-*
sudo rm -rf /var/log/kbl
sudo rm /etc/newsyslog.d/kbl.conf
rm ~/.kbl.env
```

The install script is fully idempotent (verified in preinstall report §F4) — re-running recovers from partial failure without manual rollback.

---

## Step 4 — Populate `~/.kbl.env`

**Precondition:** Step 3 complete (template exists at `~/.kbl.env`). Render dashboard open with env vars visible.

**Action:**

```bash
ssh macmini                                       # if not still in session
vi ~/.kbl.env                                     # or `nano` or `code -w`
```

Fill in these 5 values (copy-paste from Render dashboard Environment tab):

```bash
export DATABASE_URL="postgresql://..."
export ANTHROPIC_API_KEY="sk-ant-..."
export QDRANT_URL="https://...qdrant.io"
export QDRANT_API_KEY="..."
export VOYAGE_API_KEY="pa-..."
```

Save, then:

```bash
chmod 600 ~/.kbl.env                              # re-enforce mode (paranoid)
```

Verify the file loads cleanly:

```bash
# Source in a subshell and confirm all 5 vars set
bash -c '. ~/.kbl.env && echo "$DATABASE_URL $ANTHROPIC_API_KEY" | \
    awk "{print NF, length(\$0)}"'
```

Expected: `2 <length>` where length is plausibly non-trivial (both vars set).

Then verify Python can actually connect to PG using the new secrets:

```bash
. ~/.kbl.env
/opt/homebrew/bin/python3 -c "
import os, psycopg2
conn = psycopg2.connect(os.environ['DATABASE_URL'])
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM signal_queue')
print('signal_queue rows:', cur.fetchone()[0])
conn.close()
"
```

**Expected output:** `signal_queue rows: <some integer>`.

**Failure triage:**

- `KeyError: 'DATABASE_URL'` → env var name typo in `~/.kbl.env`. Fix + re-source.
- `psycopg2.OperationalError: could not connect` → wrong URL. Re-copy from Render dashboard.
- `ModuleNotFoundError: No module named 'psycopg2'` → "Before you start" pip install skipped. Install deps, retry.

**Rollback:** `rm ~/.kbl.env` — template will be re-created on next install script run.

---

## Step 5 — Commit `config/env.mac-mini.yml` to baker-vault

**Precondition:** Steps 3-4 complete. You're on Director's MacBook (NOT Mac Mini) with Obsidian Git plugin + baker-vault clone at `~/Vallen Dropbox/Dimitry vallen/baker-vault` or wherever it lives. Alternative: edit directly via GitHub web UI.

**Action (MacBook Obsidian path — recommended):**

```bash
# Copy the example from baker-master (now on main after merge) to baker-vault.
cd ~/baker-vault                                  # path may vary
mkdir -p config
cp ~/Desktop/baker-code/config/env.mac-mini.yml.example config/env.mac-mini.yml

# Review the file — no secrets, but confirm these key values:
#   flags.pipeline_enabled: "false"   ← MUST be false for first tick
#   matter_scope.allowed: ["hagenauer-rg7"]   ← Phase 1 scope
#   ollama.model: "gemma4:latest"
#   ollama.fallback: "qwen2.5:14b"
#   pipeline.cron_interval_minutes: "2"
#   gold_promote.whitelist_wa_id: "41799605092@c.us"  ← Director's number

git add config/env.mac-mini.yml
git commit -m "feat(config): env.mac-mini.yml for KBL-A Phase 1"
git push origin main
```

**Expected output:** push successful, commit visible at `https://github.com/vallen300-bit/baker-vault/commits/main`.

**Verify Mac Mini pulls it on next tick (within 2 min):**

```bash
ssh macmini
cd ~/baker-vault
sleep 130
git log --oneline -1                              # should show new commit
ls -la config/env.mac-mini.yml
```

**Failure triage:**

- Push rejected (non-fast-forward) → `git pull --rebase origin main && git push`.
- Mac Mini doesn't pull within 2 min → pipeline tick may not be firing. Check `launchctl list | grep brisen.kbl.pipeline` shows a recent last-run time. Run `tail -20 /var/log/kbl/pipeline.log` to see what the tick actually did.
- Tick log shows `WARN: env.mac-mini.yml not present yet` even after pull → check yml is committed to `main`, not a branch. `git log main -- config/env.mac-mini.yml` from inside `~/baker-vault`.

**Rollback:** `git revert <commit>` in baker-vault + push. Mac Mini pulls the revert on next tick and reverts to WARN state.

---

## Step 6 — Verify first pipeline tick with pipeline_enabled=false

**Precondition:** Step 5 complete — yml committed to vault, Mac Mini pulled.

**Action:**

```bash
ssh macmini
tail -f /var/log/kbl/pipeline.log
# (wait up to 2 min for next tick, then Ctrl-C)
```

**Expected output:** lines similar to:

```
[2026-04-18T12:34:56Z] === tick start PID=12345 ===
[2026-04-18T12:34:57Z] config sync: pulled baker-vault @ <commit>
[2026-04-18T12:34:57Z] env: loaded KBL_* from env.mac-mini.yml
[2026-04-18T12:34:57Z] pipeline_enabled=false; exiting cleanly
```

Also verify heartbeat (runs every 30 min, NOT every tick):

```bash
tail -f /var/log/kbl/heartbeat.log
# wait up to 30 min after LaunchAgent load, or force:
launchctl start com.brisen.kbl.heartbeat

psql "$DATABASE_URL" -c \
    "SELECT value FROM kbl_runtime_state WHERE key='mac_mini_heartbeat'"
```

**Expected:** heartbeat value is an ISO-8601 timestamp within the last 30 min.

**Failure triage:**

- `pipeline.log` empty → LaunchAgent not firing. `launchctl list com.brisen.kbl.pipeline` shows PID 0, no last-exit-code. Re-load: `launchctl unload ... && launchctl load ...`.
- `yq: command not found` in log → PATH in plist missing `/opt/homebrew/bin`. Check `~/Library/LaunchAgents/com.brisen.kbl.pipeline.plist`'s `EnvironmentVariables`. Reinstall if corrupted.
- Log shows `ERROR: DATABASE_URL unset` → `~/.kbl.env` not being sourced. Check wrapper script has `[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"` near top.
- Log shows Python `ImportError` → "Before you start" pip install was skipped or failed. Re-do.

**Rollback:** (to undo all installed state, see step 3 rollback block). Usually not needed — failures are diagnosable from logs.

---

## Step 7 — Flip the pipeline flag

**Precondition:** Step 6 green (pipeline tick runs cleanly with `pipeline_enabled=false`). Director is ready to process real signals against `hagenauer-rg7` matter scope.

**Action (MacBook):**

```bash
cd ~/baker-vault
# Edit config/env.mac-mini.yml — change one line:
#   flags.pipeline_enabled: "false"     →     flags.pipeline_enabled: "true"

git add config/env.mac-mini.yml
git commit -m "chore(kbl-a): flip pipeline_enabled=true — Phase 1 go-live"
git push origin main
```

That's it. No manual reload trigger — Mac Mini's next 2-min tick pulls the change and begins processing.

**Expected output:**

Watch `tail -f /var/log/kbl/pipeline.log` on Mac Mini. Within 2 min:

```
[<timestamp>] === tick start PID=... ===
[<timestamp>] config sync: pulled baker-vault @ <flag-flip-commit>
[<timestamp>] pipeline_enabled=true; invoking python3 -m kbl.pipeline_tick
[<timestamp>] claimed signal <id> (source=email, matter=hagenauer-rg7)
[<timestamp>] tick end PID=...
```

Also verify `signal_queue` rows change state:

```bash
psql "$DATABASE_URL" -c \
    "SELECT status, COUNT(*) FROM signal_queue GROUP BY status ORDER BY status"
```

You should see a `processing` or `processed` row count that grows across successive queries. If no signals claim, check `matter_scope.allowed` includes signals that exist in the queue.

**Failure triage:**

- Log still says `pipeline_enabled=false` → Mac Mini didn't pull. Re-check step 5 failure triage.
- Python traceback on import → Python deps missing. "Before you start" was skipped.
- `ERROR: circuit open` at first tick → Anthropic API issue or key wrong. Check `ANTHROPIC_API_KEY` in `~/.kbl.env`.
- Cost-circuit fires immediately → daily cap may be too tight for first real signals. Check `cost.daily_cap_usd: "15"` in yml.

**Rollback (emergency — panic brakes):**

Immediate flag flip back:

```bash
cd ~/baker-vault
sed -i '' 's/pipeline_enabled: "true"/pipeline_enabled: "false"/' config/env.mac-mini.yml
git add config/env.mac-mini.yml
git commit -m "chore(kbl-a): EMERGENCY flip pipeline_enabled=false"
git push origin main
```

Pipeline stops at next tick (up to 2 min). For faster stop, SSH Mac Mini and unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.brisen.kbl.pipeline.plist
```

---

## Post-install sanity tests (optional, runs ~5 min)

Once step 7 is green and you want to verify the harder-to-hit paths:

### Gold drain end-to-end

```bash
# On Mac Mini:
echo "test gold drain" > ~/baker-vault/test-gold.md
cd ~/baker-vault && git add test-gold.md && git commit -m "test" && git push

psql "$DATABASE_URL" -c \
    "INSERT INTO gold_promote_queue (path, wa_msg_id) \
     VALUES ('test-gold.md', 'manual-test-20260418')"

# Wait ~4 min (2 gold-drain cron cycles), then:
cd ~/baker-vault && git log --oneline -3
# Expected: a commit by Director author promoting test-gold.md frontmatter.
```

### Cost threshold alerting

```bash
psql "$DATABASE_URL" -c \
    "INSERT INTO kbl_cost_ledger (model, signal_id, usd_estimate, usd_actual, tokens_in, tokens_out, called_at) \
     VALUES ('claude-opus-4-6', NULL, 12.0, 12.0, 1000, 500, NOW())"
# Should trigger 80% threshold alert — WhatsApp received once, dedupe in kbl_alert_dedupe.
```

### Heartbeat staleness

If you unload the heartbeat LaunchAgent and wait 31 min, you should get a WhatsApp "mac_mini_heartbeat stale" alert. Don't actually test this in production.

---

## If something fails that this runbook doesn't cover

1. Capture the failure signal (log lines, psql output, screenshot).
2. Stop the procedure at that step — do NOT proceed to the next.
3. File a report at `briefs/_reports/B1_kbl_a_install_<topic>_<date>.md`.
4. Dispatch to B1 (me) via chat — "B1: install blocked at step N, see <report path>".

The idempotent install script + single-transaction gold drain + R1-invariant logging mean most failures are recoverable without data loss. The most dangerous operator mistake is running step 7 before step 6 passes — that'd put a dependency-missing pipeline into production state. Don't.

---

## Pointers

- **Brief:** `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` (§6 install script, §13 deploy sequence, §14 acceptance)
- **Verification report:** `briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`
- **B1 invariants handover:** `briefs/_handovers/B1_20260417.md`
- **PR #1:** https://github.com/vallen300-bit/baker-master/pull/1
- **B2 approval:** `briefs/_reports/B2_pr1_reverify_20260417.md`

---

*Prepared 2026-04-18 by Code Brisen #1. Time-box ~1h met in-session.*
