---
brief_id: AID_EDGE_SCOUT_VAULT_CACHE_1
author: b1
report_date: 2026-05-21
pr: vallen300-bit/baker-vault#102
branch: b1/aid-edge-scout-vault-cache-1
status: shipped (PR open; Mac Mini install pending merge)
---

# B1 ship report — AID_EDGE_SCOUT_VAULT_CACHE_1

## What shipped (PR #102 on baker-vault)

- `scripts/edge-scout-prefetch.sh` — fetches 4 feeds (Simon Willison atom, Hamel index.xml, Eugene Yan rss, HuggingFace blog feed.xml) via curl with shared UA `BakerEdgeScoutPrefetch/1.0 (+https://brisengroup.com)`, 60s max time. Per-feed failure retains prior XML in place. Writes `_status.json`. `git fetch + reset --hard origin/main` before each run for clean state. `--dry-run` mode fetches to `/tmp/` and skips git ops. shellcheck clean.
- `scripts/com.baker.edge-scout-prefetch.plist` — launchd template. `StartCalendarInterval` Saturday (Weekday=6) 17:00 UTC, `EnvironmentVariables.TZ=UTC`, `RunAtLoad=false`. Install path `/Users/dimitry/Library/Application Support/baker/edge-scout-prefetch.sh` (NOT `~/Desktop` per TCC lesson). Logs to `~/Library/Logs/baker-edge-scout-prefetch.{log,err}`.
- `_ops/edge-scout-cache/README.md` — schema (`_status.json` shape), refresh cadence, "do not edit by hand", anchor link.
- `_ops/edge-scout-cache/{simonwillison,hamel,eugeneyan,huggingface}.xml` — initial seed (4/4 ok @ 2026-05-21T06:17:11Z, total ~970 KB).
- `_ops/edge-scout-cache/_status.json` — initial status block, all 4 sources `status=ok`.

## What also shipped (outside repo — companion edit)

- `~/.claude/skills/aidennis-edge-scout/SKILL.md`:
  - "Sources — 4 feeds at v1" gets a callout note: feeds now read from `_ops/edge-scout-cache/`; HTTP fetch retired after the 2026-05-17 cron-env 403 regression.
  - Invocation prompt template: `WebFetch each feed URL` → `Read the 4 cached feed XMLs from _ops/edge-scout-cache/ ... Skip any source whose _status.json entry shows status=fail with last_success older than 14 days`.
  - Guardrails "WebFetch failures" bullet → "Cache staleness" bullet (14-day window for skipping a source; 2+ stale-failed = dispatch issue to AH1).

## Verification

- `shellcheck` on `scripts/edge-scout-prefetch.sh` — clean (no findings).
- `bash -n scripts/edge-scout-prefetch.sh` — clean.
- `plutil -lint scripts/com.baker.edge-scout-prefetch.plist` — OK.
- `./scripts/edge-scout-prefetch.sh --dry-run` — 4/4 feeds fetched, sizes 94843 / 565406 / 104015 / 229915 bytes; `_status.json` well-formed; no errors.
- Initial seed in repo matches dry-run output (same 4 XMLs + status.json).

## Open items / handoff

1. **Mac Mini install** — pending PR merge. Plan (per brief §5):
   - `ssh macmini`
   - `mkdir -p ~/Library/Application\ Support/baker ~/Library/Logs`
   - `cp ~/baker-vault/scripts/edge-scout-prefetch.sh ~/Library/Application\ Support/baker/` (`chmod +x` already in repo)
   - `cp ~/baker-vault/scripts/com.baker.edge-scout-prefetch.plist ~/Library/LaunchAgents/`
   - `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.baker.edge-scout-prefetch.plist`
   - Verify: `launchctl print gui/$(id -u)/com.baker.edge-scout-prefetch | head -30`
   - Force-fire: `launchctl kickstart -k gui/$(id -u)/com.baker.edge-scout-prefetch`
   - Confirm 4 XMLs land + commit appears on `origin/main` + log shows success / no TCC error
   - Bus-post `lead` with the launchd-fired commit sha + log paths.
2. **RemoteTrigger config update** — AH1 owns (per brief §6).

## Anchors

- Brief: `briefs/BRIEF_AID_EDGE_SCOUT_VAULT_CACHE_1.md` (baker-master `e7f7d6b`).
- Dispatch: `baker-vault:_01_INBOX_FROM_CLAUDE/2026-05-21-AID-edge-scout-cron-egress-fix.md`.
- PR: https://github.com/vallen300-bit/baker-vault/pull/102
- Branch: `b1/aid-edge-scout-vault-cache-1` @ `b87f98a`.
- TCC lesson: `feedback_macos_tcc_launchd_blocks_desktop.md`.
