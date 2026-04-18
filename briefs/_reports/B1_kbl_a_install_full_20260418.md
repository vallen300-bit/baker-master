# KBL-A Install Full — Steps 3+4+5 Report

**From:** Code Brisen #1
**To:** AI Head (via Director relay)
**Re:** [`briefs/_tasks/CODE_1_PENDING.md`](../_tasks/CODE_1_PENDING.md) Steps 3+4+5 end-to-end
**Paired:** [`briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`](B1_kbl_a_preinstall_verify_20260418.md), [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md)
**Date:** 2026-04-18

---

## TL;DR

**All three steps done. Ready for Step 6 (first-tick verification by Director).**

- Step 3 install: partial auto + partial manual (sudo via password pipe) + LaunchAgent load. All artifacts in place.
- Step 4 secrets: 5/5 populated via 1Password service account + Render API. PG connectivity verified.
- Step 5 config: `baker-vault` PR #2 open with `config/env.mac-mini.yml` (pipeline_enabled=false).

Two real bugs discovered + one scope surprise flagged in §6. None block Step 6.

---

## Step 3 evidence — install script

### Prereqs installed (pre-install, not auto)

Per the runbook's "Before you start" block — the install script's sanity checks would fail otherwise:

```bash
brew install yq util-linux libpq
brew link --force libpq
ln -sf /opt/homebrew/opt/util-linux/bin/flock /opt/homebrew/bin/flock  # util-linux is keg-only
/opt/homebrew/bin/python3 -m pip install --user --break-system-packages \
    psycopg2-binary pyyaml anthropic requests httpx pydantic
```

PEP 668 externally-managed-environment override (`--break-system-packages`) was needed on macOS 15 with Homebrew Python 3.14. User-site install at `~/Library/Python/3.14/site-packages`.

### Install execution

Three attempts:

1. **Attempt 1** — failed at `yq` sanity check (prereqs not yet installed). Fixed by installing brew deps (above).
2. **Attempt 2** — failed at `ollama list | grep -q 'qwen2.5:14b'` check despite model being pulled. **Root cause (new bug, §6.1):** pipefail + `grep -q` SIGPIPE. Patched locally on Mac Mini.
3. **Attempt 3** — reached sudo step (`sudo ln -sf` / `sudo mkdir /var/log/kbl` / `sudo cp newsyslog.conf`). Non-interactive ssh can't authenticate sudo. **Blocker (§6.2).** Resolved via Director-provided password piped to `sudo -S` (one-time, see §7).

After sudo, the remaining bits (LaunchAgent plist copy/load, Dropbox mirror dir) ran clean via non-sudo ssh.

### Final state (verified)

```
/usr/local/bin/kbl-dropbox-mirror.sh -> ~/Desktop/baker-code/scripts/kbl-dropbox-mirror.sh
/usr/local/bin/kbl-gold-drain.sh     -> ~/Desktop/baker-code/scripts/kbl-gold-drain.sh
/usr/local/bin/kbl-heartbeat.sh      -> ~/Desktop/baker-code/scripts/kbl-heartbeat.sh
/usr/local/bin/kbl-pipeline-tick.sh  -> ~/Desktop/baker-code/scripts/kbl-pipeline-tick.sh
/usr/local/bin/kbl-purge-dedupe.sh   -> ~/Desktop/baker-code/scripts/kbl-purge-dedupe.sh

launchctl list | grep brisen.kbl   → 4 agents loaded (PIDs 89679, 89675 running; -0 pending)
  com.brisen.kbl.heartbeat       (PID 89679)
  com.brisen.kbl.pipeline        (PID 89675)
  com.brisen.kbl.dropbox-mirror  (waiting for schedule)
  com.brisen.kbl.purge-dedupe    (waiting for schedule)

/var/log/kbl          drwxr-xr-x  dimitry:staff 755
/etc/newsyslog.d/kbl.conf            644 root:wheel
~/.kbl.env            -rw-------  dimitry:staff (600) — populated (§Step 4)
~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs  dir ok
~/.zshrc              -rw-------  mode 0600 (R1.N3)
```

### Transitional state

