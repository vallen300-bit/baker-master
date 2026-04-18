# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Runbook:** [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** previous Step-3-only and Render-API variants of this task

---

## Task: Runbook Steps 3 + 4 + 5 — Install + Secrets + env Config

Director authorized end-to-end. You execute Steps 3, 4, 5. Secrets via 1Password service account (cleanest long-term, aligns with D4 migration target).

---

## Secret access — 1Password service account

**Service account:** `Baker Automation`
**Vault:** `Baker API Keys`
**Access verified 2026-04-18 by AI Head** — service account has read access to the vault, `op vault list` + `op item list` both work.

**Director will paste `OP_SERVICE_ACCOUNT_TOKEN` directly in your chat session** when relaying this task. Set it in env only (not disk):

```bash
export OP_SERVICE_ACCOUNT_TOKEN="<paste value from Director's chat message>"
```

**Do NOT** save the token to disk (`~/.op/`, config files, scripts). **Do NOT** commit the token anywhere. **Do NOT** echo the full token to stdout in logs.

To retrieve secrets by name:

```bash
op item get "API Anthropic" --vault "Baker API Keys" --fields credential --reveal
op item get "API Voyager"   --vault "Baker API Keys" --fields credential --reveal
# etc. — by item name per the vault
```

---

## Prerequisites check

On Mac Mini (via `ssh macmini`):

```bash
brew install 1password-cli   # if not already installed
op --version                  # should be >= 2.30
```

If already installed, skip.

---

## Step 3 — Run `install_kbl_mac_mini.sh`

1. `ssh macmini`
2. `cd` to the baker-master clone (exists per your prereq install)
3. `git pull --ff-only origin main`
4. `./scripts/install_kbl_mac_mini.sh 2>&1 | tee /tmp/kbl_install_20260418.log`
5. Confirm exit 0
6. Enumerate what was created: `~/.kbl.env` scaffold, LaunchAgent plist, any new directories

---

## Step 4 — Populate `~/.kbl.env` via 1Password

**Enumerate the 5 (or N) required secrets from the scaffold:**

```bash
grep -E "^[A-Z_]+" ~/.kbl.env | grep -v "^#" | head -20
```

The scaffold defines the authoritative secret list. Your earlier brief's guess was ANTHROPIC_API_KEY / DATABASE_URL / VOYAGE_API_KEY / KBL_VAULT_PATH / (5th TBD) — trust the scaffold's TODO markers over my guess.

**Retrieve each from 1Password by name.** Best guess at mapping (verify against scaffold):

| Scaffold env var | 1Password item name |
|---|---|
| `ANTHROPIC_API_KEY` | `API Anthropic` |
| `VOYAGE_API_KEY` | `API Voyager` |
| `DATABASE_URL` | pull from Render (item `API Render` has Render API key; use it to read the `DATABASE_URL` value from baker-master service) OR check if vault has a direct `DATABASE_URL` item (search: `op item list --vault 'Baker API Keys' | grep -i database`) |
| Others | match scaffold names to vault items; flag unmatched in your report |

**If the scaffold requires a secret not obviously in the vault, stop and report** — do not guess. Director adds the missing item first.

**Populate `~/.kbl.env` with restricted perms:**

```bash
umask 077
op item get "API Anthropic" --vault "Baker API Keys" --fields credential --reveal > /dev/null  # sanity-check token auth
# Then edit ~/.kbl.env line by line using $(op item get ...) substitutions
# Example:
#   echo "ANTHROPIC_API_KEY=$(op item get 'API Anthropic' --vault 'Baker API Keys' --fields credential --reveal)" >> ~/.kbl.env
chmod 600 ~/.kbl.env
```

**Sanity check (not leak):**

```bash
source ~/.kbl.env && echo "${ANTHROPIC_API_KEY:0:10}..."
# Should print first 10 chars — confirms populated without exposing full key
```

---

## Step 5 — Commit `config/env.mac-mini.yml` to baker-vault

**Source of truth for values:** `briefs/KBL-A_INFRASTRUCTURE_CODE_BRIEF.md` §452-493 (the full yml example).

**Key sections (use ratified values):**

- `ollama.*` — model, fallback, temp, seed, top_p, keep_alive (per D1 §161)
- `matter_scope.allowed: ["hagenauer-rg7"]` — Phase 1 scope per D3
- `matter_scope.layer0_enabled: "true"`
- `gold_promote.*` — disabled=false, whitelist_wa_id (confirm Director's WA ID from CLAUDE.md: `+41 79 960 50 92`)
- `pipeline.*` — cron_interval_minutes=2, triage_threshold=40, max_queue_size=10000, qwen_recovery_after_signals=10, qwen_recovery_after_hours=1
- `cost.daily_cap_usd: "15"`, `max_alerts_per_day: "20"`
- **`flags.pipeline_enabled: "false"`** — critical, first tick must not run. Director flips later in Step 7.
- `observability.*` — rsync time `"23:50"`, size warn thresholds

**Procedure:**

1. Clone baker-vault if not already present in your workspace
2. Create or update `config/env.mac-mini.yml` with the ratified values
3. Commit + open PR against baker-vault main
4. Include PR URL in your report — Director merges

**DO NOT** flip `pipeline_enabled` to `true`. Step 7 is Director's.

---

## Report structure

File: `briefs/_reports/B1_kbl_a_install_full_20260418.md`

Sections:

1. **TL;DR** — all clean / partial / blocked
2. **Step 3 evidence** — install exit + enumerate created artifacts
3. **Step 4 evidence** — which N secrets populated (names only, never values), `chmod 600` confirmed, sanity-check output
4. **Step 5 evidence** — baker-vault PR URL + commit SHA
5. **Open items for Director** — Step 6 verification commands + Step 7 flag-flip procedure
6. **Issues encountered** — any scaffold secrets not matchable to vault items, any install surprises

---

## Security guardrails (STRICT)

- Service account token lives in `OP_SERVICE_ACCOUNT_TOKEN` env var only. `unset` it when done.
- **Never** commit the token, **never** echo full secret values in logs.
- **Never** paste secret values into report files — names only.
- `~/.kbl.env` perms = `600`.
- Temporary files in `/tmp/` holding any secret must be shredded: `rm -P` or `shred -u` before session end.

---

## Dispatch back

Chat one-liner:

> B1 Steps 3+4+5 done — see `briefs/_reports/B1_kbl_a_install_full_20260418.md`, commit `<SHA>`. Baker-vault PR `<URL>`. Director: ready for Step 6 (verify first tick green with pipeline_enabled=false).

---

## Est. time

~45 minutes total.

---

*Dispatched 2026-04-18 by AI Head. Director relays `OP_SERVICE_ACCOUNT_TOKEN` directly to B1 chat session. Service account is `Baker Automation`, access to `Baker API Keys` vault verified by AI Head 2026-04-18.*
