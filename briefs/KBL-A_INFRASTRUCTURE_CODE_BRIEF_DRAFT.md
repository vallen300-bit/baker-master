# KBL-A — Infrastructure Code Brief (DRAFT)

**Status:** DRAFT — pending Code Brisen architecture review + Director ratification
**Ratified decisions source:** [`briefs/DECISIONS_PRE_KBL_A_V2.md`](DECISIONS_PRE_KBL_A_V2.md) (15 decisions, ratified 2026-04-17)
**Pre-staged artifacts:**
- `briefs/_drafts/KBL_A_SCHEMA.sql` (schema DDL)
- `briefs/_drafts/200-hardening.conf` + `SSH_HARDENING_PROCEDURE.md`
- `briefs/_drafts/KBL_EVAL_SET_PLAYBOOK.md` (pending vocab update)
- `scripts/build_eval_seed.py`, `validate_eval_labels.py`, `run_kbl_eval.py`
**Date:** 2026-04-17
**Prepared by:** AI Head (Claude Opus 4.7)
**Target executor:** Code Brisen (CLI harness, 1M context)
**Estimated build time:** 12-16 hours (recalibrated from earlier 6-8 h after v2.3 scope growth)

---

## 1. Context & Purpose

KBL (Knowledge Base Layer) is Baker's compiled-wiki knowledge architecture replacing RAG for 28-matter business operations. KBL-A is the **infrastructure foundation** — schema, Mac Mini runtime, config deployment, pipeline wrapper, Gold-promote worker, retry + cost + logging subsystems. KBL-A does NOT implement the pipeline's 8-step processing logic (that's KBL-B) or the interface layer (that's KBL-C).

**Architecture:** 3-tier (Render Tier-1 for signal capture + queue; Mac Mini Tier-2 for pipeline + vault writes; Director Tier-3 for Gold promotions via WhatsApp). Per Cortex 3T design.

**Scope of KBL-A:**
- Schema migrations on Render (5 new tables, signal_queue additions)
- Mac Mini install script + LaunchAgents + flock mutex wrapper
- Config deployment via `~/baker-vault/config/env.mac-mini.yml` + yq sourcing
- Gold-promote queue drain worker (WhatsApp `/gold` → PG queue → Mac Mini drain)
- Retry + circuit breaker + runtime state persistence
- Cost tracking (`kbl_cost_ledger`) + daily cap enforcement
- Logging (local rotating + PG WARN+ + Dropbox mirror) + alert dedupe + heartbeat

**Out of scope for KBL-A** (later briefs):
- KBL-B: 8-step pipeline logic (Layer 0 → Triage → Resolve → Extract → Classify → Opus → Sonnet → Commit)
- KBL-C: WhatsApp handlers, ayoniso alerts, dashboard extensions
- Gemma prompt engineering (uses existing `scripts/benchmark_ollama_triage.py` pattern)

---

## 2. Deliverables Checklist

### New database tables (via `_ensure_*` on Render)
- [ ] `kbl_runtime_state` (key-value, seeded with 6 flag keys)
- [ ] `kbl_cost_ledger` (per-call cost + tokens + latency)
- [ ] `kbl_log` (WARN+ centralized)
- [ ] `kbl_alert_dedupe` (5-min bucket dedupe for CRITICAL alerts + 80%/95%/100% cost alerts)
- [ ] `gold_promote_queue` (WhatsApp-originated Gold promotions)

### signal_queue additive migration
- [ ] `primary_matter TEXT`, `related_matters JSONB`, `triage_confidence NUMERIC(3,2)`
- [ ] Expanded `status` CHECK: `classified-deferred`, `failed-reviewed`, `cost-deferred`
- [ ] 3 new indexes

### Mac Mini scripts (baker-master repo)
- [ ] `scripts/install_kbl_mac_mini.sh` — one-time installer
- [ ] `scripts/kbl-pipeline-tick.sh` — flock-wrapped cron entry point
- [ ] `scripts/kbl-gold-drain.sh` — Gold promote worker
- [ ] `scripts/kbl-heartbeat.sh` — 30-min heartbeat ping
- [ ] `scripts/kbl-dropbox-mirror.sh` — daily log rsync
- [ ] `scripts/kbl-purge-dedupe.sh` — nightly alert dedupe purge

### Mac Mini configuration
- [ ] `launchd/com.brisen.kbl.pipeline.plist` (periodic `kbl-pipeline-tick.sh`)
- [ ] `launchd/com.brisen.kbl.heartbeat.plist` (every 30 min)
- [ ] `launchd/com.brisen.kbl.dropbox-mirror.plist` (daily 23:50 Europe/Vienna)
- [ ] `launchd/com.brisen.kbl.purge-dedupe.plist` (nightly 03:15 Europe/Vienna)
- [ ] `config/newsyslog-kbl.conf` (log rotation template Director installs to `/etc/newsyslog.d/`)

### Python module (pipeline orchestrator — imported by `kbl-pipeline-tick.sh` via `python3 -m`)
- [ ] `kbl/__init__.py`
- [ ] `kbl/pipeline_tick.py` — cron entry orchestrator (claims 1 signal via FOR UPDATE SKIP LOCKED, dispatches to KBL-B stub)
- [ ] `kbl/gold_drain.py` — drains `gold_promote_queue`, commits to vault, pushes
- [ ] `kbl/config.py` — reads env vars from `env.mac-mini.yml`-sourced shell env
- [ ] `kbl/retry.py` — retry ladders + circuit breaker
- [ ] `kbl/cost.py` — pre-call estimation + post-call logging + cap enforcement
- [ ] `kbl/logging.py` — tiered logging (local file + PG WARN+ + CRITICAL alerts with dedupe)
- [ ] `kbl/runtime_state.py` — key-value access to `kbl_runtime_state`
- [ ] `kbl/heartbeat.py` — updates `mac_mini_heartbeat` key