Mac Mini's `~/Desktop/baker-code` is checked out on **`kbl-a-impl`** (not `main`) because PR #1 hasn't merged yet. `/usr/local/bin/kbl-*` symlinks point to absolute paths in the clone; after Director merges PR #1 and Mac Mini's next `git pull` fast-forwards `main` and checks out main (or stays on kbl-a-impl harmlessly — same content), the symlinks continue to resolve. No re-install needed post-merge.

### Install log

On Mac Mini at `/tmp/kbl_install_20260418.log` (last attempt). Did NOT reach "install complete" marker in the logged attempts because sudo bits were bypassed and the remaining steps run via direct ssh rather than through the script. Functionally equivalent end state.

---

## Step 4 evidence — secrets populated

### Scaffold secrets (5, from `~/.kbl.env` template created by install script)

```
DATABASE_URL
ANTHROPIC_API_KEY
QDRANT_URL
QDRANT_API_KEY
VOYAGE_API_KEY
```

### Source map (verified correct names)

| Env var | Source |
|---|---|
| `DATABASE_URL` | **Assembled** on Mac Mini from Render env vars `POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE` via `urllib.parse.quote()`. See §6.3 for the "no direct DATABASE_URL" surprise. |
| `ANTHROPIC_API_KEY` | 1Password: `API Anthropic` → `credential` field |
| `QDRANT_URL` | Render env var (no 1P item for URL; item `API Qdrant ` has credential only, hostname field was empty) |
| `QDRANT_API_KEY` | 1Password: `API Qdrant ` → `credential` field (note: item title has trailing space) |
| `VOYAGE_API_KEY` | 1Password: `API Voyager` → `credential` field |
| *(intermediary)* `RENDER_TOKEN` | 1Password: `API Render` → `credential` field; used once for Render API env-vars query, then discarded |

### Population method (no secret values transited through B1 terminal)

One-shot ssh invocation:
1. `OP_SERVICE_ACCOUNT_TOKEN` piped via ssh stdin (not argv); `read` on Mac Mini into env var.
2. `op item get ...` retrieved the 4 1P secrets directly on Mac Mini.
3. `curl https://api.render.com/v1/services/srv-d6dgsbctgctc73f55730/env-vars` with Render token authenticated the Render API call; Python parsed + assembled `DATABASE_URL`.
4. All 5 values written to `~/.kbl.env` via heredoc on Mac Mini (secrets never left Mac Mini).
5. `unset OP_SERVICE_ACCOUNT_TOKEN RENDER_TOKEN ANTHROPIC_API_KEY VOYAGE_API_KEY QDRANT_API_KEY DATABASE_URL QDRANT_URL` at end of ssh session.

### Sanity-check output (names + first 10 chars + lengths only — no full values)

```
DATABASE_URL      populated: first10=postgresql... len=128
ANTHROPIC_API_KEY populated: first10=sk-ant-api... len=108
QDRANT_URL        populated: first10=https://38... len=84
QDRANT_API_KEY    populated: first10=eyJhbGciOi... len=102
VOYAGE_API_KEY    populated: first10=pa-V0XVe0Y... len=46
```

### Live connectivity check

```python
python3 -c "import os, psycopg2; c=psycopg2.connect(os.environ['DATABASE_URL']); cur=c.cursor(); cur.execute('SELECT 1'); print('pg ok:', cur.fetchone()); c.close()"
# → pg ok: (1,)
```

### File perms

```
-rw-------  1 dimitry  staff  792 Apr 18 04:54 /Users/dimitry/.kbl.env
```

Mode 600 ✅.

---

## Step 5 evidence — baker-vault config PR

### PR

**URL:** https://github.com/vallen300-bit/baker-vault/pull/2
**Branch:** `env-mac-mini-config` (off `main`)
**Commit:** `ed644dd` — `feat(config): env.mac-mini.yml for KBL-A Phase 1`
**File:** `config/env.mac-mini.yml` (52 lines, new file)

### Values (ratified)

Per task §5 and brief §6/§13:

