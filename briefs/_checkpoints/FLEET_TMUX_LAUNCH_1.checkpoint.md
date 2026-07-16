# Checkpoint — FLEET_TMUX_LAUNCH_1 (Cockpit BRIEF A)

- attempt: 1
- seat: B1
- branch: b1/fleet-tmux-launch (pushed) · PR #582 (OPEN, awaiting codex cross-vendor review + lead merge)
- brief: briefs/_tasks/FLEET_TMUX_LAUNCH_1.md @643e1bf2 · scope v1.3.2 @46d8134f
- dispatcher: lead (#12029/#12051)

## What's done
- All 6 deliverables built + committed + pushed on b1/fleet-tmux-launch:
  - generate_cockpit_manifest.py (join v1.3.2 #12093: markers-only, reconcile-to-exactly-one, provenance) — 26/26 --strict exit 0
  - fleet_terminals.sh (up|open|status + ledger), cockpit_migrate.sh (Phase-1 live; Phase-2 built-not-executed, guard exit 3)
  - install_cockpit_ttyd.sh + launchd/com.baker.cockpit-ttyd.plist.template (now with -b /term/<slug>/ base path, commit aa8c4c0c)
  - cockpit_rollback.sh (Lesson 76)
- B3 sandbox pilot LIVE + green: tmux b3 UP, ttyd com.baker.cockpit-ttyd-b3 on 127.0.0.1:7608, ledger b3=migrated.
- Live ACs pass: AC-1/AC-M1 (dup guard), AC-3 (kill ttyd→tmux survives→KeepAlive reattach), AC-5/AC-M3 (lsof 127.0.0.1-only), AC-M2 (B3 e2e).
- N2 base-path defect (deputy-codex C3) FIXED: /term/b3/ = 200 direct AND through controller :7800.
- Ship report: briefs/_reports/B1_FLEET_TMUX_LAUNCH_1_20260717.md. Coordinated b3 cycle mechanism with deputy-codex.

## What's left
- Await codex cross-vendor review verdict on PR #582 → address any request-changes (new commit, never amend).
- Await deputy-codex C3 rerun verdict (C1/C2/C4/C5 already green) — should pass now base path is live.
- After lead merge + pilot: post POST_DEPLOY_AC_VERDICT v1.
- LOCKED on lead GO (do NOT start without it): Brisen Desk pilot, then Phase-2 coordinated global cutover.

## Key paths / commits
- Commits: 851a677e/f8b5a1f8 (manifest) c376f6d0 (fleet) e2f08018 (ttyd) 1d642c43 (migrate+rollback) b30e1d3c (join v1.3.2) aa8c4c0c (base-path fix) + ship report.
- Deploy dir: ~/Library/Application Support/baker/cockpit/ (launch_manifest.json, fleet_terminals.sh, credentials[controller-owned], migration_ledger.json).

## Next concrete step
Poll bus for: codex verdict on #582, deputy-codex C3 rerun, or lead merge/GO. No autonomous Brisen-Desk/Phase-2 work. Keep b3 sandbox UP for deputy-codex's probe.
