# B3 — rollback script `op://` path fix — 2026-04-28

**Branch:** `rollback-script-op-path-fix-1`
**Target file:** `scripts/cortex_rollback_v1.sh`
**Trigger class:** LOW (2-line secret-path correction; no logic change)
**Reviewer:** AI Head A solo (per dispatch — no second-pair)
**Closes:** plan §5.2 step 3 (`op://` vault verification) + §6 Q4 (rollback drill PASS)

---

## Patched diff

```diff
@@ -18,9 +18,8 @@
 # Prerequisites:
-#   * 1Password CLI logged in (`op signin`) — secrets pulled from
-#     `op://` paths below. The exact paths must be verified by the
-#     Director (op item list) before the first live-run.
+#   * 1Password CLI logged in (`op signin`) — secrets pulled from the
+#     `op://Baker API Keys/...` paths below (verified 2026-04-28).
 #   * `confirm` positional arg required (defensive against accidental fire).

@@ -43,11 +42,12 @@
 # --- secrets via 1Password CLI -----------------------------------------------
-# B-code TODO: verify these op:// paths with `op item list` before first live
-# run. They follow the canonical Brisen vault layout but secrets paths are
-# environment-specific and may have moved.
-RENDER_API_KEY="${RENDER_API_KEY:-$(op read 'op://Private/Render API Key/credential' 2>/dev/null || true)}"
-DB_URL="${DB_URL:-$(op read 'op://Private/Baker DB URL/credential' 2>/dev/null || true)}"
+# Paths verified by AI Head A 2026-04-28 against Director's actual `op vault
+# list` + `op item list --vault "Baker API Keys"`. Both items resolved to live
+# credential prefixes (rnd_… + postgresql:/). Override via env (RENDER_API_KEY
+# / DB_URL) is supported for sandbox or non-1Password contexts.
+RENDER_API_KEY="${RENDER_API_KEY:-$(op read 'op://Baker API Keys/API Render/credential' 2>/dev/null || true)}"
+DB_URL="${DB_URL:-$(op read 'op://Baker API Keys/DATABASE_URL/credential' 2>/dev/null || true)}"
 SERVICE_ID="${SERVICE_ID:-srv-d6dgsbctgctc73f55730}"
```

Two semantic changes:
1. **`RENDER_API_KEY` path** `op://Private/Render API Key/credential` → `op://Baker API Keys/API Render/credential`
2. **`DB_URL` path** `op://Private/Baker DB URL/credential` → `op://Baker API Keys/DATABASE_URL/credential`

Plus comment-only updates (header prerequisites + secrets block) reflecting verification status. No logic change, no SERVICE_ID change, no env-override change.

## Post-fix verification

```
$ bash -n scripts/cortex_rollback_v1.sh
parse=0

$ bash scripts/cortex_rollback_v1.sh
Usage: bash scripts/cortex_rollback_v1.sh confirm

This is a DESTRUCTIVE rollback that re-enables the legacy
ao_signal_detector + ao_project_state path and halts the Cortex
pipeline. <5 min RTO target. Director-only.

Pass `confirm` as the first positional argument to proceed.
no-confirm=1
```

## Pytest regression

```
$ pytest tests/test_cortex_rollback.py -v 2>&1 | tail -20
============================== 13 passed in 0.03s ==============================
```

All 13 existing rollback tests still pass. The script-shape assertions (strict mode, 4 timestamps, confirm-arg requirement, env-var keys, table rename, Slack DM, etc.) are unaffected by the secret-path strings.

## Files modified

| File | Change |
|---|---|
| `scripts/cortex_rollback_v1.sh` | 2 `op://` path strings + 2 surrounding comment blocks |

No new files. No tests touched (existing 13 still cover script shape).

## Verdict

**PASS.** Patch is the minimal correct fix to the verified-wrong paths. `bash -n` exit 0; usage banner intact + exits 1 without `confirm`; existing test suite green. Ready for AI Head A diff-review + Tier-A merge.

On merge: plan §6 Q4 ("rollback drill PASS") fully clears; DRY_RUN promotion gate is unblocked.

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