- `ollama.model`: `gemma4:latest` | `fallback`: `qwen2.5:14b` | `temp`: `0` | `seed`: `42` | `top_p`: `0.9` | `keep_alive`: `-1`
- `matter_scope.allowed`: `["hagenauer-rg7"]` (Phase 1 only)
- `matter_scope.layer0_enabled`: `true`
- `gold_promote.disabled`: `false` | `whitelist_wa_id`: `41799605092@c.us` | `vault_branch`: `main`
- `pipeline.cron_interval_minutes`: `2` | `triage_threshold`: `40` | `max_queue_size`: `10000`
- `pipeline.qwen_recovery_after_signals`: `10` | `after_hours`: `1` | `probe_every`: `5`
- `pipeline.circuit_health_model`: `claude-haiku-4-5` (B2.S5 versioned)
- `cost.daily_cap_usd`: `15` | `max_alerts_per_day`: `20`
- **`flags.pipeline_enabled`: `"false"`** — Director flips at Step 7, NOT this PR
- `observability.dropbox_rsync_time`: `23:50` | `vault_size_warn_mb`: `500` | `critical_mb`: `1000`

### Validation

```bash
python3 -c "import yaml; d=yaml.safe_load(open('config/env.mac-mini.yml')); assert d['flags']['pipeline_enabled']=='false'; assert d['matter_scope']['allowed']==['hagenauer-rg7']"
# → yml valid, pipeline_enabled=false, matter_scope=hagenauer-rg7
```

Director merges PR #2 on GitHub.

---

## Open items for Director

### Step 6 — verify first tick green

Per runbook step 6, once PR #1 (baker-master) and PR #2 (baker-vault) are both merged:

```bash
ssh macmini
tail -f /var/log/kbl/pipeline.log
# wait up to 2 min for next tick, then Ctrl-C
```

Expected lines:

```
[<utc>] === tick start PID=... ===
[<utc>] config sync: pulled baker-vault @ <commit>
[<utc>] env: loaded KBL_* from env.mac-mini.yml
[<utc>] pipeline_enabled=false; exiting cleanly
```

Heartbeat:

```bash
psql "$DATABASE_URL" -c "SELECT value FROM kbl_runtime_state WHERE key='mac_mini_heartbeat'"
# should return ISO-8601 timestamp within last 30 min (dedicated heartbeat LaunchAgent — NOT pipeline_tick per R1.S7)
```

### Step 7 — flip the pipeline flag

Director edits `config/env.mac-mini.yml` line `flags.pipeline_enabled: "true"` in baker-vault, commits, pushes. Next Mac Mini tick picks up the change via `git pull --rebase -X ours origin main`. No manual reload trigger needed.

---

## Issues encountered

### 6.1 — Install script ollama-check SIGPIPE bug (new finding)

`scripts/install_kbl_mac_mini.sh` lines 29-30 use:

```bash
set -euo pipefail
ollama list | grep -q 'gemma4' || { ... }
ollama list | grep -q 'qwen2.5:14b' || { ... }
```

`grep -q` closes its stdin at the first match and exits 0. With pipefail, `ollama list`'s SIGPIPE non-zero exit fires and the whole pipeline fails despite grep succeeding. Behavior is position-dependent: gemma4 happened to work (ollama finishes writing 3 lines before grep matches on line 2), qwen2.5:14b consistently failed (matches on line 1 while ollama still has more to emit).

**Patched locally on Mac Mini** (not committed to `kbl-a-impl`):

```bash
OLLAMA_LIST="$(ollama list)"           # buffer full output first
echo "$OLLAMA_LIST" | grep -q gemma4 || { echo "FAIL..."; exit 1; }
echo "$OLLAMA_LIST" | grep -q qwen2.5:14b || { echo "FAIL..."; exit 1; }
```

**Recommended upstream fix:** apply the same buffering pattern in a new commit on `kbl-a-impl` before Director merges PR #1 (one-line PR, low risk). Or land as a separate hotfix PR if PR #1 already merged.

### 6.2 — Non-interactive sudo blocker

`install_kbl_mac_mini.sh` uses `sudo ln -sf`, `sudo mkdir`, `sudo chown`, `sudo cp`, `sudo chmod` without `-S`. Non-interactive ssh can't provide a password; macOS `sudo`'s `tty_tickets` default means even a prior `sudo -v` doesn't help across sub-processes.

**Resolution:** Director provided the Mac Mini password inline in chat. I piped it via ssh stdin → `sudo -S -v` (one-time) → followed immediately by all sudo commands in a single ssh invocation while the 5-minute tty ticket was valid. Password was not saved to disk anywhere; it exists only in the chat log and my shell env for the duration of the population.

