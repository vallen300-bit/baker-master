---
status: COMPLETE
brief: rollback_script_op_path_fix
trigger_class: LOW
dispatched_at: 2026-04-28T16:45:00Z
dispatched_by: ai-head-a
target_script: scripts/cortex_rollback_v1.sh
prior_dispatch_ship_report: briefs/_reports/B3_rollback_dry_rehearsal_20260428.md
claimed_at: 2026-04-28T16:50:00Z
claimed_by: b3
last_heartbeat: 2026-04-28T17:05:00Z
blocker_question: null
ship_report: briefs/_reports/B3_rollback_op_path_fix_20260428.md
verdict: PASS
pr_number: 76
pr_url: https://github.com/vallen300-bit/baker-master/pull/76
pr_state: OPEN — awaiting AI Head A solo diff-review + Tier-A merge
autopoll_eligible: false
---

# CODE_3_PENDING — B3: ROLLBACK SCRIPT op:// PATH FIX + RE-VERIFY (Q4 final pass) — 2026-04-28

**Dispatcher:** AI Head A (sole orchestrator)
**Working dir:** `~/bm-b3`
**Trigger class:** LOW (2-line secret-path fix; no logic change; no auth/DB/financial)

## §2 pre-dispatch busy-check

- **B3 prior state:** COMPLETE — rollback rehearsal PARTIAL ship (`520aa3f`). IDLE.
- **Other B-codes:** B1 IDLE; B2 (App) IDLE.
- Self-review acceptable: surgical 2-line patch in script you authored. A reviews the diff.

## What you're fixing

AI Head A verified Director's actual 1Password vault names via `op vault list` + `op item list`. The script's current `op://` paths are wrong:

| Line | Current (wrong) | Correct |
|---|---|---|
| `scripts/cortex_rollback_v1.sh:49` | `op://Private/Render API Key/credential` | `op://Baker API Keys/API Render/credential` |
| `scripts/cortex_rollback_v1.sh:50` | `op://Private/Baker DB URL/credential` | `op://Baker API Keys/DATABASE_URL/credential` |

Both corrected paths verified by AI Head A — resolved to live secrets cleanly:
- `op read 'op://Baker API Keys/API Render/credential' | head -c 8` → `rnd_KfUr` (valid Render API key prefix)
- `op read 'op://Baker API Keys/DATABASE_URL/credential' | head -c 12` → `postgresql:/` (valid Postgres URL prefix)

Vault name is **`Baker API Keys`** (note the spaces — the `op://` path supports them as-is, no URL-encoding needed). Item names are **`API Render`** and **`DATABASE_URL`**, not `Render API Key` / `Baker DB URL`.

## Steps

```bash
cd ~/bm-b3
git checkout main
git pull -q
git checkout -b rollback-script-op-path-fix-1

# Apply the 2-line patch — exact strings:
#   line 49: 'op://Private/Render API Key/credential' → 'op://Baker API Keys/API Render/credential'
#   line 50: 'op://Private/Baker DB URL/credential'   → 'op://Baker API Keys/DATABASE_URL/credential'

# Verify the patched script still parses and exit-1's on no-confirm:
bash -n scripts/cortex_rollback_v1.sh ; echo "parse=$?"
bash scripts/cortex_rollback_v1.sh ; echo "no-confirm=$?"  # must still print usage + exit 1

# Update the TODO comment at line 22-46 to reflect that paths are now verified
# (drop or rewrite the "B-code TODO" block — it's done).
```

## PR

Title: `ROLLBACK_SCRIPT_OP_PATH_FIX_1: correct 1Password vault paths verified by Director`

Body:
```
Closes plan §5.2 step 3 (op:// vault verification) and §6 Q4 (rollback drill PASS).

AI Head A ran `op vault list` + `op item list --vault "Baker API Keys"` against
Director's actual 1Password account; the original guess paths (`op://Private/...`)
do not exist. Corrected to the verified item locations.

Both new paths resolved cleanly to live credential prefixes (8 + 12 chars) before
this PR was opened.

No logic change. 2-line patch + TODO-comment cleanup.
```

Trigger class LOW → A solo review (no second-pair). Tier-A merge on diff-review pass + own pytest if any tests touch the script (they don't).

## Output

- PR open + branch pushed
- Ship report: `briefs/_reports/B3_rollback_op_path_fix_20260428.md` — patched diff snippet + post-fix `bash -n` exit code + `bash <script>` no-confirm output
- Append to `briefs/_reports/B3_rollback_dry_rehearsal_20260428.md` § "Update — Q4 closure": "AI Head A verified vault paths against Director's `op vault list`; B3 patched in PR <#>; Q4 PASS on merge."
- Notify A in chat: PR # + ship report path + verdict line

After A merges → mailbox flip COMPLETE → DRY_RUN promotion gate Q4 fully cleared.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
