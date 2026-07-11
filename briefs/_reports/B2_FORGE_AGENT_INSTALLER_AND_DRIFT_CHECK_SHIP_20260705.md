# B2 SHIP — forge-agent installer + drift-check (WAKE_HOST_AFFINITY_1 follow-up)

- **PR:** #467 — `b2/forge-agent-installer-and-drift-check` → main
- **Commit:** ec6d52ee
- **Dispatch:** lead bus #5624 (accept) + #5626 (ruling/GO) on thread wake-host-affinity-joint
- **Date:** 2026-07-05
- **Gate:** codex G3 → lead merge (no deploy — host tooling)

## Done rubric
- **Root cause fixed:** forge-agent scripts now have a repo source-of-truth + an idempotent installer, so a host (the Mac Mini) can no longer sit un-provisioned and silently blind the wake handler's `isAliasLive` guard.
- **Repeatable:** `bash scripts/install_forge_agent.sh` deploys the 4 forge scripts + 2 bus hooks, adds FORGE_KEY/LAB_URL to `~/.zshrc` (env or 1Password, never hardcoded), and wires forge+bus hooks into `~/.claude/settings.json` (backup + atomic merge, existing keys preserved).
- **Drift-detectable:** `--check` is non-mutating and exits non-zero on any drift (script shasum mismatch / missing env / missing-or-wrong wiring / Director-facing hook on a headless host). Cron example in the process doc.
- **Host-class distinction codified** (per your #5624): forge+bus on both classes; Director-facing enforcement hooks laptop-only, never on a headless spawn host.

## Files
- NEW `scripts/forge-agent/{session-start-hook,heartbeat-ticker,turn-start-hook,turn-stop-hook}.sh`
- NEW `scripts/install_forge_agent.sh`
- NEW `tests/test_install_forge_agent.sh`
- MOD `_ops/processes/brisen-lab-session-start-hook.md`

## Tests (literal)
```
$ bash tests/test_install_forge_agent.sh
ok   - install -> check clean (headless)
ok   - 6 scripts deployed + executable
ok   - active/ + sessions.json seeded
ok   - tamper -> drift exit non-zero
ok   - missing env -> drift
ok   - idempotent re-install (no duplicate hook groups)
ok   - preserves pre-existing settings keys
ok   - Director hook on headless -> drift
ok   - Director hook under laptop class -> clean
ok   - missing wiring -> drift
----
PASS=10 FAIL=0
```
Installer `bash -n` clean. Dry-run + drift exercised against a throwaway HOME (no network, real ~/.claude untouched).

## Deliberately out of scope (lead ruling #5626)
Idle-keepalive / turn-gate idle-staleness — needs a daemon-side liveness/working split (`forge_sessions.last_alive_at`, `slug_live` repointed, amber untouched, low-freq idle keepalive to `last_alive_at` only) in the **brisen-lab** repo. Separate PR, after this lands. Residual is narrow (cross-host idle non-desk aliases) — defense-in-depth, not acute.

## Prior in this arc (host provisioning, already done under lead authority)
Mini provisioned live over SSH (#5620 GO → #5621 verify): forge-agent installed, FORGE_KEY/LAB_URL added, SessionStart/turn + bus hooks wired; ticker + isAliasLive proven working; live desk pid 12170 untouched. This PR generalizes that into the repeatable installer.
