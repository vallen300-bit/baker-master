# Brisen Lab — SessionStart hook (per-clone .claude/settings.json mutations)

**Status:** in production (5 watched terminals + b5 launcher) since 2026-05-01.
**Owner:** AI Head A (operator). Authored by B5 closing BRISEN_LAB_1.
**Audit-trail PR:** baker-master `b5/brisen-lab-1-completion` (this file is the doc-note).

## Why this is a doc-note, not tracked config

Brisen Lab observes 6 watched Claude Code clones (lead/deputy on `~/Desktop/baker-code` + `~/bm-b{1..4}`) plus the b5 launcher. Each clone's `.claude/settings.json` is mutated to install the SessionStart hook at `/Users/dimitry/forge-agent/session-start-hook.sh`.

These files **cannot be tracked in git** because:
1. **Absolute-path coupling:** the hook script lives at `/Users/dimitry/forge-agent/...` — Director-machine-specific.
2. **Per-clone divergence:** Desktop/baker-code preserves prior PostToolUse + PreToolUse hooks (e.g., `syntax-check.sh`); bm-b1..b4 only need SessionStart. Tracking one canonical version would either wipe Desktop's existing hooks on pull, or invent cross-clone hook references that 404 silently when the hook scripts don't exist in those clones.
3. **No semantic version drift:** these are environment-bind files, not code. The right primitive is "install via setup script", not "track in git".

PR shape was Director-authorized 2026-05-01 (Option a) since AI Head A was unavailable for the L48-49 mailbox question. AI Head A — please ack on next session: (i) ~/.zshrc surgical-inject divergence from brief L859-864 (preserves `--name` + `--append-system-prompt` persona flags; AI Head B endorsed); (ii) this doc-note PR shape.

## Where the hook script lives

`/Users/dimitry/forge-agent/session-start-hook.sh` — chmod +x, contract: **always exits 0**, all branches guarded by `|| true`. Reads stdin JSON (Claude Code passes hook input there), parses `session_id` + `cwd`, atomically writes `~/forge-agent/sessions.json` (tempfile + `os.replace`), POSTs `/api/register` to brisen-lab.onrender.com with `--max-time 5`.

Implementation file: `/Users/dimitry/forge-agent/session-start-hook.sh` (45 lines). Authoritative copy is on the Director's MacBook; this repo only documents it.

## FORGE_TERMINAL convention

Each watched terminal's shell function (zsh) prefixes the `claude` invocation with `FORGE_TERMINAL=<alias>`. The SessionStart hook reads that env var to know which Brisen Lab card the new session belongs to. Aliases:

| Alias | Worktree | Shell function | Notes |
|---|---|---|---|
| `lead` | `~/Desktop/baker-code` | `aihead1` | AI Head A; persona flags preserved |
| `deputy` | `~/Desktop/baker-code` | `aihead2` | AI Head B; persona flags preserved |
| `b1` | `~/bm-b1` | `b1` | B-code build pool |
| `b2` | `~/bm-b2` | `b2` | B-code build pool |
| `b3` | `~/bm-b3` | `b3` | B-code build pool |
| `b4` | `~/bm-b4` | `b4` | B-code build pool |
| `b5` | `~/bm-b5` | `b5` | Launcher injects FORGE_TERMINAL but agent.py WORKTREES does **not** include b5 — see "Watched-set divergence" below |

If `FORGE_TERMINAL` is unset (terminals not on the watched list), the hook exits 0 with no side effects.

## Per-clone settings.json shape

All 5 watched-clone `.claude/settings.json` files contain a `SessionStart` hook entry of this shape:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "/Users/dimitry/forge-agent/session-start-hook.sh",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

`~/Desktop/baker-code/.claude/settings.json` additionally preserves prior `PostToolUse` + `PreToolUse` hooks. `~/bm-b{1..4}/.claude/settings.json` files were created fresh for this brief (no prior hooks). `~/bm-b5/.claude/settings.json` was deliberately NOT modified — see below.

