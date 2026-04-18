# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous reports:**
- `briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`
- `briefs/_reports/B1_kbl_a_prereq_install_20260418.md` (just shipped)
**Runbook:** [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** prereq install task (shipped)

---

## Task: Runbook Step 3 — Run `install_kbl_mac_mini.sh`

Director authorized B1 to execute Step 3 directly (speed play). Scope strictly limited to the script execution — you do NOT populate secrets, do NOT commit to baker-vault.

### What to do

1. `ssh macmini`
2. `cd` to the baker-master clone (you confirmed it exists in prereq install — re-confirm path)
3. `git pull --ff-only origin main` — ensure the KBL-A merge commit is pulled locally
4. Run `scripts/install_kbl_mac_mini.sh`
5. Capture full stdout + stderr to a local file on the Mac Mini (e.g., `/tmp/kbl_install_20260418.log`) in case of surprise
6. Observe exit code + final state
7. Enumerate what the script created: `~/.kbl.env` (should be scaffold with TODO markers), LaunchAgent plist at `~/Library/LaunchAgents/`, any created directories

### Report structure

File at `briefs/_reports/B1_kbl_a_step3_install_20260418.md`:

- **TL;DR:** script ran clean / partial / failed
- **Exit code + key output:** first 20 + last 20 lines of install log
- **What landed:** list of files created + any systemd/LaunchAgent registrations
- **What's waiting for Director:** exact hand-off for Step 4 — which 5 secrets need to be populated in `~/.kbl.env`, with names and a 1-line description each (pull from the env.mac-mini.yml or the install script itself)
- **Sanity checks** you can run without secrets: `yq . env.mac-mini.yml` parses clean, LaunchAgent plist loads without error, etc.

### Scope guardrails (STRICT)

- **Do NOT** populate `~/.kbl.env` secrets (ANTHROPIC_API_KEY, DATABASE_URL, etc.). Leave scaffold as-is.
- **Do NOT** commit `config/env.mac-mini.yml` to baker-vault. If install script created a template locally, leave it local.
- **Do NOT** flip `KBL_FLAGS_PIPELINE_ENABLED` or load the LaunchAgent (`launchctl load ...`). Install ≠ start.
- **Do NOT** run the pipeline tick manually for testing.
- If the script fails, stop + report. Don't debug-and-re-run — let AI Head + Director triage first.

### Dispatch back

Chat one-liner:

> B1 Step 3 done — see `briefs/_reports/B1_kbl_a_step3_install_20260418.md`, commit `<SHA>`. Status: <CLEAN / failed at X>. Director: ready for Step 4 (populate 5 secrets in `~/.kbl.env`).

---

## Est. time

~15 minutes (script is fast; most time in reporting + capturing hand-off for Director).

---

*Dispatched 2026-04-18 by AI Head.*
