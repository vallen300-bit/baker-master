PENDING — BRISEN_LAB_1 BUILT_LOCALLY_AWAITING_DIRECTOR_PROVISIONING (b5, 2026-05-01).

## Status: BUILT_AWAITING_DIRECTOR

All four parts (Parts 1, 2, 4, 3) built and locally verified. Static QCs (#5, #6, #14, #15) pass. Live QCs (#1-4, #7-13, #16-20) paused pending Director-side provisioning per brief §Prerequisites + mailbox-original L20-21.

Full breakdown: `briefs/_reports/B5_brisen_lab_1_20260501.md`.

## What's ready

- **`~/brisen-lab-staging/`** — local git repo with 10-file root commit `851843a` (FastAPI app + db.py + render.yaml + start.sh + static/ + README + .gitignore). Will push to `vallen300-bit/brisen-lab` once Director creates the GitHub repo.
- **`~/forge-agent/`** — daemon files written: `agent.py`, `requirements.txt`, `sessions.json` (`{}`), `session-start-hook.sh` (chmod +x). Smoke-tested all 11 secret-scrub patterns + buffer + classify + project-dir encoding.
- **`~/Library/LaunchAgents/com.brisen.lab-agent.plist`** — written, `plutil` validates OK. NOT yet loaded (Director must replace `FORGE_KEY` placeholder + run `launchctl load`).
- **`~/.zshrc`** — 2 exports added (`FORGE_KEY` placeholder, `LAB_URL`). 6 function injections (b1-b4, aihead1, aihead2). Backed up at `~/.zshrc.bak.20260501`. b5 + aihead_biz + baker untouched. **Surgical inject preserved aihead1/2 persona flags** — diverges from brief L859-864 literal replacement, see report §Divergences (flagged for AI Head A review).
- **5 `.claude/settings.json`** files: Desktop preserves PostToolUse + PreToolUse + new SessionStart; bm-b1..b4 created with SessionStart only. All reference `/Users/dimitry/forge-agent/session-start-hook.sh` with `timeout: 10`.

## What Director must do (5 steps to unblock B5)

1. Create empty GitHub repo `vallen300-bit/brisen-lab`.
2. Create Render Web Service `brisen-lab` (Starter $7/mo, auto-deploy from `main`, connected to that GitHub repo).
3. Set Render env vars: `DATABASE_URL` (same Neon DSN as baker-master) + `FORGE_KEY` (e.g., `openssl rand -hex 32`).
4. Replace `__SET_BY_DIRECTOR_BEFORE_USE__` placeholder in `~/.zshrc` with the FORGE_KEY value, then `source ~/.zshrc` (or restart terminals).
5. Replace `__SET_BY_DIRECTOR_BEFORE_LOAD__` in `~/Library/LaunchAgents/com.brisen.lab-agent.plist` with same FORGE_KEY value, then run:
   ```
   python3 -m venv ~/forge-agent/.venv
   ~/forge-agent/.venv/bin/pip install -r ~/forge-agent/requirements.txt
   launchctl load ~/Library/LaunchAgents/com.brisen.lab-agent.plist
   ```

When all 5 done, signal B5 with: "BRISEN_LAB_1 prerequisites ready, resume".

## Open question for AI Head A

Mailbox L48-49 says open ONE PR in baker-master for the `.claude/settings.json` edits. But these 5 files (a) are not currently tracked in git, (b) have absolute Director-machine-specific paths, (c) have different content per clone (Desktop has 3 hooks, b1-b4 have 1 each). Committing them as-is would either create cross-clone hook references or wipe Desktop's existing PostToolUse/PreToolUse on next pull.

Three viable resolutions — please pick one:
1. **Track `.claude/settings.json` in git as-is** (Desktop's full version, with its absolute paths). On next pull from b1-b4 they get cross-clone hook refs that fail silently (`syntax-check.sh` etc. don't exist in those clones, hooks just error and Claude Code continues).
2. **Open a doc-note PR** at `_ops/processes/brisen-lab-session-start-hook.md` documenting the local edits (audit trail; doesn't pollute git with clone-specific files).
3. **No baker-master PR** — only the brisen-lab repo PR. The .claude/settings.json edits remain per-clone untracked, as they have always been.

Default if no response: option 2 (doc note). Will execute when prerequisites unblock.

## Resume protocol when unblocked

1. `cd ~/brisen-lab-staging && git remote add origin git@github.com:vallen300-bit/brisen-lab.git && git push -u origin main`.
2. Wait for Render auto-deploy. `curl https://brisen-lab.onrender.com/healthz` → `{"ok": true}` (QC #1).
3. Verify Postgres bootstrap: `psql $DATABASE_URL -c "\dt forge_*"` → 3 tables (QC #2).
4. Verify launchd: `launchctl list | grep brisen.lab-agent` (QC #3) + `tail -f ~/forge-agent/agent.log` (QC #4).
5. Run remaining live QCs #7-13, #16-20.
6. Open PR(s) per AI Head A's resolution to the open question above.
7. Append lessons to `tasks/lessons.md`.
8. Overwrite this file with `COMPLETE` + final report reference.

## Reference

- Brief: `briefs/BRIEF_BRISEN_LAB_1.md`
- Build report: `briefs/_reports/B5_brisen_lab_1_20260501.md`
- Brisen-lab staging: `~/brisen-lab-staging/` (commit `851843a`)
- Forge-agent: `~/forge-agent/`
- Plist: `~/Library/LaunchAgents/com.brisen.lab-agent.plist`
- zshrc backup: `~/.zshrc.bak.20260501`
