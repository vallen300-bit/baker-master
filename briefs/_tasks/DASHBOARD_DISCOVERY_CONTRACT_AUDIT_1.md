# BRIEF: DASHBOARD_DISCOVERY_CONTRACT_AUDIT_1

dispatched_by: lead
worker: b4
priority: high
Harness-V2: N/A — audit/docs discovery brief, no production code; any remediation PR is doc/registry-only (structural changes return as proposal, separately briefed)
origin: Director correction relayed via codex (bus #11702, thread af95145c); lead dispatch

## Context

Task class: discovery/audit (docs). The fleet has three distinct dashboard surface classes
(design references, live deployed pages, per-matter static desk files) with no single
discovery contract telling a desk/pilot which is authoritative and how each is updated.
A live Director correction (AO vs MOVIE attribution on the arrivals board) exposed the gap.
Binding references: `flight-dashboard-build` skill (canonical v5 template + content-contract
v2.4 + living-documents register), `_ops/build/baker-os-v2/05_outputs/flight-dashboards/`,
`outputs/dashboard.py` (production surfaces).

## Problem

Director correction on the arrivals-dashboard record: the desk that supplied the frozen
source file `arrivals-board-v6.html` was **AO, not MOVIE**. That file is the **approved
design reference** — while the pinned "Arrivals Board" app actually opens the **production
`/arrivals` page**, and the **deployed template + live flight data** are a third, separate
surface. Nothing in the fleet guidance distinguishes these three, so any desk or pilot can
be misdirected to the wrong surface and the wrong update path (e.g. editing a frozen design
file expecting production to change, or restyling production against a stale reference).

## Task — fleet-wide dashboard discovery/update contract audit

1. **Inventory every dashboard-class artifact** the fleet references. Known starting points:
   - `_ops/build/baker-os-v2/05_outputs/flight-dashboards/` (per-flight dashboard-v1.html, vault)
   - frozen canonical templates (`flight-dashboard-canonical-v5.html`, content-contract v2.4, living-documents register — see `flight-dashboard-build` skill)
   - production pages served by baker-master (`/arrivals`, cockpit surfaces in `outputs/dashboard.py`)
   - per-matter static desk files (AO arrivals-board-v6.html pattern)
2. **Classify each into the three classes:** (a) design reference (frozen, never live),
   (b) live deployed URL (production, updated via repo deploy), (c) per-matter static desk
   file (desk-owned, vault-committed). Flag anything ambiguous or dual-role.
3. **Identify the canonical registry/mapping** — where a desk/pilot is SUPPOSED to look up
   "which surface is authoritative for dashboard X and how do I update it". If no single
   registry exists, say so loudly (that is the expected finding).
4. **Audit AO + pilot guidance** (AO desk orientation/operating files, flight-dashboard-build
   skill, living-documents register) for the MOVIE/AO mis-attribution and for missing
   class-distinction language. List exact files + lines needing correction.
5. **Return remediation:** (i) the authoritative route for each dashboard class (lookup →
   edit → deploy/commit path), (ii) proposed registry location + format if none exists,
   (iii) the specific doc corrections (AO attribution fix included). Small doc/registry
   fixes: open ONE PR. Anything structural: proposal only, no build.

## Files Modified

- None expected beyond ONE optional doc/registry PR (new registry doc + AO/pilot guidance
  attribution corrections). List every touched file in the ship report. No code, no
  templates, no per-flight dashboard content.

## Verification

- Every inventory row carries a checkable path or URL (vault path, repo path, or live URL —
  spot-verify live URLs return 200).
- AO attribution finding cross-checked against the actual frozen file
  (`arrivals-board-v6.html` provenance) — no attribution claim without a source anchor.
- If a registry gap is declared: grep evidence that no existing registry covers it
  (living-documents register + flight-dashboard-build skill + baker-os-v2 outputs checked).

## Quality Checkpoints / Acceptance criteria

- [ ] AC1: Inventory table — every dashboard artifact found, with class (a/b/c) + owner + update path.
- [ ] AC2: Canonical registry identified OR gap declared with proposed location/format.
- [ ] AC3: AO/pilot guidance mis-attribution audit — exact file+line list.
- [ ] AC4: Remediation — authoritative route per class + doc-fix PR (if small) or proposal.
- [ ] AC5: Ship report to lead on bus, topic `baker-os-v2/arrivals-dashboard-discovery`, referencing #11702.

## Gate plan

b4 audit → ship report to lead → lead line-read → if PR opened: codex cross-vendor gate → lead merge.
No production code changes in scope; no deploy. POST_DEPLOY_AC: N/A (audit/docs).

## Constraints

- Read-only across vault + repo except the one small doc/registry PR (branch, never direct to main).
- Do not touch the frozen canonical template or any per-flight dashboard content.
- Surface conflicts between sources — do not average them (Mnilax rule).
