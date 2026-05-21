---
brief_id: AID_EDGE_SCOUT_VAULT_CACHE_1
author: AH1-Terminal (lead)
dispatched_by: lead
target: b1
target_repo: baker-vault (+ Mac Mini via ssh macmini)
created: 2026-05-21
status: dispatched
deadline: 2026-05-23T12:00:00Z (Saturday, ~5h before Mac Mini's first launchd fire @ 17:00 UTC)
parent_dispatch: ~/baker-vault/_01_INBOX_FROM_CLAUDE/2026-05-21-AID-edge-scout-cron-egress-fix.md
---

# BRIEF_AID_EDGE_SCOUT_VAULT_CACHE_1 — pre-fetch edge-scout feeds via Mac Mini

### Surface contract: N/A — Mac Mini launchd job + skill doc edit + vault cache dir; no clickable surface.

## Problem

`aidennis-edge-scout` weekly cron (trigger `trig_01BjL6NYoTFWwVMLs1mGXFTT`, fires Sun 18:00 UTC) returned uniform HTTP 403 on all 4 source feeds in its execution environment on 2026-05-17 (W20). AID Terminal fetches the same feeds fine — block is environment-specific to the cron's Anthropic Managed Agent context, not source-side.

W20 backfilled manually by AID. Without intervention, W21 (Sun 2026-05-24) fails the same way.

Cron context already has baker-vault cloned (per trigger config `sources: [git_repository: vallen300-bit/baker-vault]`). So the cron can `Read` feed XMLs from the local checkout — zero egress dependency — IF we pre-fetch them into the vault before the cron fires.

## Architecture

1. **Mac Mini Saturday launchd job** (17:00 UTC, 1h before cron) fetches the 4 feeds, writes XMLs to `baker-vault/_ops/edge-scout-cache/`, commits + pushes.
2. **AID skill prompt** (`~/.claude/skills/aidennis-edge-scout/SKILL.md`) updated: Step 2 swaps WebFetch calls for `Read` against the cached files.
3. **Cron trigger config** (RemoteTrigger update) — AH1 handles post-ship after Mac Mini side verifies.

Mac Mini already runs a daily launchd pipeline + has full egress + already commits to baker-vault. No new infra; piggyback on existing pattern. See `feedback_macos_tcc_launchd_blocks_desktop.md` — scripts deploy to `~/Library/Application Support/baker/`, NEVER under `~/Desktop`.

## Constraints

1. **API version/endpoint:** N/A (RSS/atom HTTP GET).
2. **Deprecation check date:** N/A.
3. **Fallback note:** if any feed returns non-200 in pre-fetch, keep the previous cached XML in place (don't overwrite with empty) and log `<source>_last_fetch_failed: <ISO>` to `_ops/edge-scout-cache/_status.json`. Cron reads the still-valid cached XML for that source.
4. **Migration-vs-bootstrap DDL check:** N/A.
5. **Ship gate:** literal end-to-end fire (script-run-once locally + verify 4 XMLs land + commit succeeds) — no "by inspection".
6. **Test plan:**
   - Unit test of the bash script's argument parsing + curl construction via shellcheck + a dry-run mode.
   - Live fire-once test in B1's working dir: run script once, verify 4 XMLs land in `_ops/edge-scout-cache/`, verify commit message format, verify push.
   - Post-ship verify on Mac Mini: SSH macmini, install plist, `launchctl kickstart -k gui/$(id -u)/com.baker.edge-scout-prefetch`, verify launchd log + git commit lands.
7. **`file:line` citation verification:** none — new files.
8. **Singleton pattern:** N/A.
9. **Post-merge script handoff:** the launchd plist + script install on Mac Mini is part of this brief (Step 4 below) — not a separate post-merge handoff.
10. **Invocation-path audit (Amendment H):** N/A — not a Pattern-2 capability.

## Acceptance criteria

### 1. Pre-fetch script — baker-vault `scripts/edge-scout-prefetch.sh`

Executable bash script. Fetches the 4 feeds, writes to `_ops/edge-scout-cache/`, commits + pushes.

Requirements:
- Shebang `#!/usr/bin/env bash` + `set -euo pipefail`.
- 4 sources hard-coded as `(name, url)` pairs:
  - `simonwillison` → `https://simonwillison.net/atom/everything/`
  - `hamel` → `https://hamel.dev/index.xml`
  - `eugeneyan` → `https://eugeneyan.com/rss/`
  - `huggingface` → `https://huggingface.co/blog/feed.xml`
- Output paths: `_ops/edge-scout-cache/<name>.xml` (always overwrite on success).
- HTTP fetch: `curl -fsSL --max-time 60 -A "BakerEdgeScoutPrefetch/1.0 (+https://brisengroup.com)" -o "$TMP" "$URL"`. On success: `mv "$TMP" "$DEST"`. On failure: leave existing `$DEST` alone, increment failure counter.
- Status JSON: write `_ops/edge-scout-cache/_status.json` after all 4 fetches with shape `{"generated": "<ISO>", "sources": {"simonwillison": {"status": "ok|fail", "last_success": "<ISO>", "size_bytes": N, "fetch_error": "<str>|null"}, ...}}`.
- Git workflow: `cd $VAULT_DIR && git fetch origin main && git reset --hard origin/main` (clean slate to avoid drift) → run fetches → `git add _ops/edge-scout-cache/` → `git commit -m "cache(edge-scout): pre-fetch $(date -u +%FT%TZ)"` → `git push origin main`. Skip commit if no files changed.
- Vault dir resolution: `VAULT_DIR="${BAKER_VAULT_PATH:-$HOME/baker-vault}"`.
- Dry-run mode: if `--dry-run` passed, fetch to `/tmp/` instead of vault + skip git ops. Print summary table.
- Exit 0 even if 1-3 feeds fail (degraded but operable). Exit 1 only if 4/4 fail OR git push hard-fails.

### 2. launchd plist — baker-vault `scripts/com.baker.edge-scout-prefetch.plist`

Template plist for `launchctl bootstrap`. Cadence: Saturday 17:00 UTC (gives 1h headroom before Sun 18:00 UTC cron). Use `StartCalendarInterval` with `Weekday=6` (Saturday in launchd's 0=Sun convention) + `Hour=17` + `Minute=0`. **Use UTC explicitly** — Mac Mini timezone may not be UTC.

Plist fields:
- `Label: com.baker.edge-scout-prefetch`
- `ProgramArguments: [/Users/dimitry/Library/Application Support/baker/edge-scout-prefetch.sh]`
- `StartCalendarInterval` as above (and `EnvironmentVariables: {TZ: "UTC"}`)
- `WorkingDirectory: /Users/dimitry/baker-vault`
- `StandardOutPath: /Users/dimitry/Library/Logs/baker-edge-scout-prefetch.log`
- `StandardErrorPath: /Users/dimitry/Library/Logs/baker-edge-scout-prefetch.err`
- `RunAtLoad: false` (avoid double-fire on boot)

Reason for `~/Library/Application Support/baker/` install path, NOT `~/Desktop`: macOS TCC blocks launchd execution from `~/Desktop`. See lesson `feedback_macos_tcc_launchd_blocks_desktop.md`.

### 3. Cache dir init — baker-vault `_ops/edge-scout-cache/`

- `README.md` — 1-pager: purpose, schema, "do not edit by hand", "expected refresh cadence: weekly Saturday 17:00 UTC by Mac Mini launchd", anchor link to this brief.
- `.gitignore` empty — XMLs ARE committed (cron needs them in the clone).
- Optional initial seed: run the script once locally in B1's working dir to land the first set of 4 XMLs (gives the cron something to read on first wire-up).

### 4. SKILL.md edit — `~/.claude/skills/aidennis-edge-scout/SKILL.md`

Section to update: "Wiring (cron + invocation)" → "Invocation prompt template" block (current lines 105-109). The cron prompt no longer uses WebFetch. Replace the WebFetch language with:

```
Run the aidennis-edge-scout skill. Read the 4 cached feed XMLs from `_ops/edge-scout-cache/` (simonwillison.xml, hamel.xml, eugeneyan.xml, huggingface.xml — pre-fetched by Mac Mini launchd Saturday 17:00 UTC; freshness in `_ops/edge-scout-cache/_status.json`). Apply the editorial filter (skip consumer hype + Anthropic-scope items; keep eval / agent-arch / SRE / security-engineering / production-LLM-tradeoff items). Cross-check against the last 4 weekly digests in `~/baker-vault/wiki/_ai-it/aid-t/live-edge/` to skip repeats. Write 5-10 ranked items + watching list + skipped count + trends to `~/baker-vault/wiki/_ai-it/aid-t/live-edge/YYYY-WW-weekly.md` per the template in SKILL.md. Skip any source whose `_status.json` entry shows `status=fail` with `last_success` older than 14 days — log it in the digest's frontmatter `sources_failed` field.
```

Also update the existing "Sources — 4 feeds at v1" section: add a line at the end noting "(now read from `_ops/edge-scout-cache/` — pre-fetched by Mac Mini Saturday 17:00 UTC; HTTP fetch path retired after 2026-05-17 cron-env 403 regression — see `_ops/agents/aihead1/handover-archive/2026-05/<this-handover>.md`)".

Also update the "Guardrails" section's "WebFetch failures" bullet to refer to cache-staleness rather than live fetch failures.

### 5. Install on Mac Mini

After PR merges:
- `ssh macmini`
- `mkdir -p ~/Library/Application\ Support/baker ~/Library/Logs`
- Copy `scripts/edge-scout-prefetch.sh` from vault clone → `~/Library/Application Support/baker/edge-scout-prefetch.sh`. `chmod +x`.
- Copy `scripts/com.baker.edge-scout-prefetch.plist` from vault clone → `~/Library/LaunchAgents/com.baker.edge-scout-prefetch.plist`.
- `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.baker.edge-scout-prefetch.plist`.
- Verify: `launchctl print gui/$(id -u)/com.baker.edge-scout-prefetch | head -30`.
- Force-fire once: `launchctl kickstart -k gui/$(id -u)/com.baker.edge-scout-prefetch`. Verify 4 XMLs land in vault on origin/main + log shows success.

### 6. Out of scope

- RemoteTrigger update — AH1 handles after b1 ships + Mac Mini verifies (sequencing: don't flip the cron prompt until Mac Mini has cached at least one full set).
- Schema changes to the weekly digest output.
- Editorial filter changes (AID owns).

## Reporting

Bus-post `lead` on PR open with:
- PR # + commit shas
- Local fire-once result (4 XMLs + status.json)
- Mac Mini install + kickstart verification (log paths + first XML commit sha in vault)

On any blocker (e.g. Mac Mini SSH down, plist won't load): bus `lead` with diagnosis — do not improvise plist tweaks beyond what the lesson file documents.

## Anchor

- AID dispatch `~/baker-vault/_01_INBOX_FROM_CLAUDE/2026-05-21-AID-edge-scout-cron-egress-fix.md`.
- Director ratification 2026-05-21 ~00:50 UTC: "go" on architecture (vault-cache via Mac Mini, decoupled from diagnostic which failed to fire).
- Diagnostic context: `RemoteTrigger action=run` against `trig_01BjL6NYoTFWwVMLs1mGXFTT` returned HTTP 200 twice but `last_fired_at` never advanced — manual fires aren't taking. Architecture chosen does not depend on the diagnostic outcome.
- Lesson: `feedback_macos_tcc_launchd_blocks_desktop.md` (deploy launchd scripts to `~/Library/Application Support/`, never `~/Desktop`).
- Cron trigger config (read-only reference): `RemoteTrigger(action=get, trigger_id=trig_01BjL6NYoTFWwVMLs1mGXFTT)`.
