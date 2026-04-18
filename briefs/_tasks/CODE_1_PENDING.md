# Code Brisen #1 — Pending Task

**From:** AI Head
**To:** Code Brisen #1 (terminal instance)
**Previous report:** [`briefs/_reports/B1_kbl_a_preinstall_verify_20260418.md`](../_reports/B1_kbl_a_preinstall_verify_20260418.md) — verification CLEAR / Mac Mini prereqs BLOCKED
**Runbook paired:** [`briefs/_runbooks/KBL_A_MERGE_RUNBOOK.md`](../_runbooks/KBL_A_MERGE_RUNBOOK.md)
**Task posted:** 2026-04-18
**Status:** OPEN — awaiting execution
**Supersedes:** verification + runbook task (both shipped)

---

## Task: Mac Mini Prereq Install (fix the 5 failures you flagged)

### Context

Your verification caught 5 missing prereqs on Mac Mini that would make `install_kbl_mac_mini.sh` exit 1 at its sanity check. Fixing them now — **in parallel with Director's PR #1 merge** — means when Director runs the install script (post-merge Step 3 of the runbook), it runs clean.

**This is an execution task, not a report task.** You fix, you verify, you commit evidence, you report done.

### Constraints

- **Safe to run now:** Mac Mini is not yet running any KBL pipeline ticks (`KBL_FLAGS_PIPELINE_ENABLED=false` default, also `install_kbl_mac_mini.sh` hasn't been run yet). No risk of interfering with running production work.
- **Do NOT** run `install_kbl_mac_mini.sh` itself — that's Director's call post-merge per the runbook.
- **Do NOT** edit `~/.kbl.env` or populate secrets — that's the runbook's Step 4, Director-owned.
- **Do NOT** commit `env.mac-mini.yml` to baker-vault — that's Step 5, Director-owned.
- Scope is: (a) install missing Homebrew binaries, (b) install missing Python deps into the python3 that LaunchAgent uses, (c) verify fixes hold, (d) report.

### What to install

#### (a) Homebrew binaries (via `ssh macmini`)

```bash
ssh macmini 'brew install yq util-linux'
```

`util-linux` provides GNU `flock` (distinct from macOS native flock which has incompatible flags per D5).

#### (b) Python deps into LaunchAgent's python3

LaunchAgent PATH is `/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin` per the plist. Target python3 is `/opt/homebrew/bin/python3` (Python 3.14.4 per your report).

Install the full `requirements.txt` from `baker-master` into this python3. Two approaches:

**Option 1 (simpler, less isolated):** install globally on the target python3

```bash
ssh macmini '/opt/homebrew/bin/python3 -m pip install --user -r <baker-master>/requirements.txt'
```

(adjust `<baker-master>` to wherever the Mac Mini's baker-master clone lives — if it doesn't exist yet, that's a finding: the Mac Mini needs a baker-master clone before the install script can run. Flag in your report.)

**Option 2 (cleaner, more aligned with Python best practice):** create a venv at a known path, install there, patch the LaunchAgent plist or the pipeline wrapper to activate the venv before running Python.

**Recommendation:** Option 1 for now. Option 2 is a better end-state but touches the plist + wrapper, which is scope creep. Document Option 2 as a follow-up if you go Option 1.

If `requirements.txt` itself doesn't exist on the Mac Mini yet (because the baker-master clone isn't there), clone it first — that's a legitimate pre-install step (the runbook's Step 3 assumes a clone exists).

#### (c) Verify fixes

Re-run your original verification checks against the LaunchAgent PATH context:

```bash
ssh macmini '/bin/bash -c "PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin; \
  which yq flock python3; \
  /opt/homebrew/bin/python3 -c \"import psycopg2, yaml; print(psycopg2.__version__, yaml.__version__)\""'
```

All should now ✅ PASS.

Also re-run the install script's sanity checks (the lines you originally found failing, L26-L27 etc.) — confirm they pass, but **do NOT** run the install script itself end-to-end. Just verify the early sanity-check gates clear.

### Output format

File: `briefs/_reports/B1_kbl_a_prereq_install_20260418.md`

Sections:

1. **TL;DR:** all fixes landed / partial / blocked on X
2. **Before/after table:** each of the 5 originally failing checks, before status → after status
3. **What you installed:** exact commands run, versions landed (`brew install` output, `pip install` output versions)
4. **Followups:** any deferred items (Option 2 venv migration, missing baker-master clone, etc.)
5. **Evidence:** paste the verification command outputs showing all ✅ PASS

### Dispatch back

Chat one-liner:

> B1 Mac Mini prereqs installed — see `briefs/_reports/B1_kbl_a_prereq_install_20260418.md`, commit `<SHA>`. Status: <CLEAN / partial>.

---

## Scope guardrails

- **No secrets.** Do not create or populate `~/.kbl.env`.
- **No pipeline start.** Do not run `install_kbl_mac_mini.sh`, launch the LaunchAgent, or touch `KBL_FLAGS_PIPELINE_ENABLED`.
- **No production file edits.** LaunchAgent plist, crontab, systemd units — all off-limits.
- **DO** flag surprises (e.g., "baker-master clone doesn't exist on mac mini" → stop + report).
- **Time-box:** ~30 min. If install or verification takes >45 min, stop + flag.

---

## Est. time

~30 min:

- 10 min brew + pip install
- 10 min re-verify
- 10 min report + commit

---

*Dispatched 2026-04-18 by AI Head. Git identity: `Code Brisen 1` / `dvallen@brisengroup.com`. SSH to `macmini` via Tailscale.*
