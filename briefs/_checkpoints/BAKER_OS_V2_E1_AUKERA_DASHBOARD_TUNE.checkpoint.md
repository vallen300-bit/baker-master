---
brief_id: BAKER_OS_V2_E1_AUKERA_DASHBOARD_TUNE
worker: b2
attempt: 1
repo: baker-vault (NOT baker-master) — artifact is vault-side
branch: b2/e1-aukera-dashboard-tune (in an ISOLATED clone; recreate — see next_action)
base_commit: baker-vault origin/main @f56402b
last_commit: none (zero edits made this session — pure discovery + setup)
pr: none
mailbox: bus-dispatch #5814 (E1 rerouted to b2 from cowork-ah1); inputs #5824 #5846 #5852
gates_cleared: []
gates_pending: [codex-terminal-UI-critique, lead-review, Director-visual-ratify]
tests_state: "n/a — static HTML artifact, no test suite"
next_action: >
  Re-clone the vault isolated (git clone --depth 1 --branch main https://github.com/vallen300-bit/baker-vault.git /tmp/bm-b2-e1-vault; git checkout -b b2/e1-aukera-dashboard-tune) then edit dashboard-v1-pattern-d.html — apply BB desk finding 2 FIRST (loan-cost tile).
done_log:
  - Full E1 orientation done; all inputs located + read.
  - Mini P1 (#5781) diagnosed + PARKED by Director; stood down (do NOT touch build.sh signing PR).
  - Branch-lock incident recovered (#5857): shared ~/baker-vault restored to main @f56402b, stray branch deleted, E1 moved to isolated clone. Confirmed to lead #5859.
open_questions:
  - none blocking; finding-2 loan-cost content is LOCKED by BB desk (render verbatim, do not re-derive).
bus_thread: baker-os-v2/wave0-e1-template-lane-b2; baker-os-v2/wave0-e1-aukera-dashboard-tune
no_secrets: true
written_at: 2026-07-07T00:00:00Z
trigger: manual (Director 50%-context-refresh rule #5917)
---

## E1 work-list (from BB desk memo E1-content-pass-findings-bbdesk-20260706.md: SHOWN 9 / MISSING 6 / NOISE 6)

Target file (vault): `_ops/build/baker-os-v2/05_outputs/flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html` (756 lines).
Then flow structural/rule changes into: `wiki/_templates/flight-dashboard-canonical-v5.html` + skill `_ops/skills/flight-dashboard-build/SKILL.md`.
Contract: `content-contract-v2.md` (rules 1-11). Living-docs register: `wiki/matters/lilienmatt/living-documents-register.md`.

**Do FIRST — HIGH (decision-integrity, rule 7 / Lesson #78):**
1. Loan-cost tile — RENDER VERBATIM from `decide-now-loan-cost-tile-CORRECTED-bbdesk-20260706.md` (commit 7055a13). ≈1.66M is UPFRONT ONLY (reserve 1,479,416 + structuring 184,650); all-in = +coupon(blank)+1.116x MOIC make-whole+40,350 structuring re-cut = OPEN; old 2.8M WITHDRAWN/STALE. Mislabels to kill: line 275 "All-in loan cost" ; KPI line 201 "Loan cost"; decsub line 194; decide-now opts lines 246-247; Financials line 266.
2. Comms per-sender msg/urgent counts hand-typed vs ledger (rule 5) — lines 464-498; badge block "desk-estimated, not ledger" until wired.

**MISSING (medium):** 3=rule-9a as-of anchors on KPI tiles (lines 200-204); 4=STALE badge on LTV+collateral tiles (Colliers p29 mid-revision, rule 9c); 5=Director-facing "what changed" matter-event feed on Overview (currently only build-feed in Engine Lab); 6=section 5b research-received (b3 sweep + ESG); 7=rule-4 updated-by actor on Overview attention + KPI cards.

**NOISE (med/low):** LTV basis note on KPI tile (37% vs 33.1M secured, not 38.6M whole); gloss "2+1-year term"; Engine Lab counts "snapshot — live query in step-2" label (line 599, stale 4 Jul 22:42); countdown soften "may slip — see land register" (line 184).

**Gate after edits:** codex terminal UI critique BEFORE Director sees it → push branch from isolated clone → open vault PR → post DONE to lead with evidence. Autonomous GO (do not ask Director).