## Watched-set divergence: b5 launcher vs. agent.py WORKTREES

**Director-side reality (post-provisioning 2026-05-01):**
- Director added `FORGE_TERMINAL=b5` to the b5 zshrc launcher (line 25 per Director note).
- `~/bm-b5/.claude/settings.json` is **NOT** modified.
- `agent.py` `WORKTREES` map at `~/forge-agent/agent.py:36-43` does **NOT** include `b5`.

**Effective consequence:**
- Snapshots from `~/bm-b5` are NOT polled (agent doesn't scan the worktree).
- JSONL events from b5 sessions are NOT tailed (agent doesn't watch `~/.claude/projects/-Users-dimitry-bm-b5/`).
- The `FORGE_TERMINAL=b5` env var simply sits in the b5 shell session, observed by nothing.

If b5 should be a 7th watched terminal, the change required is:
1. Add `"b5": HOME / "bm-b5"` to `WORKTREES` in `~/forge-agent/agent.py:36`.
2. (Optional) Add `b5: briefs/_tasks/CODE_5_PENDING.md` to `MAILBOX_FILE` in `agent.py:45` if mailbox status surveillance is wanted.
3. Create `~/bm-b5/.claude/settings.json` with the SessionStart hook block above.
4. `launchctl kickstart -k gui/$(id -u)/com.brisen.lab-agent`.

**B5 closed BRISEN_LAB_1 with the watched-set at 6** (lead/deputy/b1-b4) per the brief's locked decision Q9. Director can promote b5 to watched-7 in a follow-up if useful.

## TCC-protected lead/deputy worktree

`~/Desktop/baker-code` is TCC-protected. launchd-spawned processes can't run `git` inside it without explicit Files-and-Folders grant. Symptom: `agent.err.log` shows `fatal: Unable to read current working directory: Operation not permitted` on every snapshot poll for lead+deputy. `forge_snapshots` rows for those aliases show `git_branch=null, git_head_sha=null, git_head_subject=null` while `daemon_last_seen` advances normally.

Director-side fix (one-time):
- System Settings → Privacy & Security → Files and Folders → enable **Desktop** for `/Users/dimitry/forge-agent/.venv/bin/python3`.
- `launchctl kickstart -k gui/$(id -u)/com.brisen.lab-agent`.

Until then: degraded but not broken. b1-b4 cards show full git info; lead/deputy show heartbeat + mailbox only.

## Operational reference

- **Render service:** `srv-d7q7kvlckfvc739l2e8g` (Frankfurt, Starter), URL https://brisen-lab.onrender.com.
- **Auto-deploy from:** `vallen300-bit/brisen-lab@main` (current `8d5db20` pins Python to 3.12.7 via `.python-version`; psycopg2-binary 2.9.9 is incompatible with Render's default 3.14).
- **Postgres:** same Neon DSN as baker-master. 3 tables: `forge_sessions` (id, session_uuid, terminal_alias, project_path, started_at, last_seen_at, ended_at), `forge_events` (id, session_uuid, terminal_alias, event_type, payload, occurred_at, received_at), `forge_snapshots` (one row per terminal_alias; upsert keyed; 11 cols incl. `daemon_last_seen`).
- **Auth:** `X-Forge-Key` header. Canonical key in 1Password "Baker API Keys" → "FORGE_KEY (brisen-lab)" (`wgz5eckjaxwezykogpghmui2be`). Set in (1) Render env, (2) `~/.zshrc`, (3) `~/Library/LaunchAgents/com.brisen.lab-agent.plist`.
- **launchd:** `com.brisen.lab-agent` (RunAtLoad+KeepAlive=true). Snapshot loop @ 30s; JSONL discover loop @ 2s.
- **Live QCs run 2026-05-01 (post-provisioning):** see `briefs/_reports/B5_brisen_lab_1_20260501.md` §"Live QC results".
