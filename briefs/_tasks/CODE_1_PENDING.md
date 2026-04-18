# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous:** Install steps 3+4+5 shipped (`fba1d9b`), SIGPIPE hotfix landed via PR #1 merge (`3f130f1`)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution

---

## Task: TCC/Desktop Install Fix + DATABASE_URL to 1Password

Two quick cleanups from the install session's unresolved items. ~40 min combined.

### Deliverable 1 — TCC-safe install script

**Problem:** macOS 15 launchd can't execute scripts under `~/Desktop` due to TCC restrictions. Current install bandaged by editing plists on Mac Mini to bypass `/usr/local/bin/` symlinks and point at `~/baker-code/` directly. Anyone running `install_kbl_mac_mini.sh` fresh from a Desktop clone will hit the same failure.

**Fix (pick one, document rationale):**

**(a)** Install script detects clone location at runtime. If `$(git rev-parse --show-toplevel)` is under `~/Desktop/`, script refuses with a clear error + recommends `mv ~/Desktop/baker-code ~/baker-code` then re-run.

**(b)** Install script skips `/usr/local/bin/` symlinks entirely. Plists reference the clone path directly (same as the manual fix I applied). Removes root-owned symlinks as an install artifact.

**(c)** Install script copies the scripts into `~/.local/bin/kbl-*.sh` (user-owned, non-TCC-protected) and plists reference that. Keeps install self-contained under user home.

AI Head preference: **(b)** — least install surface, no sudo required, plist is the single source of truth for script path. (c) is also good but changes install shape.

Add a short note to the KBL-A brief `§install` section explaining the TCC context for future re-installs.

**PR against main.** Branch: `kbl-a-tcc-fix`. B2 reviews before merge.

### Deliverable 2 — DATABASE_URL to 1Password

**Problem:** Render has split `POSTGRES_HOST/PORT/DB/USER/PASSWORD/SSLMODE` env vars. Assembly into a single `DATABASE_URL` required a Python hack (§6.3 of install report). Future automation will repeat.

**Fix:** Add a `DATABASE_URL` item to the 1Password `Baker API Keys` vault. Value = the already-assembled URL with `urllib.parse.quote` applied to special chars. Document the format in the item's notes field.

**Procedure:**

1. On Mac Mini via `ssh macmini`, `export OP_SERVICE_ACCOUNT_TOKEN=...` (from `/tmp/b1-op.env` if still present, else Director re-provides)
2. Retrieve split vars via Render API (you know the pattern from §6.3)
3. Assemble URL
4. Create new 1P item: `op item create --category 'API Credential' --vault 'Baker API Keys' --title 'DATABASE_URL' credential='<url>'`
5. Verify: `op item get 'DATABASE_URL' --vault 'Baker API Keys' --fields credential --reveal | head -c 40` (just to confirm retrievable)
6. Update Mac Mini `~/.kbl.env` to pull from the new item on next rebuild (document in the report, don't re-populate now)

### Report

File: `briefs/_reports/B1_tcc_fix_dburl_20260418.md`

- Deliverable 1: which option (a/b/c) picked + rationale + PR URL
- Deliverable 2: 1P item created (name only, no value) + verify output (first 40 chars of URL, NOT full value)

### Scope guardrails

- **Do NOT** touch the bandaged plist paths on Mac Mini (they're live and working — don't regress Step 6 state)
- **Do NOT** commit secrets to git in any form
- Token hygiene: `unset OP_SERVICE_ACCOUNT_TOKEN` at session end

### Dispatch back

> B1 TCC + DB_URL done — see `briefs/_reports/B1_tcc_fix_dburl_20260418.md`, commit `<SHA>`. PR `<URL>` for TCC fix. Standing by.

---

## Est. time

~40 min:

- 20 min TCC fix (option b) + PR
- 10 min DATABASE_URL to 1P
- 10 min report

---

*Dispatched 2026-04-18 by AI Head.*