### Baker-vault repo additions (separate PR on `vallen300-bit/baker-vault`)
- [ ] `config/env.mac-mini.yml` (template with Phase 1 defaults)
- [ ] `.git/hooks/commit-msg` (enforces Baker Pipeline identity can't touch `author: director` files)

### Acceptance tests
- [ ] End-to-end: insert test row into `gold_promote_queue`, verify Mac Mini drains within 2 cron cycles, commit lands on `main` with Director identity
- [ ] Cost-circuit: force `DAILY_COST_CAP=0.01`, verify pipeline marks signal `cost-deferred` without calling API
- [ ] Anthropic-circuit: mock 3× 5xx in a row, verify circuit opens, health-check clears after 10 min
- [ ] Flock mutex: start two `kbl-pipeline-tick.sh` simultaneously, verify second exits immediately without touching PG
- [ ] Heartbeat: run 45 min, verify `kbl_runtime_state.mac_mini_heartbeat` updated ≤30 min stale
- [ ] Alert dedupe: emit 10× identical CRITICAL in 2 min, verify 1 WhatsApp sent

---

## 3. Prerequisites (Director-owned + Code-verified before dispatch)

### Director-owned (before KBL-A dispatch) — ~30 min total
- [ ] **D1 pre-shadow eval completed:** Director runs `build_eval_seed.py` → labels 50 signals (~55 min — not blocking KBL-A dispatch, but blocks D1 ratification which must precede shadow go-live) → `validate_eval_labels.py` → `run_kbl_eval.py --compare-qwen`. Acceptance: Gemma ≥90% vedanā + 100% JSON + ≥85% per-source. If fail, KBL-A brief still ships but D1 reverts to option B.
- [ ] **SSH hardening applied** on Mac Mini per `briefs/_drafts/SSH_HARDENING_PROCEDURE.md` (~5 min — not blocking KBL-A dispatch, but required before production)
- [ ] **Obsidian Git plugin** installed on MacBook with `auto-commit-interval=300`, `auto-push=true` (~10 min)
- [ ] **Mac Mini system TZ:** verify `sudo systemsetup -gettimezone` = `Europe/Vienna`; set if not
- [ ] **FileVault** on Mac Mini (verify `fdesetup status` = `FileVault is On`) — mitigating control for deferred secret rotation per D4 override

### Code Brisen verifies (in dispatch session) — ~15 min total
- [ ] `brew install yq` present and `yq --version` ≥ 4.0 on Mac Mini
- [ ] `brew install flock` (macOS `flock` is BSD variant; Homebrew provides GNU `flock` via `util-linux`)
- [ ] SSH to macmini works via `ssh macmini` (Tailscale path)
- [ ] `git -C ~/baker-vault status` clean on Mac Mini (no uncommitted cruft from prior experiments)
- [ ] Ollama `gemma4:latest` loaded, Metal backend confirmed (`ollama run gemma4:latest "ok" --verbose 2>&1 | grep -iE "metal|gpu"`)
- [ ] Qwen 2.5 14B pulled, `ollama list` shows it
- [ ] `baker-master` repo cloned at `~/Desktop/baker-code` on Mac Mini (or equivalent path — install script reads `REPO` env)

---

## 4. Architecture Overview

```
                    ┌───────────────────────────────────────┐
                    │ Render (Tier 1 — always-on)           │
                    │                                       │
WhatsApp ─ WAHA ──► │  - Signal sentinels (email/WA/etc)   │
(Director /gold)    │  - signal_queue (Neon PG)            │
                    │  - gold_promote_queue                 │
                    │  - kbl_runtime_state / ledger / log   │
                    │  - Dashboard (KBL-C reads)            │
                    └──────────────┬────────────────────────┘
                                   │ Tailscale (direction:
                                   │ Mac Mini pulls, never pushed-to)
                    ┌──────────────▼────────────────────────┐
                    │ Mac Mini (Tier 2 — vault writer)     │
                    │                                       │
                    │  launchd:                             │
                    │   - kbl.pipeline  (every 2 min)       │
                    │   - kbl.heartbeat (every 30 min)      │
                    │   - kbl.dropbox-mirror (23:50 daily)  │
                    │   - kbl.purge-dedupe (03:15 daily)    │
                    │                                       │
                    │  flock /tmp/kbl-pipeline.lock:        │
                    │   1. git pull --rebase -X ours        │
                    │   2. source env.mac-mini.yml via yq   │
                    │   3. drain gold_promote_queue         │
                    │   4. claim 1 signal_queue row         │
                    │   5. run KBL-B pipeline (future)      │
                    │   6. commit + push wiki writes        │
                    │                                       │
                    │  Ollama (Metal):                      │
                    │   - gemma4:latest (keep-alive -1)     │
                    │   - qwen2.5:14b (cold-swap fallback)  │
                    └──────────────┬────────────────────────┘
                                   │ git push (wiki + Gold)
                    ┌──────────────▼────────────────────────┐
                    │ GitHub: vallen300-bit/baker-vault    │
                    │  - raw/transcripts/ (append-only)    │
                    │  - wiki/**/*.md (Silver + Gold)      │
                    │  - config/env.mac-mini.yml            │
                    │  - schema/ (templates)               │
                    └──────────────┬────────────────────────┘
                                   │ Director Obsidian
                                   │ + Git plugin auto-push
                    ┌──────────────▼────────────────────────┐
                    │ Director MacBook (Tier 3 — Gold)     │
                    │  - Obsidian with Git plugin          │
                    │  - WhatsApp /gold commands           │
                    └───────────────────────────────────────┘
```

**Data flows:**
- **Signal enqueue:** Render sentinels insert → `signal_queue` (this flow already exists pre-KBL).
- **Pipeline drain:** Mac Mini cron → `FOR UPDATE SKIP LOCKED` claim → process → wiki write → commit → push.
- **Gold promote:** WhatsApp → WAHA/Render → `gold_promote_queue` INSERT → Mac Mini cron drains → frontmatter edit → commit with Director identity → push.
- **Runtime state:** PG `kbl_runtime_state` visible to both Render (for circuit breaker checks) and Mac Mini (for circuit + heartbeat).
- **Config:** Director edits `config/env.mac-mini.yml` on MacBook Obsidian → git auto-push → Mac Mini cron pulls → yq sources → next signal uses new values.

---

## 5. Phase 1 — Schema Migrations (Render)

### Execution
Code Brisen references `briefs/_drafts/KBL_A_SCHEMA.sql` (pre-staged by Code Brisen #2 at commit `c275ffe`). Wraps into `_ensure_*` methods under `memory/store_back.py` (or equivalent SentinelStoreBack pattern).

### FK type reconciliation (resolves pre-staged caveat)

The pre-staged schema declares `signal_id BIGINT` without FK. v2.3 D14 specifies `INTEGER` to match `signal_queue.id SERIAL`.

**Decision locked here:** keep `signal_queue.id = SERIAL (INTEGER)` (no bump to BIGSERIAL — INT max 2.1B signals is decades of headroom at Phase 1 scale). Update pre-staged schema:

```sql
-- kbl_cost_ledger.signal_id: BIGINT → INTEGER, add FK with ON DELETE SET NULL
ALTER TABLE kbl_cost_ledger ALTER COLUMN signal_id TYPE INTEGER;
ALTER TABLE kbl_cost_ledger
    ADD CONSTRAINT fk_cost_ledger_signal
    FOREIGN KEY (signal_id) REFERENCES signal_queue(id) ON DELETE SET NULL;

-- kbl_log.signal_id: same
ALTER TABLE kbl_log ALTER COLUMN signal_id TYPE INTEGER;
ALTER TABLE kbl_log
    ADD CONSTRAINT fk_kbl_log_signal
    FOREIGN KEY (signal_id) REFERENCES signal_queue(id) ON DELETE SET NULL;
```

**Why `ON DELETE SET NULL`:** when a signal is purged from `signal_queue` (30-day TTL on `done`/`classified-deferred`), its cost and log rows stay for rollups. We lose the per-signal join but keep the aggregate cost/log data.

### Additional table introduced here (not in pre-staged schema)

```sql
-- kbl_alert_dedupe — suppresses duplicate CRITICAL alerts (D15) + cost thresholds (D14 S8)
CREATE TABLE IF NOT EXISTS kbl_alert_dedupe (
    alert_key   TEXT PRIMARY KEY,             -- e.g., 'cost_80pct_2026-04-17' or '<component>_<msg_hash_16>_<bucket>'
    first_seen  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_sent   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    send_count  INTEGER NOT NULL DEFAULT 1
);
-- No auto-purge DDL — nightly purge is Mac Mini scheduled task (kbl-purge-dedupe.sh)
```

### Acceptance for Phase 1
- Render deploys KBL-A PR → logs show `_ensure_kbl_runtime_state`, `_ensure_kbl_cost_ledger`, `_ensure_kbl_log`, `_ensure_kbl_alert_dedupe`, `_ensure_gold_promote_queue`, `_ensure_signal_queue_additions` all executed without error
- Manual verification via `psql`: `\d kbl_runtime_state` returns 4 columns; `SELECT COUNT(*) FROM kbl_runtime_state` returns 6 (seeded keys); `\d kbl_cost_ledger` shows FK constraint present; `\d signal_queue` shows new columns + expanded CHECK
- NO Mac Mini work begins until Render deploy green

---

## 6. Phase 2 — Mac Mini Install Script

### `scripts/install_kbl_mac_mini.sh`

```bash
#!/bin/bash
# install_kbl_mac_mini.sh — one-time KBL Mac Mini installer
# Owner: Director (via SSH) or Code Brisen at dispatch
# Idempotent: can re-run after code updates (symlinks stay current)

set -euo pipefail

REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
VAULT="${KBL_VAULT:-${HOME}/baker-vault}"
TARGET_BIN="/usr/local/bin"
LAUNCHD_DIR="${HOME}/Library/LaunchAgents"

# --- Sanity checks ---
[ -d "${REPO}" ] || { echo "FAIL: ${REPO} not found. Set KBL_REPO or clone baker-master there."; exit 1; }
[ -d "${VAULT}" ] || { echo "FAIL: ${VAULT} not found. Clone baker-vault."; exit 1; }

command -v yq >/dev/null 2>&1 || { echo "FAIL: yq not installed. Run: brew install yq"; exit 1; }
command -v flock >/dev/null 2>&1 || { echo "FAIL: flock not installed. Run: brew install util-linux"; exit 1; }
command -v ollama >/dev/null 2>&1 || { echo "FAIL: ollama not installed."; exit 1; }

ollama list | grep -q 'gemma4' || { echo "FAIL: gemma4 not pulled. Run: ollama pull gemma4:latest"; exit 1; }
ollama list | grep -q 'qwen2.5:14b' || { echo "FAIL: qwen2.5:14b not pulled. Run: ollama pull qwen2.5:14b"; exit 1; }

# --- 1. Symlink pipeline scripts ---
for script in kbl-pipeline-tick.sh kbl-gold-drain.sh kbl-heartbeat.sh kbl-dropbox-mirror.sh kbl-purge-dedupe.sh; do
    sudo ln -sf "${REPO}/scripts/${script}" "${TARGET_BIN}/${script}"
    sudo chmod +x "${REPO}/scripts/${script}"
done

# --- 2. Install LaunchAgent plists ---
mkdir -p "${LAUNCHD_DIR}"
for plist in com.brisen.kbl.pipeline com.brisen.kbl.heartbeat com.brisen.kbl.dropbox-mirror com.brisen.kbl.purge-dedupe; do
    cp "${REPO}/launchd/${plist}.plist" "${LAUNCHD_DIR}/${plist}.plist"
    launchctl unload "${LAUNCHD_DIR}/${plist}.plist" 2>/dev/null || true
    launchctl load "${LAUNCHD_DIR}/${plist}.plist"
done

# --- 3. Create log dir (requires sudo) ---
if [ ! -d "/var/log/kbl" ]; then
    echo "Creating /var/log/kbl (requires sudo)..."
    sudo mkdir -p /var/log/kbl
    sudo chown "${USER}:staff" /var/log/kbl
    sudo chmod 755 /var/log/kbl
fi

if [ ! -f "/etc/newsyslog.d/kbl.conf" ]; then
    echo "Installing /etc/newsyslog.d/kbl.conf (requires sudo)..."
    sudo cp "${REPO}/config/newsyslog-kbl.conf" /etc/newsyslog.d/kbl.conf
    sudo chmod 644 /etc/newsyslog.d/kbl.conf
fi

# --- 4. Dropbox mirror dir ---
DROPBOX_DIR="${HOME}/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs"
[ -d "${DROPBOX_DIR}" ] || mkdir -p "${DROPBOX_DIR}"

# --- 5. Validate ---
echo ""
echo "=== KBL Mac Mini install complete ==="
echo "Scripts in ${TARGET_BIN}:"
ls -la "${TARGET_BIN}"/kbl-* 2>/dev/null || echo "  (none symlinked)"
echo "LaunchAgents loaded:"
launchctl list | grep brisen.kbl || echo "  (none loaded)"
echo "Log dir:"
ls -la /var/log/kbl
echo ""
echo "Next: verify env.mac-mini.yml exists at ${VAULT}/config/env.mac-mini.yml"
echo "Then trigger first pipeline tick: launchctl start com.brisen.kbl.pipeline"
```

### `config/newsyslog-kbl.conf`

```
# Rotates /var/log/kbl/pipeline.log and related KBL logs
# Columns: filename mode count size(kb) when flags
/var/log/kbl/pipeline.log   644  7  10240  *  J
/var/log/kbl/gold-drain.log 644  7  10240  *  J
/var/log/kbl/heartbeat.log  644  7   1024  *  J
```

### Acceptance for Phase 2
- Run `install_kbl_mac_mini.sh` on clean-ish Mac Mini → exit 0
- `ls /usr/local/bin/kbl-*` shows 5 symlinks
- `launchctl list | grep brisen.kbl` shows 4 agents loaded
- `/var/log/kbl/` exists, owned by dimitry, mode 755
- Re-run idempotent (no errors, no duplicate LaunchAgents)

---

## 7. Phase 3 — Config Deployment (`env.mac-mini.yml` + yq sourcing)

### `config/env.mac-mini.yml` (in baker-vault repo, committed separately)

```yaml
# Mac Mini KBL pipeline config (tunables only — NO SECRETS)
# Secrets stay in ~/.zshrc (or op:// post-Phase 1 per D4 override)
# Director edits on MacBook Obsidian → git auto-push → Mac Mini cron pulls

ollama:
  model: "gemma4:latest"
  fallback: "qwen2.5:14b"
  temp: "0"
  seed: "42"
  top_p: "0.9"
  keep_alive: "-1"

matter_scope:
  allowed: ["hagenauer-rg7"]              # Phase 1 only
  layer0_enabled: "true"
  newsletter_blocklist: []
  wa_blocklist: []

gold_promote:
  disabled: "false"
  whitelist_wa_id: "41799605092@c.us"

pipeline:
  cron_interval_minutes: "2"              # TBD post-bench (D5)
  triage_threshold: "40"
  max_queue_size: "10000"
  qwen_recovery_after_signals: "10"
  qwen_recovery_after_hours: "1"

cost:
  daily_cap_usd: "15"
  max_alerts_per_day: "20"

flags:
  pipeline_enabled: "false"               # flipped true at Phase 1 go-live

observability:
  dropbox_rsync_time: "23:50"
  vault_size_warn_mb: "500"
  vault_size_critical_mb: "1000"
```

### yq sourcing in `kbl-pipeline-tick.sh` wrapper (partial — full wrapper in Phase 4)

```bash
# Step 2 of wrapper (after git pull):
eval "$(yq -r '
  [paths(scalars, arrays) as $p |
    select($p | last | type != "number") |
    "export KBL_" + ($p | map(. | ascii_upcase) | join("_")) + "=" +
    (getpath($p) |
      if type == "array" then join(",") else tostring end
    )
  ] | .[]
' "${VAULT}/config/env.mac-mini.yml")"
```

Produces flat env:
- `KBL_OLLAMA_MODEL=gemma4:latest`
- `KBL_MATTER_SCOPE_ALLOWED=hagenauer-rg7`
- `KBL_PIPELINE_CRON_INTERVAL_MINUTES=2`
- ... etc.

### `kbl/config.py` — Python read helper

```python
"""Reads KBL config from yq-sourced shell env.
List-typed values are comma-split."""

import os

def cfg(key: str, default: str = "") -> str:
    """Get scalar config value."""
    return os.getenv(f"KBL_{key.upper()}", default)

def cfg_list(key: str, default: list[str] | None = None) -> list[str]:
    """Get comma-separated list config value. Empty string → empty list."""
    raw = os.getenv(f"KBL_{key.upper()}", "")
    if not raw:
        return default or []
    return [x.strip() for x in raw.split(",") if x.strip()]

def cfg_bool(key: str, default: bool = False) -> bool:
    """Get boolean config value (accepts 'true'/'false' case-insensitive)."""
    raw = os.getenv(f"KBL_{key.upper()}", "").lower()
    if not raw:
        return default
    return raw in ("true", "1", "yes")

def cfg_int(key: str, default: int = 0) -> int:
    try:
        return int(os.getenv(f"KBL_{key.upper()}", ""))
    except (ValueError, TypeError):
        return default

def cfg_float(key: str, default: float = 0.0) -> float:
    try:
        return float(os.getenv(f"KBL_{key.upper()}", ""))
    except (ValueError, TypeError):
        return default
```

### Acceptance for Phase 3
- `test_env_yml_flatten.sh` runs sample yml → asserts expected flat env output (no stray `_0`, `_1` indices from arrays)
- `python3 -c "from kbl.config import cfg, cfg_list, cfg_bool; print(cfg('ollama_model'), cfg_list('matter_scope_allowed'), cfg_bool('gold_promote_disabled'))"` returns expected values
- Director edits `env.mac-mini.yml` on MacBook → auto-push → Mac Mini pulls → next cron sees updated value (manual end-to-end test)

---

## 8. Phase 4 — Pipeline Wrapper (flock + cron + Python orchestrator)

### `scripts/kbl-pipeline-tick.sh`

```bash
#!/bin/bash
# kbl-pipeline-tick.sh — cron entry, flock-wrapped
# Invoked by launchd every KBL_CRON_INTERVAL_MINUTES
# Exits immediately if lock held (next tick retries)

set -euo pipefail

LOCK_FILE="/tmp/kbl-pipeline.lock"
REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
VAULT="${KBL_VAULT:-${HOME}/baker-vault}"
LOG="/var/log/kbl/pipeline.log"

# --- Acquire lock ---
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    # Lock held → exit silently (not an error, next tick will retry)
    exit 0
fi

# --- Logging helper ---
log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" >> "${LOG}"
}
log "=== tick start PID=$$ ==="

# --- Step 1: sync config (D13, D2 backup path) ---
cd "${VAULT}"
if ! git pull --rebase -X ours origin main 2>> "${LOG}"; then
    log "CRITICAL: git pull conflict, aborting tick"
    git rebase --abort 2>/dev/null || true
    python3 -m kbl.logging emit_critical "git-conflict" "baker-vault pull failed — manual intervention required"
    exit 1
fi

# --- Step 2: source config ---
eval "$(yq -r '
  [paths(scalars, arrays) as $p |
    select($p | last | type != "number") |
    "export KBL_" + ($p | map(. | ascii_upcase) | join("_")) + "=" +
    (getpath($p) |
      if type == "array" then join(",") else tostring end
    )
  ] | .[]
' "${VAULT}/config/env.mac-mini.yml")"

# --- Step 3: hard kill switch ---
if [ "${KBL_FLAGS_PIPELINE_ENABLED:-false}" != "true" ]; then
    log "pipeline disabled (KBL_FLAGS_PIPELINE_ENABLED=false), exiting"
    exit 0
fi

# --- Step 4: drain gold_promote_queue ---
log "draining gold_promote_queue"
cd "${REPO}" && python3 -m kbl.gold_drain >> "${LOG}" 2>&1 || log "WARN: gold_drain exited nonzero"

# --- Step 5: process 1 signal via KBL-B (stub in KBL-A) ---
log "processing 1 signal"
cd "${REPO}" && python3 -m kbl.pipeline_tick >> "${LOG}" 2>&1 || log "WARN: pipeline_tick exited nonzero"

log "=== tick end ==="
# Lock released on exec 9 close (implicit at script exit)
```

### `launchd/com.brisen.kbl.pipeline.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.brisen.kbl.pipeline</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/kbl-pipeline-tick.sh</string>
    </array>
    <key>StartInterval</key>
    <integer>120</integer>              <!-- 2 min default (D5: TBD post-bench, env override possible via reload) -->
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/var/log/kbl/pipeline.stdout</string>
    <key>StandardErrorPath</key>
    <string>/var/log/kbl/pipeline.stderr</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <!-- Secrets loaded from ~/.zshrc via login shell, or via op://
             post-Phase 1 migration. NOT in plist (per D4 D13). -->
    </dict>
</dict>
</plist>
```

**Cadence note:** StartInterval = 120s default. Post-bench (D5), adjust via plist edit + `launchctl reload`. Cron format (`*/2 * * * *`) from `env.mac-mini.yml` is documentation-only in Phase 1; launchd uses StartInterval.

### `kbl/pipeline_tick.py` (Python orchestrator — KBL-A STUB)

```python
"""KBL-A pipeline tick orchestrator.
KBL-A: claims 1 signal, logs, exits.
KBL-B: will replace the stub body with actual 8-step pipeline."""

import logging
import sys
from kbl.config import cfg_bool, cfg_list, cfg_int
from kbl.runtime_state import get_state, set_state
from kbl.logging import emit_log
from kbl.db import get_conn

log = logging.getLogger(__name__)

def claim_one_signal(conn) -> int | None:
    """Claim next pending signal via FOR UPDATE SKIP LOCKED. Returns signal_id or None."""
    with conn.cursor() as cur:
        allowed = cfg_list("matter_scope_allowed")
        cur.execute("""
            SELECT id FROM signal_queue
            WHERE status = 'pending'
            ORDER BY priority DESC, created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        row = cur.fetchone()
        if not row:
            return None
        signal_id = row[0]
        cur.execute(
            "UPDATE signal_queue SET status = 'processing', started_at = NOW() WHERE id = %s",
            (signal_id,)
        )
        conn.commit()
        return signal_id

def main():
    # Heartbeat first — even if nothing to process, prove aliveness
    set_state("mac_mini_heartbeat", "NOW()")

    # Check circuit breaker
    if get_state("anthropic_circuit_open") == "true":
        emit_log("WARN", "pipeline_tick", None,
                 "Anthropic circuit open, skipping API calls this tick")
        return 0

    # Check cost-circuit
    if get_state("cost_circuit_open") == "true":
        emit_log("INFO", "pipeline_tick", None,
                 "Cost cap reached today, skipping until UTC midnight")
        return 0

    conn = get_conn()
    try:
        signal_id = claim_one_signal(conn)
        if signal_id is None:
            return 0  # queue empty, normal exit

        # KBL-A STUB: just log + mark as done. KBL-B replaces this.
        emit_log("INFO", "pipeline_tick", signal_id,
                 "KBL-A stub: signal claimed but no pipeline logic yet (awaiting KBL-B)")
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE signal_queue SET status = 'classified-deferred', processed_at = NOW() WHERE id = %s",
                (signal_id,)
            )
            conn.commit()
        return 0
    finally:
        conn.close()

if __name__ == "__main__":
    sys.exit(main())
```

### Acceptance for Phase 4
- `launchctl start com.brisen.kbl.pipeline` → exits 0, log shows "=== tick start === / tick end ==="
- Run two `kbl-pipeline-tick.sh` concurrently → second exits immediately (flock held), log shows nothing for second
- Insert test signal (`INSERT INTO signal_queue (status, priority, source, raw_content) VALUES ('pending', 50, 'test', 'hello')`) → next tick claims it, marks `classified-deferred`, `kbl_log` INFO row present
- `KBL_FLAGS_PIPELINE_ENABLED=false` → tick exits 0 without claiming signals
- Heartbeat: after 1 tick, `SELECT value FROM kbl_runtime_state WHERE key='mac_mini_heartbeat'` is within last 2 min

---

## 9. Phase 5 — Gold Promote Drain Worker

### `kbl/gold_drain.py`

```python
"""Drains gold_promote_queue on each pipeline tick.
Per D2: WhatsApp /gold → WAHA/Render → gold_promote_queue INSERT
→ Mac Mini drains → frontmatter edit → commit with Director identity → push."""

import subprocess
from pathlib import Path
import yaml
from datetime import datetime, timezone
from kbl.db import get_conn
from kbl.logging import emit_log
from kbl.config import cfg_bool

VAULT = Path.home() / "baker-vault"
DIRECTOR_EMAIL = "dvallen@brisengroup.com"
DIRECTOR_NAME = "Dimitry Vallen"

def drain_queue():
    if cfg_bool("gold_promote_disabled", False):
        emit_log("INFO", "gold_drain", None, "Gold promotion disabled via kill-switch")
        return

    conn = get_conn()
    try:
        # Claim pending rows with SKIP LOCKED (though conflicts unlikely — Mac Mini is sole consumer)
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, path, wa_msg_id FROM gold_promote_queue
                WHERE processed_at IS NULL
                ORDER BY requested_at ASC
                LIMIT 10
                FOR UPDATE SKIP LOCKED
            """)
            rows = cur.fetchall()

            if not rows:
                return

            for row_id, path, wa_msg_id in rows:
                result = promote_one(path)
                cur.execute("""
                    UPDATE gold_promote_queue
                    SET processed_at = NOW(), result = %s
                    WHERE id = %s
                """, (result, row_id))
                conn.commit()
                emit_log(
                    "INFO" if result in ("ok", "noop") else "ERROR",
                    "gold_drain", None,
                    f"Promoted {path}: {result}",
                    metadata={"wa_msg_id": wa_msg_id, "queue_id": row_id}
                )

        # After all promotions: commit + push if any changes
        _commit_and_push()
    finally:
        conn.close()

def promote_one(path: str) -> str:
    """Apply Gold promotion to a single file. Returns 'ok', 'noop', or 'error:...'."""
    target = VAULT / path
    if not target.exists():
        return f"error:file_not_found"

    try:
        content = target.read_text()
        fm, body = _parse_frontmatter(content)
    except Exception as e:
        return f"error:parse:{e}"

    if fm.get("author") == "director":
        return "noop"  # already Gold, idempotent

    fm["author"] = "director"
    fm["author_verified_at"] = datetime.now(timezone.utc).isoformat()

    new_content = _format_frontmatter(fm) + body
    target.write_text(new_content)
    return "ok"

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content
    fm_str = content[4:end]
    body = content[end + 5:]
    return yaml.safe_load(fm_str) or {}, body

def _format_frontmatter(fm: dict) -> str:
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n"

def _commit_and_push():
    """Commit staged changes with Director identity and push."""
    # Check if any changes
    diff = subprocess.run(
        ["git", "-C", str(VAULT), "diff", "--stat"],
        capture_output=True, text=True
    )
    if not diff.stdout.strip():
        return

    subprocess.run(["git", "-C", str(VAULT), "add", "-A"], check=True)
    subprocess.run([
        "git", "-C", str(VAULT),
        "-c", f"user.name={DIRECTOR_NAME}",
        "-c", f"user.email={DIRECTOR_EMAIL}",
        "commit", "-m", "gold: Director promotion"
    ], check=True)
    subprocess.run(["git", "-C", str(VAULT), "push", "origin", "main"], check=True)
```

### Backup path: git-diff-on-pull

In `kbl-pipeline-tick.sh` after `git pull`, check for frontmatter flips:

```bash
# After successful git pull, before sourcing config:
CHANGED_FILES=$(git -C "${VAULT}" diff-tree --no-commit-id --name-only -r HEAD@{1} HEAD 2>/dev/null || true)
for f in ${CHANGED_FILES}; do
    if [[ "${f}" == wiki/*.md ]]; then
        # Check if frontmatter now has author: director
        if head -20 "${VAULT}/${f}" | grep -qE '^author:\s*director\s*$'; then
            # Log as Gold promotion via git-diff path (idempotent with gold_drain)
            python3 -m kbl.logging emit_info "gold_promote_git_diff" \
                "Detected author: director in ${f} via git-diff backup path"
        fi
    fi
done
```

**Idempotency:** if `gold_drain` already set `author: director` and pushed, the diff-detection logs but `promote_one()` returns `noop` if called. No double-commit.

### Acceptance for Phase 5
- `INSERT INTO gold_promote_queue (path, wa_msg_id) VALUES ('hagenauer-rg7/test.md', 'test-001')` → within 2 cron cycles, file frontmatter has `author: director` + `author_verified_at`, commit on `main` with author = `Dimitry Vallen <dvallen@brisengroup.com>`
- Second INSERT same path → `result='noop'`, no duplicate commit
- INSERT with non-existent path → `result='error:file_not_found'`, log ERROR, no commit
- Kill-switch: `GOLD_PROMOTE_DISABLED=true` in yml → push → next tick logs "disabled", no draining

---

## 10. Phase 6 — Retry + Circuit Breaker + Runtime State

### `kbl/runtime_state.py`

```python
"""Key-value access to kbl_runtime_state table.
Atomic UPSERT for writes; single-query reads."""

from kbl.db import get_conn

def get_state(key: str, default: str = "") -> str:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT value FROM kbl_runtime_state WHERE key = %s", (key,))
        row = cur.fetchone()
        return row[0] if row else default

def set_state(key: str, value: str, updated_by: str = "pipeline"):
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kbl_runtime_state (key, value, updated_at, updated_by)
            VALUES (%s, %s, NOW(), %s)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                updated_at = EXCLUDED.updated_at,
                updated_by = EXCLUDED.updated_by
        """, (key, value, updated_by))
        conn.commit()

def increment_state(key: str, updated_by: str = "pipeline") -> int:
    """Atomic increment for counters. Returns new value."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kbl_runtime_state (key, value, updated_at, updated_by)
            VALUES (%s, '1', NOW(), %s)
            ON CONFLICT (key) DO UPDATE
            SET value = (kbl_runtime_state.value::int + 1)::text,
                updated_at = NOW(),
                updated_by = EXCLUDED.updated_by
            RETURNING value
        """, (key, updated_by))
        conn.commit()
        return int(cur.fetchone()[0])
```

### `kbl/retry.py`

```python
"""Retry ladders + circuit breaker for Anthropic API and local Ollama."""

import time
import json
from anthropic import Anthropic, APIError, APIConnectionError, RateLimitError
from kbl.runtime_state import get_state, set_state, increment_state
from kbl.logging import emit_log

ANTHROPIC_BACKOFFS = [10, 30, 120]  # seconds
CIRCUIT_CLEAR_WAIT_SECONDS = 600    # 10 min per D8

def call_anthropic_with_retry(anthropic: Anthropic, model: str, messages: list, max_tokens: int, skip_circuit: bool = False) -> dict:
    """Anthropic call with backoff + circuit breaker."""
    # Check circuit
    if not skip_circuit and get_state("anthropic_circuit_open") == "true":
        raise RuntimeError("anthropic_circuit_open")

    last_error = None
    for attempt, backoff in enumerate([0] + ANTHROPIC_BACKOFFS):
        if backoff > 0:
            time.sleep(backoff)
        try:
            resp = anthropic.messages.create(model=model, messages=messages, max_tokens=max_tokens)
            # Success — reset 5xx counter
            set_state("anthropic_5xx_counter", "0")
            return resp
        except RateLimitError as e:
            last_error = e
            emit_log("WARN", "retry_anthropic", None, f"429 on attempt {attempt+1}, backing off")
            continue
        except APIError as e:
            last_error = e
            # 5xx handling: increment counter, maybe open circuit
            if hasattr(e, 'status_code') and 500 <= e.status_code < 600:
                counter = increment_state("anthropic_5xx_counter")
                emit_log("WARN", "retry_anthropic", None, f"5xx on attempt {attempt+1}, counter={counter}")
                if counter >= 3:
                    set_state("anthropic_circuit_open", "true")
                    set_state("anthropic_5xx_counter", "0")
                    emit_log("CRITICAL", "circuit_breaker", None, "Anthropic circuit opened (3× consecutive 5xx)")
                    break
            continue

    # Exhausted retries → DLQ
    raise last_error or RuntimeError("anthropic retry exhausted")

def check_and_clear_anthropic_circuit(anthropic: Anthropic) -> bool:
    """Periodic health check to clear open circuit.
    Called by dedicated maintenance task (not pipeline_tick — that has its own skip logic)."""
    if get_state("anthropic_circuit_open") != "true":
        return True  # already clear

    # Health check: 1-token ping with skip_circuit
    try:
        resp = anthropic.messages.create(
            model="claude-haiku-4",       # cheapest
            messages=[{"role": "user", "content": "ok"}],
            max_tokens=1
        )
        set_state("anthropic_circuit_open", "false")
        emit_log("INFO", "circuit_breaker", None, "Anthropic circuit cleared by health check")
        return True
    except Exception as e:
        emit_log("WARN", "circuit_breaker", None, f"Health check still failing: {e}")
        return False

def call_gemma_with_retry(signal: dict, prompt_template: str) -> dict:
    """Gemma call ladder: retry same temp=0 with pared prompt → temp=0.3 → Qwen cold-swap → DLQ."""
    from kbl.config import cfg
    model = cfg("ollama_model", "gemma4:latest")
    fallback = cfg("ollama_fallback", "qwen2.5:14b")

    # Attempt 1: full prompt, temp=0
    try:
        return _call_ollama(model, prompt_template.format(**signal), temp=0)
    except (InvalidJSONError, Exception) as e:
        emit_log("WARN", "retry_gemma", signal.get("id"), f"attempt 1 failed: {e}")

    # Attempt 2: pared prompt (signal + schema only, no context), temp=0
    try:
        pared = _pare_prompt(prompt_template).format(**signal)
        return _call_ollama(model, pared, temp=0)
    except (InvalidJSONError, Exception) as e:
        emit_log("WARN", "retry_gemma", signal.get("id"), f"attempt 2 failed: {e}")

    # Attempt 3: original prompt, temp=0.3
    try:
        return _call_ollama(model, prompt_template.format(**signal), temp=0.3)
    except (InvalidJSONError, Exception) as e:
        emit_log("WARN", "retry_gemma", signal.get("id"), f"attempt 3 failed: {e}")

    # Attempt 4: Qwen cold-swap
    try:
        set_state("qwen_active", "true")
        if not get_state("qwen_active_since"):
            set_state("qwen_active_since", "NOW()")
        result = _call_ollama(fallback, prompt_template.format(**signal), temp=0)
        increment_state("qwen_swap_count_today")
        return result
    except Exception as e:
        emit_log("ERROR", "retry_gemma", signal.get("id"), f"Qwen also failed: {e}")
        raise  # caller decides DLQ

def _pare_prompt(template: str) -> str:
    """Strip vault context chunks, keep instruction + signal + schema. KBL-B refines."""
    # Minimal implementation for KBL-A: return template as-is.
    # KBL-B replaces with actual vault-context stripping.
    return template

def _call_ollama(model: str, prompt: str, temp: float = 0) -> dict:
    """Call Ollama locally, parse JSON response."""
    import requests
    resp = requests.post(
        "http://localhost:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": temp, "seed": 42, "top_p": 0.9}
        },
        timeout=60
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        return json.loads(data["response"])
    except json.JSONDecodeError as e:
        raise InvalidJSONError(f"Ollama returned invalid JSON: {data['response'][:200]}") from e

class InvalidJSONError(Exception):
    pass
```

### Qwen recovery (runs periodically — e.g., at start of every N ticks)

```python
# In kbl/pipeline_tick.py, after heartbeat:
def maybe_recover_gemma():
    """After N signals or X hours on Qwen, try Gemma again on next call."""
    if get_state("qwen_active") != "true":
        return
    swap_count = int(get_state("qwen_swap_count_today") or "0")
    if swap_count >= cfg_int("qwen_recovery_after_signals", 10):
        set_state("qwen_active", "false")
        set_state("qwen_active_since", "")
        set_state("qwen_swap_count_today", "0")
        emit_log("INFO", "qwen_recovery", None, f"Recovered to Gemma after {swap_count} signals")
```

### Acceptance for Phase 6
- Mock Anthropic with 3× `APIError(status_code=502)` → circuit opens, `kbl_runtime_state.anthropic_circuit_open='true'`
- `check_and_clear_anthropic_circuit` with mocked 200 response → circuit clears
- Force Gemma JSON failure → retry ladder cycles → Qwen picked up → `qwen_active='true'`
- After 10 successful Qwen calls → `maybe_recover_gemma` flips back → next call uses Gemma

---

## 11. Phase 7 — Cost Tracking Runtime

### `kbl/cost.py`

```python
"""Cost tracking: pre-call estimate, post-call logging, daily cap enforcement."""

from datetime import date
from decimal import Decimal
import os
from anthropic import Anthropic
from kbl.db import get_conn
from kbl.runtime_state import get_state, set_state
from kbl.logging import emit_log
from kbl.config import cfg_float

# Per-million-token prices (USD) — env-seeded, Director updates on Anthropic changes
PRICING = {
    "claude-opus-4":   {"input": float(os.getenv("PRICE_OPUS4_IN",  "15.00")),  "output": float(os.getenv("PRICE_OPUS4_OUT",  "75.00"))},
    "claude-sonnet-4": {"input": float(os.getenv("PRICE_SONNET4_IN", "3.00")),  "output": float(os.getenv("PRICE_SONNET4_OUT", "15.00"))},
    "claude-haiku-4":  {"input": float(os.getenv("PRICE_HAIKU4_IN",  "0.80")),  "output": float(os.getenv("PRICE_HAIKU4_OUT",   "4.00"))},
    "gemma4:latest":   {"input": 0.0, "output": 0.0},
    "qwen2.5:14b":     {"input": 0.0, "output": 0.0},
}

def estimate_cost(model: str, prompt: str, max_output_tokens: int, anthropic: Anthropic | None = None) -> float:
    """Pre-call cost estimate. USD."""
    # Primary: Anthropic count_tokens endpoint
    input_tokens = None
    if anthropic and model.startswith("claude-"):
        try:
            resp = anthropic.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": prompt}]
            )
            input_tokens = resp.input_tokens
        except Exception:
            pass

    # Fallback 1: SDK tokenizer (may not exist in newer SDK versions)
    if input_tokens is None:
        try:
            from anthropic import Anthropic as _A
            input_tokens = _A().count_tokens(prompt)  # may raise AttributeError
        except Exception:
            pass

    # Fallback 2: char/4 heuristic (conservative — overestimates)
    if input_tokens is None:
        input_tokens = len(prompt) // 4 + 1

    price = PRICING.get(model, {"input": 0, "output": 0})
    return (input_tokens * price["input"] + max_output_tokens * price["output"]) / 1_000_000

def today_spent_usd() -> float:
    """Sum of cost_usd for today UTC."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM kbl_cost_ledger
            WHERE ts::date = NOW()::date
        """)
        return float(cur.fetchone()[0])

def check_cost_cap(model: str, prompt: str, max_output_tokens: int, anthropic: Anthropic | None = None) -> tuple[bool, float, float]:
    """Returns (would_exceed, estimated_cost, today_total)."""
    cap = cfg_float("cost_daily_cap_usd", 15.0)
    today = today_spent_usd()
    estimate = estimate_cost(model, prompt, max_output_tokens, anthropic)
    return (today + estimate > cap, estimate, today)

def log_cost_actual(signal_id: int | None, step: str, model: str,
                    input_tokens: int, output_tokens: int, latency_ms: int,
                    success: bool = True, metadata: dict | None = None):
    """Post-call actual cost logging."""
    price = PRICING.get(model, {"input": 0, "output": 0})
    cost = (input_tokens * price["input"] + output_tokens * price["output"]) / 1_000_000
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kbl_cost_ledger
            (signal_id, step, model, input_tokens, output_tokens, latency_ms, cost_usd, success, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (signal_id, step, model, input_tokens, output_tokens, latency_ms, cost, success,
              json.dumps(metadata) if metadata else None))
        conn.commit()

    # Post-log cap check
    _maybe_alert_cost_threshold()

def _maybe_alert_cost_threshold():
    """80% / 95% / 100% alerts with dedupe via kbl_alert_dedupe."""
    cap = cfg_float("cost_daily_cap_usd", 15.0)
    today = today_spent_usd()
    today_pct = today / cap * 100
    today_date = date.today().isoformat()

    thresholds = [(100, "cost_100pct_open_circuit"), (95, "cost_95pct_alert"), (80, "cost_80pct_alert")]
    for pct, alert_key_base in thresholds:
        if today_pct < pct:
            continue
        alert_key = f"{alert_key_base}_{today_date}"
        if _try_dedupe(alert_key):
            if pct == 100:
                set_state("cost_circuit_open", "true")
                emit_log("CRITICAL", "cost_circuit", None,
                         f"KBL cost cap reached today: ${today:.2f} / ${cap:.2f}. Pipeline halted until UTC midnight.")
            else:
                emit_log("WARN", "cost_threshold", None,
                         f"KBL cost at {pct}%: ${today:.2f} / ${cap:.2f}")
        break  # only fire highest threshold hit

def _try_dedupe(alert_key: str) -> bool:
    """INSERT with ON CONFLICT DO NOTHING. Returns True if this is a new alert (should send)."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kbl_alert_dedupe (alert_key) VALUES (%s)
            ON CONFLICT (alert_key) DO NOTHING
            RETURNING alert_key
        """, (alert_key,))
        inserted = cur.fetchone()
        conn.commit()
        return inserted is not None

def daily_cost_circuit_clear():
    """Reset cost_circuit_open at UTC midnight. Called by daily maintenance task."""
    set_state("cost_circuit_open", "false")
    emit_log("INFO", "cost_circuit", None, "Cost circuit auto-cleared at UTC midnight")
```

### Acceptance for Phase 7
- `DAILY_COST_CAP=0.01` → pre-call estimate exceeds → signal marked `cost-deferred`, `cost_circuit_open='true'`
- 80% / 95% / 100% thresholds fire exactly once per UTC day (verified via `kbl_alert_dedupe`)
- `log_cost_actual` populates `kbl_cost_ledger` with correct cost based on token counts + price table
- `daily_cost_circuit_clear` at UTC midnight resets state

---

## 12. Phase 8 — Logging + Alert Dedupe + Heartbeat

### `kbl/logging.py`

```python
"""Tiered logging: local file (DEBUG+), PG (WARN+), WhatsApp alert (CRITICAL with dedupe)."""

import json
import hashlib
import logging
import time
from pathlib import Path
from kbl.db import get_conn
from kbl.whatsapp import send_director_alert  # existing WAHA client helper

LOG_FILE = Path("/var/log/kbl/pipeline.log")
DEDUPE_BUCKET_MINUTES = 5

# Local Python logger
_logger = logging.getLogger("kbl")
_logger.setLevel(logging.DEBUG)
_handler = logging.FileHandler(LOG_FILE)
_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
_logger.addHandler(_handler)

def emit_log(level: str, component: str, signal_id: int | None, message: str,
             metadata: dict | None = None):
    """Tiered emission. INFO and DEBUG go to file only; WARN+ to PG; CRITICAL to WhatsApp."""
    # Always local
    _logger.log(getattr(logging, level, logging.INFO), f"[{component}] signal={signal_id} {message}")

    if level in ("WARN", "ERROR", "CRITICAL"):
        with get_conn() as conn, conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kbl_log (level, component, signal_id, message, metadata)
                VALUES (%s, %s, %s, %s, %s)
            """, (level, component, signal_id, message,
                  json.dumps(metadata) if metadata else None))
            conn.commit()

    if level == "CRITICAL":
        emit_critical_alert(component, message)

def emit_critical_alert(component: str, message: str, bucket_minutes: int = DEDUPE_BUCKET_MINUTES):
    """CRITICAL WhatsApp alert with dedupe."""
    bucket = int(time.time() // (bucket_minutes * 60))
    msg_hash = hashlib.sha256(message.encode()).hexdigest()[:16]
    alert_key = f"{component}_{msg_hash}_{bucket}"

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO kbl_alert_dedupe (alert_key) VALUES (%s)
            ON CONFLICT (alert_key) DO UPDATE SET
                send_count = kbl_alert_dedupe.send_count + 1,
                last_sent = NOW()
            RETURNING (xmax = 0) AS was_inserted
        """, (alert_key,))
        was_inserted = cur.fetchone()[0]
        conn.commit()

    if was_inserted:
        send_director_alert(f"[KBL CRITICAL] {component}: {message}")

# Convenience shims used by bash wrappers via python3 -m
def emit_info(component: str, message: str):
    emit_log("INFO", component, None, message)

def emit_critical(component: str, message: str):
    emit_log("CRITICAL", component, None, message)
```

### `kbl/heartbeat.py`

```python
"""Heartbeat: updates mac_mini_heartbeat in kbl_runtime_state every 30 min."""
from kbl.runtime_state import set_state
from datetime import datetime, timezone

def main():
    set_state("mac_mini_heartbeat", datetime.now(timezone.utc).isoformat(), updated_by="heartbeat")

if __name__ == "__main__":
    main()
```

### `scripts/kbl-heartbeat.sh`

```bash
#!/bin/bash
set -euo pipefail
REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
cd "${REPO}"
python3 -m kbl.heartbeat >> /var/log/kbl/heartbeat.log 2>&1
```

### `launchd/com.brisen.kbl.heartbeat.plist` (every 30 min)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.brisen.kbl.heartbeat</string>
    <key>ProgramArguments</key><array><string>/usr/local/bin/kbl-heartbeat.sh</string></array>
    <key>StartInterval</key><integer>1800</integer>
    <key>RunAtLoad</key><true/>
</dict></plist>
```

### `scripts/kbl-dropbox-mirror.sh` (daily 23:50 Europe/Vienna)

```bash
#!/bin/bash
set -euo pipefail
SRC="/var/log/kbl/"
DEST="${HOME}/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/$(date +%Y-%m-%d)/"
mkdir -p "${DEST}"
rsync -a --include='*.log' --include='*.log.*' --exclude='*' "${SRC}" "${DEST}"
```

### `scripts/kbl-purge-dedupe.sh` (daily 03:15 Europe/Vienna)

```bash
#!/bin/bash
set -euo pipefail
REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
cd "${REPO}"
python3 -c "
from kbl.db import get_conn
from kbl.cost import daily_cost_circuit_clear
with get_conn() as conn, conn.cursor() as cur:
    cur.execute(\"DELETE FROM kbl_alert_dedupe WHERE last_sent < NOW() - INTERVAL '7 days'\")
    conn.commit()
daily_cost_circuit_clear()
" >> /var/log/kbl/purge.log 2>&1
```

### Render-side heartbeat monitor (sentinel addition)

Add a new sentinel or extend an existing one to poll `kbl_runtime_state.mac_mini_heartbeat` every 15 min. If >30 min stale, emit `CRITICAL` log `component='heartbeat_stale'` — triggers WhatsApp via existing dedupe.

### Acceptance for Phase 8
- `emit_log("CRITICAL", "test", None, "test message")` → log file contains, `kbl_log` row present, WhatsApp received (once, dedupe 5-min bucket)
- Emit 10× identical CRITICAL in 2 min → 1 WhatsApp received, `kbl_alert_dedupe.send_count >= 10`
- Heartbeat runs every 30 min → `mac_mini_heartbeat` current within last 30 min
- Dropbox rsync at 23:50 → logs present at `~/Dropbox-Vallen/.../kbl_logs/<date>/`
- Purge script clears 7-day-old dedupe rows + resets cost circuit at 03:15

---

## 13. Deploy Sequence (D12)

1. **Merge KBL-A PR to `main`** on `baker-master` repo
2. **Render auto-deploys** → `_ensure_*` methods run on startup → all 5 new tables + signal_queue additions present in Neon PG
3. **Verify via psql:** `\d kbl_runtime_state`, `\d kbl_cost_ledger`, `\d kbl_log`, `\d kbl_alert_dedupe`, `\d gold_promote_queue`, `\d signal_queue` — all show expected columns + constraints
4. **Director applies SSH hardening** on Mac Mini (if not already done) per `SSH_HARDENING_PROCEDURE.md`
5. **Director/Code SSH to macmini**, run `scripts/install_kbl_mac_mini.sh` (one-time setup — sudo prompts for log dir + newsyslog)
6. **Commit `config/env.mac-mini.yml`** to `baker-vault` repo (via MacBook Obsidian) — Mac Mini pulls on next tick
7. **Verify first tick:** `tail -f /var/log/kbl/pipeline.log` → should show "tick start / pipeline disabled, exiting" (KBL_FLAGS_PIPELINE_ENABLED=false is correct initial state)
8. **Insert test gold row:** `INSERT INTO gold_promote_queue (path, wa_msg_id) VALUES ('test/dummy.md', 'manual-test')` (after creating `test/dummy.md` in vault). Within 2 cron cycles, verify commit on `main` with Director identity.
9. **Flip pipeline flag:** Director edits `flags.pipeline_enabled: "true"` in `env.mac-mini.yml`, commits, pushes. Next tick begins processing.
10. **Monitor:** `kbl_log` PG queries, `/var/log/kbl/` tail, dashboard cost rollup.

---

## 14. Acceptance Criteria (Dispatch Sign-off)

Code Brisen signs off on KBL-A when ALL of the following pass:

### Schema
- [ ] All 5 new tables present with correct columns + CHECK constraints
- [ ] `signal_queue` has 3 new columns + 3 new indexes + expanded status CHECK
- [ ] `kbl_runtime_state` seeded with 6 flag keys
- [ ] FK constraints (`kbl_cost_ledger.signal_id`, `kbl_log.signal_id`) present with `ON DELETE SET NULL`

### Mac Mini install
- [ ] `install_kbl_mac_mini.sh` runs clean on fresh Mac Mini setup (idempotent re-run works)
- [ ] 5 symlinks in `/usr/local/bin/kbl-*`
- [ ] 4 LaunchAgents loaded and running
- [ ] `/var/log/kbl/` exists with `/etc/newsyslog.d/kbl.conf` installed

### Config deployment
- [ ] `env.mac-mini.yml` in baker-vault parses via yq expression without stray `_N` exports
- [ ] Python config module reads scalars, lists, booleans correctly
- [ ] Director-triggered yml edit → auto-push → Mac Mini pull → new value read on next tick (end-to-end)

### Pipeline tick
- [ ] Flock mutex prevents concurrent ticks
- [ ] `KBL_FLAGS_PIPELINE_ENABLED=false` → ticks skip processing
- [ ] Pipeline claims 1 signal via `FOR UPDATE SKIP LOCKED` (verified with concurrent inserts)
- [ ] Heartbeat updates `mac_mini_heartbeat` every tick

### Gold drain
- [ ] INSERT into `gold_promote_queue` → file frontmatter flipped to `author: director` + commit with Director identity + push within 2 cron cycles
- [ ] Idempotency: repeat INSERT same path → `result='noop'`, no duplicate commit
- [ ] Kill-switch: `GOLD_PROMOTE_DISABLED=true` → drain logs "disabled" and does nothing
- [ ] Non-existent path → `result='error:file_not_found'`, logged ERROR

### Retry + circuit
- [ ] Mocked 3× Anthropic 5xx → circuit opens, counter resets
- [ ] Mocked Anthropic 429 → backoff delays applied, counter NOT incremented
- [ ] Circuit health-check with 200 → circuit clears
- [ ] Gemma fail cascade: same-temp retry → temp=0.3 retry → Qwen cold-swap → DLQ on Qwen fail

### Cost
- [ ] Pre-call estimate via Anthropic endpoint (+ fallbacks) returns USD cost
- [ ] Cap exceeded → signal marked `cost-deferred`, `cost_circuit_open='true'`
- [ ] 80% / 95% / 100% thresholds fire exactly once per UTC day
- [ ] `kbl_cost_ledger` populated with correct actual cost after successful calls
- [ ] `claude -p` token usage counted (if any `claude -p` path implemented in stub)

### Logging
- [ ] CRITICAL emit → WhatsApp received, `kbl_log` row present, `kbl_alert_dedupe` row present
- [ ] 10× identical CRITICAL in 2 min → 1 WhatsApp (dedupe works)
- [ ] Dropbox mirror at 23:50 → logs copied to Dropbox dir
- [ ] Purge at 03:15 → 7d+ dedupe rows deleted, cost circuit reset

---

## 15. Rollback Plan

**Trigger:** KBL-A regresses existing Cortex V2 functionality, OR introduces production outage.

**Procedure:**
1. **Flip kill-switch:** Director edits `env.mac-mini.yml` → `flags.pipeline_enabled: "false"` → commit + push. Mac Mini ticks go to no-op on next poll (≤2 min).
2. **Stop LaunchAgents (if needed):** `launchctl unload ~/Library/LaunchAgents/com.brisen.kbl.*` — halts all KBL processes.
3. **Render revert:** Revert the KBL-A PR merge commit. Render redeploys without the `_ensure_*` calls for the new tables. **Important: new tables stay in PG** (soft-deprecate per D12 N5) — they don't interfere with non-KBL code paths since Cortex V2 doesn't reference them.
4. **signal_queue migration rollback (if needed):**
   ```sql
   ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_status_check;
   ALTER TABLE signal_queue ADD CONSTRAINT signal_queue_status_check
       CHECK (status IN ('pending', 'processing', 'done', 'failed', 'expired'));
   ALTER TABLE signal_queue DROP CONSTRAINT IF EXISTS signal_queue_triage_confidence_range;
   ```
   Added columns stay (no data loss).
5. **Vault state preserved:** baker-vault repo untouched. `gold_promote_queue` rows retained for post-mortem.
6. **Cortex V2 continues running independently.** KBL-A is additive infrastructure; rollback leaves baseline intact.

---

## 16. Env Var Complete Reference

All tunables (sourced from `env.mac-mini.yml` except where noted):

| Var (flat after yq) | Default | Source | Scope |
|---|---|---|---|
| `KBL_OLLAMA_MODEL` | `gemma4:latest` | D1 | Mac Mini |
| `KBL_OLLAMA_FALLBACK` | `qwen2.5:14b` | D1 | Mac Mini |
| `KBL_OLLAMA_TEMP` | `0` | D1 | Mac Mini |
| `KBL_OLLAMA_SEED` | `42` | D1 | Mac Mini |
| `KBL_OLLAMA_TOP_P` | `0.9` | D1 | Mac Mini |
| `KBL_OLLAMA_KEEP_ALIVE` | `-1` | D1 / S2 | Mac Mini |
| `KBL_MATTER_SCOPE_ALLOWED` | `hagenauer-rg7` | D3 | Mac Mini |
| `KBL_MATTER_SCOPE_LAYER0_ENABLED` | `true` | D3 | Mac Mini |
| `KBL_MATTER_SCOPE_NEWSLETTER_BLOCKLIST` | `""` | D3 | Mac Mini |
| `KBL_MATTER_SCOPE_WA_BLOCKLIST` | `""` | D3 | Mac Mini |
| `KBL_GOLD_PROMOTE_DISABLED` | `false` | D2 | Mac Mini + Render (same value both sides) |
| `KBL_GOLD_PROMOTE_WHITELIST_WA_ID` | `41799605092@c.us` | D2 | Render (WAHA) |
| `KBL_PIPELINE_CRON_INTERVAL_MINUTES` | `2` (TBD post-bench) | D5 | documentation only — launchd uses StartInterval |
| `KBL_PIPELINE_TRIAGE_THRESHOLD` | `40` | existing | Mac Mini |
| `KBL_PIPELINE_MAX_QUEUE_SIZE` | `10000` | D10 | Render |
| `KBL_PIPELINE_QWEN_RECOVERY_AFTER_SIGNALS` | `10` | D1 / S3 | Mac Mini |
| `KBL_PIPELINE_QWEN_RECOVERY_AFTER_HOURS` | `1` | D1 / S3 | Mac Mini |
| `KBL_COST_DAILY_CAP_USD` | `15` | D6 / D14 | Mac Mini + Render |
| `KBL_COST_MAX_ALERTS_PER_DAY` | `20` | D6 | Mac Mini |
| `KBL_FLAGS_PIPELINE_ENABLED` | `false` (flips `true` at go-live) | existing | Mac Mini |
| `KBL_OBSERVABILITY_DROPBOX_RSYNC_TIME` | `23:50` | D15 | Mac Mini launchd |
| `KBL_OBSERVABILITY_VAULT_SIZE_WARN_MB` | `500` | D15 | Mac Mini |
| `KBL_OBSERVABILITY_VAULT_SIZE_CRITICAL_MB` | `1000` | D15 | Mac Mini |

**Render-side environment (NOT in yml, set via Render dashboard):**
- `ANTHROPIC_API_KEY` — secret, existing
- `DATABASE_URL` — secret, existing
- `PRICE_OPUS4_IN` / `PRICE_OPUS4_OUT` / `PRICE_SONNET4_IN` / etc. — pricing table, rotate on Anthropic changes

**Mac Mini `.zshrc` (NOT in yml, secrets):**
- Same 5 secrets as Render (ANTHROPIC_API_KEY, DATABASE_URL, QDRANT_URL, QDRANT_API_KEY, VOYAGE_API_KEY)
- Per D4 override: rotation deferred to Phase 1 close-out

**Runtime state (`kbl_runtime_state` PG table — NOT env vars):**
- `anthropic_circuit_open`, `anthropic_5xx_counter`, `qwen_active`, `qwen_active_since`, `qwen_swap_count_today`, `mac_mini_heartbeat`, `cost_circuit_open`

---

## 17. Known Open Items / Risks

1. **D5 cron cadence TBD post-bench.** Phase 1 launches at default StartInterval=120s. Bench runs after Phase 1 install but before production go-live (signal_queue enabled). If p95 > 120s, Director updates plist + `launchctl reload`. KBL-B brief formalizes cadence lock.

2. **KBL-A orchestrator is a stub.** `kbl/pipeline_tick.py` claims a signal and marks it `classified-deferred` without running the 8-step pipeline. KBL-B replaces the stub. KBL-A verifies the CLAIM mechanism works end-to-end; processing logic is out of scope.

3. **Qwen cold-swap path untested in production.** First real Gemma failure exercises it. Low risk — Qwen is verified installed and loadable.

4. **Vault retention policy open.** D9 flags per-matter retention policy as Phase 1 close-out item. Not blocking KBL-A dispatch.

5. **SSH hardening by Director.** Not blocking dispatch but blocking production go-live. Drop-in ready.

6. **`feature-dev:code-reviewer` subagent parser must handle both harness output shapes** (CRITICAL/IMPORTANT vs Verdict:Passes/Fails). Implementation in D6 gate flow is minor; not blocking KBL-A build.

7. **MacBook Obsidian Git plugin auto-push dependency.** If Director forgets to enable plugin, D2 backup path (git-diff-on-pull) will not fire for MacBook-originated Gold edits. Prerequisite check covers this (§3).

8. **Signal-queue type mismatch already reconciled** (`BIGINT` → `INTEGER` FKs in §5). Documented in deploy sequence.

---

*Prepared 2026-04-17 by AI Head (Claude Opus 4.7). Target: Code Brisen review (R1) → Director ratification → dispatch. Expected build: 12-16 hours.*