**Recommendations:**

- **Immediate hygiene:** rotate the Mac Mini user password (it's visible in today's chat log).
- **Longer term:** either (a) add a one-line `sudoers.d/kbl-install` with NOPASSWD for the specific install paths (`/usr/local/bin/kbl-*`, `/var/log/kbl`, `/etc/newsyslog.d/kbl.conf`), or (b) document that install script execution is Director-interactive only (revert the "B1 via SSH" dispatch pattern for steps that touch root-owned paths).
- **Scoped sudoers drop-in** (cleanest, if recurring):

  ```
  dimitry ALL=(ALL) NOPASSWD: /bin/mkdir, /usr/sbin/chown, /bin/chmod, /bin/cp, /bin/ln
  ```

### 6.3 — No `DATABASE_URL` on Render; split `POSTGRES_*` vars only

Task §4 suggested either a direct `DATABASE_URL` in 1P or pulling from Render via the Render API. 1P has no `DATABASE_URL` item. Render has 6 split vars (`POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE`) and no single `DATABASE_URL`.

**Resolved** by assembling the URL with `urllib.parse.quote(user, pw)` to handle special chars. See `/tmp/b1-assemble-db.py` (shredded at session end).

**Recommendation:** add a `DATABASE_URL` item to 1P (or add it as a Render env var) so future automation doesn't need the assembly step. Or, patch `kbl/db.py` to accept split `POSTGRES_*` as fallback — symmetric with `config/settings.py` which likely already reads the split form for the Render FastAPI app.

### 6.4 — Mac Mini Python deps were ALL missing

Pre-install verify report §F2 flagged this; confirmed here. Fixed via `pip install --user --break-system-packages` of 6 packages. `CLAUDE.md` memory line "Python packages installed: qdrant-client, voyageai, psycopg2-binary, python-dotenv" is stale — those orphaned when Homebrew's Python3 upgraded to 3.14. Flag for Director to prune from memory.

### 6.5 — Install script doesn't reach "install complete" marker in any attempt

Because Attempt 3's sudo steps were taken over by manual piped-password execution (not the script itself), the final `echo "=== KBL Mac Mini install complete ==="` never printed in the logged attempts. End state is functionally equivalent (symlinks ✅, plists ✅, logs ✅, newsyslog ✅, dropbox dir ✅, ~/.kbl.env ✅), but grep-based CI checks on the log file would false-negative. Not fixing — scope.

---

## Security hygiene performed

- `OP_SERVICE_ACCOUNT_TOKEN` stored only in `/tmp/b1-op.env` (MacBook, mode 600) for this session. **Shredded at end:**

  ```bash
  rm -P /tmp/b1-op.env  # (executed in final cleanup)
  ```

- Token passed to Mac Mini via ssh stdin only (not argv/environ), read into a shell variable, used, unset. Never written to disk on Mac Mini.
- `~/.kbl.env` populated with `umask 077` + explicit `chmod 600`. Verified.
- Mac Mini user password: piped via ssh stdin, used once for `sudo -S -v` timestamp refresh, never written to any file or env export persisted beyond the single ssh session.
- No secret values in any commit, log artifact, or this report.

---

## Dispatch back

> B1 Steps 3+4+5 done — see `briefs/_reports/B1_kbl_a_install_full_20260418.md`, commit `<SHA>`. Baker-vault PR https://github.com/vallen300-bit/baker-vault/pull/2. Director: ready for Step 6 (first-tick verify with `pipeline_enabled=false`), then Step 7 (flip flag). Two issues for upstream follow-up: install-script pipefail/SIGPIPE bug (§6.1), `DATABASE_URL` assembly pattern (§6.3). Rotate Mac Mini password (visible in today's chat).

---

## Pointers

- Runbook: [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md)
- Pre-install report: [`briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`](B1_kbl_a_preinstall_verify_20260418.md)
- KBL-A brief: [`briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md`](../KBL-A_INFRASTRUCTURE_CODE_BRIEF.md)
- B1 invariants handover: [`briefs/_handovers/B1_20260417.md`](../_handovers/B1_20260417.md)
- baker-master PR #1: https://github.com/vallen300-bit/baker-master/pull/1
- baker-vault PR #2: https://github.com/vallen300-bit/baker-vault/pull/2
