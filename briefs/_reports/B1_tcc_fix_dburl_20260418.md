# B1 Report — TCC Install Fix + DATABASE_URL to 1Password

**From:** Code Brisen #1
**To:** AI Head
**Task file:** `briefs/_tasks/CODE_1_PENDING.md`
**Date:** 2026-04-18
**Status:** ALL CLEAN

---

## TL;DR

Both deliverables shipped.

- **Deliverable 1 (TCC-safe install):** chose AI Head's preferred option **(b)** — templated plists + dropped `/usr/local/bin/` symlinks, plus a TCC refuse-guard (option (a) as cheap insurance). PR: <https://github.com/vallen300-bit/baker-master/pull/3>, commit `04b494b` on branch `kbl-a-tcc-fix`.
- **Deliverable 2 (DATABASE_URL to 1P):** item created in `Baker API Keys` vault, retrievable. Notes field documents format + source.

---

## Deliverable 1 — TCC-safe install

### Option picked: **(b) + cheap refuse-guard from (a)**

Rationale:

- **(b) core** — committed plists now carry a literal `__REPO__` placeholder in `ProgramArguments`. Install-time sed-substitutes `__REPO__` → resolved `$REPO`. Plist is the single source of truth for the script path; the `/usr/local/bin/kbl-*.sh` symlink layer is gone entirely. This matches the manual bandage already live on Mac Mini.
- **Refuse guard (from a)** — `$REPO` under `~/Desktop/`, `~/Documents/`, or `~/Downloads/` now fails fast with a clear `mv` remediation. Costs ~5 lines and prevents a next-operator-on-a-fresh-box from silently walking into the same TCC trap that ate the initial install.
- **Not (c)** — copying scripts to `~/.local/bin/` works, but changes install shape (scripts live in two places; git-pull updates don't flow until re-install). Option (b) keeps the clone as the single on-disk source of truth.

### Changes

1. `launchd/com.brisen.kbl.*.plist` (×4) — `ProgramArguments` path now `__REPO__/scripts/kbl-*.sh`.
2. `scripts/install_kbl_mac_mini.sh`:
    - TCC guard: refuses if `$REPO` is under `~/Desktop/`, `~/Documents/`, or `~/Downloads/`.
    - Default `KBL_REPO` changed from `~/Desktop/baker-code` → `~/baker-code`.
    - Symlink step dropped (no more `sudo ln -sf` to `/usr/local/bin/`).
    - `chmod +x` on scripts runs without sudo.
    - Plist install now `sed "s/__REPO__/${REPO_ESCAPED}/g"` into `~/Library/LaunchAgents/`.
    - Post-sed `grep __REPO__` guard — fails loud if substitution didn't run (stale placeholder → launchd silent fail, hard to diagnose).
    - Header doc + final validation section updated (lists plist script paths rather than `/usr/local/bin/` contents).
3. `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md §6`:
    - TCC note added explaining context + fix for future re-installs.
    - Acceptance criteria updated: TCC refuse check + `grep -L __REPO__` check on rendered plists replace the `ls /usr/local/bin/kbl-*` symlink count.

### Verification (local)

- `bash -n scripts/install_kbl_mac_mini.sh` — syntax OK.
- sed smoke test with `REPO=/Users/dimitry/baker-code` → rendered plist contains `/Users/dimitry/baker-code/scripts/kbl-pipeline-tick.sh`.
- TCC guard unit test: `REPO=~/Desktop/baker-code` refused; `REPO=~/baker-code` passed.

### Non-regression on live Mac Mini

Mac Mini is already running with manually-bandaged plists pointing at `~/baker-code/scripts/kbl-*.sh`. Re-running the new installer there will sed-substitute `__REPO__` → `/Users/dimitry/baker-code` and overwrite the manually-edited plists with **byte-identical** `ProgramArguments` — no regression to Step 6 state. `launchctl unload`/`load` cycle is a few-ms gap.

**Residue:** stale `/usr/local/bin/kbl-*.sh` symlinks from the original install remain on disk. They're unreferenced (plists don't point there anymore) and therefore harmless. Cleanup is one sudo command: `sudo rm /usr/local/bin/kbl-*.sh`. Intentionally not automated — would re-introduce sudo into the installer and defeat the "no-sudo-for-staging" goal of option (b).

### Artifacts

- **Branch:** `kbl-a-tcc-fix`
- **Commit:** `04b494b`
- **PR:** <https://github.com/vallen300-bit/baker-master/pull/3>
- **Status:** awaiting B2 review

---

## Deliverable 2 — DATABASE_URL to 1Password

### Procedure

