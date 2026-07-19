---
brief_id: COCKPIT_IN_LAB_BRIDGE_1
attempt: 1
branch: b1/cockpit-in-lab-bridge-1 (both repos: baker-master + brisen-lab)
dispatched_by: lead (bus #12566)
report_topic: gates/cockpit-in-lab-bridge-1
status: CLOSED — LIVE (hardened). Merged both repos (baker #596 + lab #153, 07:22Z), flipped LIVE 08:14Z (Director /goal, 7/7 AC #12690), NEVER rolled back. HARDENING_2 deployed under it evening (baker #605 + lab #158, codex PASS #12992). Lead's 18:07Z agent bootout (#12962) was a MISDIAGNOSIS — tokenless /cockpit/ 404 is the fail-closed token gate's disguise, NOT flag-off; cowork-ah1 restored the agent 19:2xZ (#13013). Trap documented in the runbook STATUS block. Delta codex scope-confirm PASS #12947.
gate: /security-review clean; codex PASS-WITH-NOTE both tips; delta scope-confirm PASS #12947; lab #155 fail-closed token gate merged 15:00Z on top
---

# COCKPIT_IN_LAB_BRIDGE_1 — checkpoint (post-merge)

Brief: `briefs/_tasks/COCKPIT_IN_LAB_BRIDGE_1.md` @c1828591. Reverse bridge: laptop
outbound WS -> Lab proxies /cockpit/* + terminals down to 127.0.0.1:7800.

## Done (merged, both repos)

- baker PR #596 + lab PR #153 merged 2026-07-18 07:22Z; delta commits 16a9821e +
  08a7c077 in baker main, codex scope-confirm PASS #12947.
- Lab #155 (fail-closed token gate — deny all when token unset) merged 15:00Z.
- Blocker #2 resolved via Option A (`window.__COCKPIT_BASE__` inject); close-race
  ConnectionClosedOK fixed + regression test (baker tests 28, agent suite 13).
- Build-not-flip held: COCKPIT_EMBED_ENABLED default OFF; installer staged NOT
  loaded; no secret in plist; /security-review clean.

## Open / next concrete step

1. **Director-GO morning flip** — checklist in `.claude/how-to/cockpit-cloud-access.md`:
   kill switches FIRST (`COCKPIT_EMBED_ENABLED` unset + `launchctl bootout
   com.baker.cockpit-bridge`), then flip. COCKPIT_ACCESS_TOKEN mandatory before
   flip (auth ruling, bus #12569).
2. Recommend flipping only after b1 COCKPIT_BRIDGE_HARDENING_2 (kill-switch
   socket revoke) merges — in build as of 2026-07-18 evening.

## Key paths

- Lab: `brisen-lab/cockpit_bridge.py`, routes in `brisen-lab/app.py` (grep COCKPIT_IN_LAB_BRIDGE_1).
- Agent: `scripts/cockpit_bridge_agent.py`, `scripts/install_cockpit_bridge.sh`, `scripts/launchd/com.baker.cockpit-bridge.plist`.
- Probe: `scripts/cockpit_bridge_loopback_probe.py`. Report: `briefs/_reports/B1_cockpit_in_lab_bridge_1_20260718.md`.
