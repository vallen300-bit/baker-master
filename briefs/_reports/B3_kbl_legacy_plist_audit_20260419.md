# B3 — KBL-A Legacy Plist Audit

**From:** Code Brisen 3
**To:** AI Head → Director ratification
**Date:** 2026-04-19
**Task:** `briefs/_tasks/CODE_3_PENDING.md` at commit `16e89e0` — MAC_MINI_LEGACY_PLIST_AUDIT
**Mode:** read-only — no unloads, renames, or writes on Mac Mini in this task

---

## TL;DR

| Plist | Recommendation | One-line rationale |
|---|---|---|
| `com.brisen.kbl.purge-dedupe` | **KEEP** | Performs two operations the new KBL-B pipeline still depends on: `kbl_alert_dedupe` retention + `cost_circuit_open` daily reset. Retire = latent breakage. |
| `com.brisen.kbl.dropbox-mirror` | **ESCALATE** | Not harmful, but structurally hollowed out — sources `/var/log/kbl/` which no longer receives writes from the new baker.* agents (those log to `~/baker-pipeline/`). Director picks: update path, split, or retire. |

**Neither conflicts with Inv 9** when that invariant is read as "Mac Mini is the single vault writer" (the spec's actual scope). Broader "single agent per KBL table" reading would also clear both — see §4.

---

## 1. `com.brisen.kbl.purge-dedupe.plist`

### 1.1 What does it run?

**Plist `ProgramArguments`:** `/Users/dimitry/baker-code/scripts/kbl-purge-dedupe.sh`
**Schedule:** `StartCalendarInterval Hour=3 Minute=15` — daily 03:15 (system local, Europe/Vienna).
**Runs:** last fired `Apr 19 03:15` today (log mtimes confirm). All three logs are 0 bytes — clean exits.

**Wrapper body** (`kbl-purge-dedupe.sh`, 936B):

```bash
set -euo pipefail
REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"
LOG="/var/log/kbl/purge.log"
mkdir -p "$(dirname "${LOG}")" 2>/dev/null || true
[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"
cd "${REPO}"
python3 - <<'PY' >> "${LOG}" 2>&1
from kbl.cost import daily_cost_circuit_clear
from kbl.db import get_conn
with get_conn() as conn:
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kbl_alert_dedupe WHERE last_sent < NOW() - INTERVAL '7 days'")
            conn.commit()
    except Exception:
        conn.rollback()
        raise
daily_cost_circuit_clear()
PY
```

Inline Python (no separate module file) — two operations:

1. `DELETE FROM kbl_alert_dedupe WHERE last_sent < NOW() - INTERVAL '7 days'` — retention delete.
2. `kbl.cost.daily_cost_circuit_clear()` — resets the cost circuit.

### 1.2 What does it touch?

| Target | Operation | Notes |
|---|---|---|
| `kbl_alert_dedupe` (DB) | `DELETE` rows older than 7d | Authoritative retention gate |
| `cost_circuit_open` state (DB, via `kbl.cost.set_state`) | `SET` to `"false"` | Daily UTC-midnight reset |
| `/var/log/kbl/purge.{log,stdout,stderr}` | write | Log sink |
| `~/baker-vault/` | **none** | Does not touch vault |
| `signal_queue`, `kbl_cross_link_queue`, `mac_mini_heartbeat`, `kbl_cost_ledger`, `kbl_log` | **none** | Verified via `grep -rn` in `kbl-purge-dedupe.sh` + traced `kbl.cost.daily_cost_circuit_clear` definition |

Relevant source citation: `kbl/cost.py:254`:
```python
def daily_cost_circuit_clear() -> None:
    """Reset cost_circuit_open at UTC midnight. Invoked by kbl-purge-dedupe.sh."""
    set_state("cost_circuit_open", "false")
```

The docstring explicitly names `kbl-purge-dedupe.sh` as its invoker — the maintenance loop is an intentional two-sided contract, not accidental legacy.

### 1.3 Does it conflict with Cortex T3?

**No — it underpins Cortex T3.** Both operations serve functions the new KBL-B pipeline still uses:

| Function | New pipeline dependency | What breaks if purge-dedupe stops |
|---|---|---|
| `kbl_alert_dedupe` retention | `kbl/logging.py:134` INSERT, `kbl/cost.py:240` INSERT — table actively written by Steps 1-6 every time an alert fires | Unbounded table growth; no semantic breakage but storage bloat over time |
| `cost_circuit_open` reset | `kbl/pipeline_tick.py:208` gate: `if get_state("cost_circuit_open") == "true": skip tick` | **First cost-circuit trip becomes permanent** — pipeline idles forever until Director manually clears the flag |

The second is the sharper one: a single budget breach on any day would pin the pipeline in the OFF state until human intervention. That's a real hard failure mode.

**Write-overlap analysis (`kbl_alert_dedupe`):**
- Writers: `kbl.logging` + `kbl.cost` (on Render, Steps 1-6) INSERT current-day rows; purge-dedupe (on Mac Mini) DELETEs rows ≥ 7 days old.
- Temporal separation — no race on the same row set.
- Both writers exist in the approved architecture — see §4 on Inv 9 scope.

**No writes to** `signal_queue`, `kbl_cross_link_queue`, `mac_mini_heartbeat`, `kbl_cost_ledger`, `kbl_log`, or `~/baker-vault/`.

### 1.4 Recommendation

**KEEP — with one small hygiene fix to flag for a follow-up task (not urgent):**

The wrapper defaults `REPO="${KBL_REPO:-${HOME}/Desktop/baker-code}"` — pointing at `~/Desktop/baker-code`, which doesn't exist on this Mac Mini. The clone is at `~/baker-code`. Today this works because `KBL_REPO` is presumably set in `~/.kbl.env` (I did not read the env contents). Fragile if that var is ever dropped. **Future task (low-pri):** change the default to `${HOME}/baker-code` in `scripts/kbl-purge-dedupe.sh` — one-line PR.

---

## 2. `com.brisen.kbl.dropbox-mirror.plist`

### 2.1 What does it run?

**Plist `ProgramArguments`:** `/Users/dimitry/baker-code/scripts/kbl-dropbox-mirror.sh`
**Schedule:** `StartCalendarInterval Hour=23 Minute=50` — daily 23:50 (system local, Europe/Vienna).
**Runs:** last fired `Apr 18 23:50`. Both logs 0 bytes — rsync clean.

**Wrapper body** (`kbl-dropbox-mirror.sh`, 683B):

```bash
set -euo pipefail
[ -f "${HOME}/.kbl.env" ] && . "${HOME}/.kbl.env"
SRC="/var/log/kbl/"
DEST="${HOME}/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/$(date +%Y-%m-%d)/"
mkdir -p "${DEST}"
rsync -a --include='*.log' --include='*.log.*' --exclude='*' "${SRC}" "${DEST}"
```

Pure shell. No Python invocation. Single `rsync` with include/exclude for `*.log` + `*.log.*`.

### 2.2 What does it touch?

| Target | Operation | Notes |
|---|---|---|
| `/var/log/kbl/*.log` + `*.log.*` | **read** | Source files |
| `~/Dropbox-Vallen/_02_DASHBOARDS/kbl_logs/<date>/` | write (mkdir + rsync) | Dropbox-synced copy |
| Any DB table | **none** | Zero DB calls |
| `~/baker-vault/` | **none** | Does not touch vault |
| `~/.kbl.env` | read (but only if it exists — defensively loaded) | Not actually needed by current logic; carry-forward hook |

### 2.3 Does it conflict with Cortex T3?

**No active conflict — but the mirror is structurally hollowed out by my prior `MAC_MINI_LAUNCHD_PROVISION` work.**

The mirror sources `/var/log/kbl/`. After the `2026-04-19` surgical retirement of `com.brisen.kbl.pipeline` + `com.brisen.kbl.heartbeat`, the actively-written logs in `/var/log/kbl/` are only:

| File | Size | Last-write | Still live? |
|---|---|---|---|
| `pipeline.log` | 233KB | Apr 19 13:13 | **STALE** — old pipeline retired; this is trailing buffer |
| `pipeline.stderr` | 57KB | Apr 19 13:13 | STALE |
| `heartbeat.log` | 0B | Apr 18 05:09 | STALE |
| `purge.log`, `purge.stderr`, `purge.stdout` | 0B each | Apr 19 03:15 | **LIVE** (from purge-dedupe) |
| `dropbox-mirror.stderr`, `dropbox-mirror.stdout` | 0B | Apr 18 23:50 | LIVE (self) |
| `kbl.log` | 78B | Apr 19 11:09 | LIVE (general kbl logger) |

Meanwhile the new baker-pipeline logs live at `~/baker-pipeline/{poller,heartbeat}.{log,err.log}` — **not covered** by the current mirror glob.

**Net state:** the mirror still runs cleanly, but it's archiving largely-dead files and missing the new pipeline's working logs. It neither blocks nor helps Cortex T3.

**No writes to** any of the `signal_queue` / `kbl_cost_ledger` / `kbl_cross_link_queue` / `mac_mini_heartbeat` / `kbl_log` / `kbl_alert_dedupe` set, nor to `~/baker-vault/`.

### 2.4 Recommendation

**ESCALATE.** Three reasonable paths, Director picks:

| Option | Action | Pros | Cons |
|---|---|---|---|
| **(a) Update source** | Change `SRC="/var/log/kbl/"` → include both `/var/log/kbl/` AND `~/baker-pipeline/` | Mirrors BOTH legacy-purge logs and new pipeline logs | 1-line PR; minimal churn |
| **(b) Split** | Add a second plist `com.brisen.baker.log-mirror` for `~/baker-pipeline/`; leave `kbl.dropbox-mirror` as-is for legacy | Clean per-agent responsibility; matches the naming scheme you chose for baker.* | Two plists; more to monitor |
| **(c) Retire** | Unload + rename `.retired-2026-04-19b` (same pattern as before). Rely on Render / other monitoring for log visibility. | Minimalist | Loses offline Dropbox copy — you'd have no log snapshot if Mac Mini dies |

**B3 lean: (a)** — smallest change, preserves the Director-visible snapshot pattern, minimal operational footprint. Option (b) is defensible if you want strict 1:1 agent→mirror mapping.

**Hard-no to the implicit fourth option (do nothing)** — leaving it running sources the Director's nightly snapshot from `/var/log/kbl/` which is now a half-dead directory. Operational readings of "what the pipeline did last night" would diverge from where the real logs live.

---

## 3. Summary table

| Plist | Purpose | DB touch | Vault touch | Fresh writes after 2026-04-19 retirement? | Recommendation |
|---|---|---|---|---|---|
| `com.brisen.kbl.purge-dedupe` | `kbl_alert_dedupe` retention + `cost_circuit_open` daily reset | **DELETE + state-set** (both required by KBL-B pipeline) | None | Yes — fires daily 03:15; both ops still load-bearing | **KEEP** |
| `com.brisen.kbl.dropbox-mirror` | rsync `/var/log/kbl/` → Dropbox | None | None | Yes — fires daily 23:50; but source largely stale | **ESCALATE** (lean: option a — expand source) |

---

## 4. Inv 9 interpretation note

Task framing phrases Inv 9 as "Any write = conflict, per Inv 9 — Mac Mini poller is the only vault-writing agent in the new architecture."

Canonical Inv 9 (per CHANDA §3, ratified 2026-04-19): **"Mac Mini is the single AGENT writer. Director writes are expected from any machine."** In context, this is a statement about the **vault** (the git-backed `~/baker-vault/` clone) — not about every KBL Postgres table. Render-hosted Steps 1-6 unambiguously write to `signal_queue`, `kbl_cost_ledger`, `kbl_alert_dedupe`, etc. as part of the approved architecture.

Applied to this audit:

- **Vault writers:** only Step 7 (via `com.brisen.baker.poller`). `purge-dedupe` and `dropbox-mirror` don't touch the vault → Inv 9 clean.
- **DB writers:** per-table semantic separation matters more than "one host per table." Both legacy plists pass that narrower test (purge-dedupe does maintenance DELETEs on stale rows; dropbox-mirror writes zero DB).

If Director wants to tighten Inv 9 to explicitly scope "no DB writes from Mac Mini except Step 7 + heartbeat," that's a CHANDA amendment separate from this audit — flagging.

---

## 5. CHANDA pre-push

- **Q1 Loop Test:** audit only, no code touched. No Leg affected. Pass.
- **Q2 Wish Test:** serves the wish — ambiguity around retired-vs-kept legacy plists resolved with per-plist recommendation. Pass.
- **Inv 9:** §4 confirms both legacy plists are Inv-9-clean under the canonical scope. If scope broadens, purge-dedupe re-opens (see §1.3).
- **Inv 10:** no prompts touched. Pass.

---

*Read-only audit. No state changes to Mac Mini in this task. Follow-up retirement (if Director ratifies RETIRE on either) is a separate task per the prior `.retired-2026-04-19` pattern.*
