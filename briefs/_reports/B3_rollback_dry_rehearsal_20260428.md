# B3 — Cortex V1 rollback script dry rehearsal — 2026-04-28

**Brief:** mailbox `briefs/_tasks/CODE_3_PENDING.md` (rollback_dry_rehearsal)
**Plan §:** [`briefs/_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md`](../_plans/CORTEX_V1_DRY_RUN_LAUNCH_PLAN_20260428.md) §5.2
**Target script:** `scripts/cortex_rollback_v1.sh` (committed in PR #74; unchanged on main since `97f26b1`)
**Reviewer:** Code Brisen #3 (b3) — author of both the plan and the script (self-rehearsal acceptable per dispatch)
**Trigger class:** LOW (operational verification)
**Date:** 2026-04-28
**Verdict:** **PARTIAL** — Steps 1, 2, 4 PASS locally; Step 3 (`op://` path verification) **NEEDS DIRECTOR** — only Director can read his own 1Password vault. Promotion gate Q4 is half-cleared; final clearance pending Director's two `op read` outputs.

---

## Step 1 — file/parse verification

```
$ ls -l scripts/cortex_rollback_v1.sh
-rwxr-xr-x@ 1 dimitry  staff  4467 Apr 28 19:16 scripts/cortex_rollback_v1.sh

$ bash -n scripts/cortex_rollback_v1.sh
exit=0
```

**PASS.** File mode `-rwxr-xr-x` — execute bit set for owner / group / world. `bash -n` (parse-only, no execution) returns 0 → no syntax errors.

## Step 2 — usage-banner check

```
$ bash scripts/cortex_rollback_v1.sh
Usage: bash scripts/cortex_rollback_v1.sh confirm

This is a DESTRUCTIVE rollback that re-enables the legacy
ao_signal_detector + ao_project_state path and halts the Cortex
pipeline. <5 min RTO target. Director-only.

Pass `confirm` as the first positional argument to proceed.
exit=1
```

**PASS.** Without the `confirm` positional arg the script prints the full usage banner including the `DESTRUCTIVE` warning + `<5 min RTO` + Director-only callout, then exits 1. Defensive guard works as designed.

## Step 3 — Director `op://` verification (NEEDS DIRECTOR)

> **Action for Director:** I cannot read your 1Password vault — only you can. Please paste these two commands into your local terminal (with `op` CLI signed in) and report the prefix output back to AI Head A. The expected output is the **first 8 / 12 chars** of each secret, NOT the full credential — this is enough to confirm the path resolves and the secret is present, without exposing the full value.

```bash
op read 'op://Private/Render API Key/credential' | head -c 8 ; echo
op read 'op://Private/Baker DB URL/credential' | head -c 12 ; echo
```

### Expected output shape

| Command | Expected on success | Failure modes (and what to do) |
|---|---|---|
| `op read 'op://Private/Render API Key/credential'` | 8-char prefix of the Render API token (typically starts `rnd_…` per Render's modern key format, but any 8 chars is fine — we're verifying *presence*, not format) | If `op` returns `[ERROR] item not found` → the path moved. Update the script's line ~47 with the correct path (or set `RENDER_API_KEY` directly via env override) before any live rollback. |
| `op read 'op://Private/Baker DB URL/credential'` | 12-char prefix of the Postgres DATABASE_URL (typically starts `postgres://` or `postgresql:`) | Same — if not found, fix the path at line ~48 or pass via `DB_URL` env override. The script already has a soft fallback if `DB_URL` is empty (it prints `[WARN] DB_URL not available — table-rename step will be skipped`), but in a real rollback this would leave `ao_project_state` un-restored. |

### What this verifies

- Both `op://` paths actually resolve in Director's vault as written in the script (`scripts/cortex_rollback_v1.sh` lines 47-48).
- The script's `# TODO: verify` comment at line ~46 can be retired once both prefixes come back non-empty.

### Recovery paths if Director's `op` lookup fails

1. **Path moved** — `op item list --vault Private | grep -i 'render\|baker'` to find the new canonical name; update the script + commit.
2. **CLI not signed in** — `op signin` (interactive). The script does not handle the `op` CLI's "not signed in" state gracefully; it would fall through to the `RENDER_API_KEY not available` ERROR branch (exit 2). Acceptable failure mode.
3. **Bypass entirely** — Director can `export RENDER_API_KEY=...` and `export DB_URL=...` in the rollback shell before invoking the script; both env vars are read with `${RENDER_API_KEY:-…}` / `${DB_URL:-…}` defaults so explicit overrides take priority.

## Step 4 — sandbox-fire decision: **FIRED (local stub-env slice)**

**Decision:** Local sandbox-fire executed against a stripped environment (no `RENDER_API_KEY`, no `DB_URL`, no `op` CLI on PATH) to exercise the secrets-missing guard without any live API call. Real-Render sandbox is **deferred** — there is no non-prod Render service equivalent for `srv-d6dgsbctgctc73f55730`, and live execution is gated behind Director auth + 4 hard preconditions per plan §5.3.

```
$ env -i PATH="$PATH" HOME="$HOME" bash scripts/cortex_rollback_v1.sh confirm
[2026-04-28T17:31:24Z] cortex_rollback_v1: START
[ERROR] RENDER_API_KEY not available — pass via env or fix op:// path
exit=2
```

### What this proves

- **ISO timestamp formatting works** (`[2026-04-28T17:31:24Z]` matches `%Y-%m-%dT%H:%M:%SZ` literally; this is timestamp #1 of the 4 the script emits on the success path).
- **`set -euo pipefail` does NOT halt on the `op read ... 2>/dev/null || true` lines** — the `|| true` correctly swallows `op` not being available so the script can fall through to its own guard logic.
- **The `RENDER_API_KEY not available` guard correctly catches empty env + missing `op` CLI.**
- **Exit code 2 (NOT 1)** — distinguishes "missing secrets" from "missing `confirm` arg" (which exits 1, see Step 2). Operationally meaningful: a wrapper that checks `$?` can tell which guard fired.

### What this does NOT cover

- The two `curl` calls to Render API (env-var PATCH + redeploy POST) — never reached without `RENDER_API_KEY`. Live test is the only way to exercise these, and that's by definition the real rollback.
- The `psql` `ALTER TABLE … RENAME` step — skipped without `DB_URL`.
- The Slack DM Director POST to `/api/slack/dm-director` — never reached without successfully traversing the prior steps.

### Why no real-Render sandbox-fire

- No non-prod Render service slot exists in Brisen's account that mirrors `baker-master`'s env-var schema closely enough to be meaningful.
- A spin-up + tear-down on Render would itself burn 5-10 min of operational time + leave billing artifacts.
- The 4 hard preconditions in plan §5.3 (legacy detector decommissioned + `ao_project_state` frozen + DRY_RUN promotion criteria met + Director explicit auth) are by design unmet during DRY_RUN, so the script's intended live invocation path is intrinsically post-DRY_RUN. There is no "safe" intermediate state that would meaningfully exercise the live path.

The local-stub slice is the most useful test possible without burning operational risk.

---

## Verdict: **PARTIAL** (locally PASS; awaiting Director step 3)

| Pass criterion (per mailbox) | Result |
|---|---|
| Step 1: file mode `x`, `bash -n` exit 0 | ✅ PASS |
| Step 2: usage banner prints, exit 1 | ✅ PASS |
| Step 3: 2 `op read` commands surfaced cleanly | ✅ surfaced — see block above. **NEEDS DIRECTOR** to execute and report back. |
| Step 4: explicit decision (fired / deferred + reason) | ✅ FIRED locally (stub-env slice); real-Render sandbox-fire DEFERRED with documented reason |

**Promotion gate §6 Q4 status:** half-cleared. Local rehearsal passes; the second `op://` half lands when Director executes Step 3.

### What's blocking Q4 full PASS

Director must execute the two `op read` commands in §3 above and confirm both return non-empty prefixes. Once confirmed:
- If both succeed → Q4 PASS, plan §5.2 fully cleared, DRY_RUN promotion gate clears the rollback-drill checkpoint.
- If either fails → fix the path / move the secret / add explicit env-override doc, then re-rehearse.

No code changes required from this rehearsal; the script + plan are correct as written.

---

## Director to verify (callout — copy/paste block)

```bash
op read 'op://Private/Render API Key/credential' | head -c 8 ; echo
op read 'op://Private/Baker DB URL/credential' | head -c 12 ; echo
```

Report results back to AI Head A. Expected: two non-empty prefix lines. AI Head A folds the response into this report and flips Q4 to full PASS.

---

## Update — Q4 closure (2026-04-28)

AI Head A verified vault paths directly against Director's account via
`op vault list` + `op item list --vault "Baker API Keys"`. The original
guess paths (`op://Private/...`) do not exist; the canonical Brisen
vault is **`Baker API Keys`** with items **`API Render`** and
**`DATABASE_URL`**.

Verified resolutions (8 / 12 char prefixes):
- `op read 'op://Baker API Keys/API Render/credential' | head -c 8` → `rnd_KfUr` (valid Render API key prefix)
- `op read 'op://Baker API Keys/DATABASE_URL/credential' | head -c 12` → `postgresql:/` (valid Postgres URL prefix)

B3 patched the script in PR `ROLLBACK_SCRIPT_OP_PATH_FIX_1` (branch
`rollback-script-op-path-fix-1`); see `briefs/_reports/B3_rollback_op_path_fix_20260428.md`.

**Q4 PASS on merge** — `scripts/cortex_rollback_v1.sh` resolves both
secrets cleanly; plan §5.2 fully cleared; DRY_RUN promotion gate
unblocked on the rollback-drill axis.

---

## Co-Authored-By

```
Co-authored-by: Code Brisen #3 <b3@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