1. Confirmed no existing `DATABASE_URL` item in `Baker API Keys` vault (28 items, none match).
2. Retrieved assembled URL from Mac Mini `~/.kbl.env` (`source && printf %s "$DATABASE_URL"` via ssh). Length 128. The URL was already assembled during the Steps 3+4+5 session (§6.3 of `B1_kbl_a_install_full_20260418.md`) — format: `postgresql://<USER>:<PASSWORD>@<HOST>:<PORT>/<DB>?sslmode=require` where USER and PASSWORD are `urllib.parse.quote()`'d from Render's split `POSTGRES_USER` / `POSTGRES_PASSWORD` vars.
3. Built API Credential JSON template via `op item template get 'API Credential'`, populated `credential` + `notesPlain` from env vars in a Python filter, piped to `op item create --vault 'Baker API Keys' -`. JSON-template path chosen over assignment statements (`credential='<url>'`) to avoid the URL appearing on the `op` command line (visible to `ps aux`).
4. Verified retrievable: `op item get 'DATABASE_URL' --vault 'Baker API Keys' --fields credential --reveal | head -c 40` → `postgresql://neondb_owner:npg_26tjJyupOS` (first 40 chars, matches Mac Mini `~/.kbl.env`).
5. Env vars unset in the same shell invocation.

### Item

- **Title:** `DATABASE_URL`
- **Vault:** `Baker API Keys` (id `fcyjwe5jjrx24l3hbr3ukdofci`)
- **Category:** `API_CREDENTIAL`
- **ID:** `t77jpmwqxwlm2x32jhcup7vjie`
- **Created:** 2026-04-18

### Notes field (stored verbatim in the item)

> Assembled DATABASE_URL for KBL-A Mac Mini install (2026-04-18). Format: `postgresql://<USER>:<PASSWORD>@<HOST>:<PORT>/<DB>?sslmode=require` — USER and PASSWORD are `urllib.parse.quote()`'d. Source: `POSTGRES_HOST`/`PORT`/`DB`/`USER`/`PASSWORD`/`SSLMODE` split env vars on Render service `srv-d6dgsbctgctc73f55730` (baker-master). Re-assemble if Render rotates the Postgres connection string. See `briefs/_reports/B1_kbl_a_install_full_20260418.md §6.3`.

### Verify output (first 40 chars only, per task guardrail)

```
postgresql://neondb_owner:npg_26tjJyupOS...
```

### `~/.kbl.env` migration — deferred per task

Task guardrail: "Update Mac Mini `~/.kbl.env` to pull from the new item on next rebuild (document in the report, don't re-populate now)."

**Future rebuild procedure** (for inclusion in the next `~/.kbl.env` regen script or runbook):

```bash
export OP_SERVICE_ACCOUNT_TOKEN="<from Director>"
{
  echo "export DATABASE_URL=\"$(op item get 'DATABASE_URL'     --vault 'Baker API Keys' --fields credential --reveal)\""
  echo "export ANTHROPIC_API_KEY=\"$(op item get 'API Anthropic' --vault 'Baker API Keys' --fields credential --reveal)\""
  echo "export QDRANT_URL=\"$(op item get 'API Qdrant'          --vault 'Baker API Keys' --fields credential --reveal)\""  # TBD: Qdrant URL vs key split
  echo "export QDRANT_API_KEY=\"$(op item get 'API Qdrant'      --vault 'Baker API Keys' --fields credential --reveal)\""
  echo "export VOYAGE_API_KEY=\"$(op item get 'API Voyager'     --vault 'Baker API Keys' --fields credential --reveal)\""
} > ~/.kbl.env
chmod 600 ~/.kbl.env
unset OP_SERVICE_ACCOUNT_TOKEN
```

**Caveat to verify at next rebuild:** `API Qdrant` may store URL+key as one combined credential or two separate fields. Current Mac Mini `~/.kbl.env` has them as two distinct values (split-populated during the original install). If the 1P item only holds one of the two, a second item or a multi-field refactor is needed. Flag for Director during next rebuild dispatch.

---

## Security hygiene (this session)

- `OP_SERVICE_ACCOUNT_TOKEN` was already present in local env from the previous session; re-used without re-provisioning.
- DB URL value was pulled into a single bash variable, passed to `op` via JSON template on stdin (not via command-line args), and `unset` immediately after create.
- No value written to disk outside of 1Password. `~/.kbl.env` on Mac Mini unchanged (already populated in Steps 3+4+5).
- Nothing echoed to stdout beyond the documented first-40-char verify truncation.

Token cleanup at session end: `unset OP_SERVICE_ACCOUNT_TOKEN` (applies when Director closes the chat shell).

---

## Dispatch back

> B1 TCC + DB_URL done — see `briefs/_reports/B1_tcc_fix_dburl_20260418.md`, commit `04b494b` on branch `kbl-a-tcc-fix`. PR <https://github.com/vallen300-bit/baker-master/pull/3> awaiting B2 review. DATABASE_URL item in 1P `Baker API Keys` vault, retrievable, verified head=40. Standing by.
