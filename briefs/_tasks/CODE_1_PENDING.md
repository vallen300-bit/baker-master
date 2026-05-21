---
status: PENDING
brief: briefs/BRIEF_AID_EDGE_SCOUT_VAULT_CACHE_1.md
brief_id: AID_EDGE_SCOUT_VAULT_CACHE_1
target_repo: baker-vault
matter_slug: baker-internal
dispatched_at: 2026-05-21T00:55:00Z
dispatched_by: lead
target: b1
working_branch: b1/aid-edge-scout-vault-cache-1
reply_to: lead
deadline: 2026-05-23T12:00:00Z
---

# CODE_1_PENDING — AID_EDGE_SCOUT_VAULT_CACHE_1

**Brief:** `briefs/BRIEF_AID_EDGE_SCOUT_VAULT_CACHE_1.md` (in baker-master `196bc01`).
**Working branch:** `b1/aid-edge-scout-vault-cache-1` on baker-vault.
**Deadline:** Sat 2026-05-23 ~12:00 UTC (5h buffer before Mac Mini's first launchd fire at 17:00 UTC).
**Reply target:** bus-post `lead` on PR open.

## Summary (full body in brief)

Pre-fetch the 4 edge-scout RSS/atom feeds via a Saturday Mac Mini launchd job;
cron reads cached XMLs from `_ops/edge-scout-cache/` instead of WebFetch.

Five deliverables:

1. `scripts/edge-scout-prefetch.sh` — bash script with `--dry-run` mode + status JSON.
2. `scripts/com.baker.edge-scout-prefetch.plist` — launchd template, Saturday 17:00 UTC, TZ=UTC.
3. `_ops/edge-scout-cache/{README.md, simonwillison.xml, hamel.xml, eugeneyan.xml, huggingface.xml, _status.json}` — initial seed via fire-once.
4. `~/.claude/skills/aidennis-edge-scout/SKILL.md` — invocation prompt + sources section + guardrails section updated to reflect cache-read instead of WebFetch.
5. Mac Mini install (via `ssh macmini`): plist + script + bootstrap + force-fire verify.

## Ship gate

- Local fire-once: 4 XMLs land in `_ops/edge-scout-cache/`, `_status.json` written correctly, commit + push succeeds.
- `shellcheck` clean on the bash script.
- Mac Mini `launchctl kickstart` produces 4 XMLs in vault on origin/main + log shows success + no TCC error.

## Reporting

Bus-post `lead` on PR open. Then bus `lead` again post-Mac-Mini-install with the first launchd-fired commit sha + log paths. AH1 handles RemoteTrigger update post-verify.
