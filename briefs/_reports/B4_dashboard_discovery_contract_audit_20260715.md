# B4 audit — DASHBOARD_DISCOVERY_CONTRACT_AUDIT_1

- **Brief:** briefs/_tasks/DASHBOARD_DISCOVERY_CONTRACT_AUDIT_1.md (lead dispatch #11705; origin Director correction via codex #11702)
- **Class:** discovery/audit (docs). Harness-V2 N/A. Read-only + at most ONE doc/registry PR.
- **Date:** 2026-07-15
- **Ship topic:** `baker-os-v2/arrivals-dashboard-discovery` (ref #11702)

## Bottom line
Three dashboard surface classes exist with **no single discovery registry** telling a desk
which surface is authoritative and how to update it (gap confirmed by grep — the expected
finding). **No committed doc mis-attributes the arrivals board to MOVIE** — the #11702
correction was to the live/mental record, not a checked-in file. The real recurrence vector
is a **class-confusion mislabel** in the flight-dashboard-build skill, not a name error.
Every remediation target is vault-side → **PR-path decision flagged to lead** (below).

## AC1 — Inventory (every dashboard-class artifact, with class + owner + update path)

Classes: **(a)** design reference (frozen, never live) · **(b)** live deployed URL (prod,
repo-deploy) · **(c)** per-matter static desk file (vault-committed, desk-owned).

| Artifact | Path | Class | Owner | Update path |
|---|---|---|---|---|
| Canonical template Page v5 | `~/baker-vault/wiki/_templates/flight-dashboard-canonical-v5.html` | a | Director + codex (pattern gate) | ratified once; never edit after lock (design-v2 §14) |
| Canonical template v4 (history) | `~/baker-vault/wiki/_templates/flight-dashboard-canonical-v4.html` | a | — | frozen (superseded by v5) |
| Arrivals design reference | `~/baker-vault/_ops/build/baker-os-v2/05_outputs/flight-dashboards/arrivals-board-v6.html` (8 Jul, 8466 B) | a | **AO desk** (supplied) | frozen; visual register for the live `/arrivals` surface |
| Departure-board mockups v1–v5 | `.../flight-dashboards/departure-board-v*.html` | a | design | frozen mockups |
| BB-AUK-001 reference demo | `.../flight-dashboards/BB-AUK-001/dashboard-v1-pattern-d.html` (+v2-pattern-e, 30+ support files) | a/c dual | AO desk | vault-commit during flight (content moves — **not a copy source**) |
| Per-flight desk dashboards | `.../flight-dashboards/{MO-VIE-001,AO-OSK-001,FA-ACA-001,BRI-GRP-001,HAG-RG7-001}/dashboard-v*.html` | c | owning desk | vault-commit by desk/lead during flight |
| `/arrivals` (Director flight board) | `outputs/dashboard.py:8603` `@app.get("/arrivals")` → `arrivals_board.render_board_html` | b | b-code builders + lead merge | repo → PR → merge → Render deploy |
| `/cockpit/{project_code}` | `outputs/dashboard.py:8553` → `orchestrator.cockpit_serve.fetch_cockpit_html` | b | builders + lead | repo deploy (serves frozen vault cockpit html) |
| `POST /api/flight-board/{code}` | `outputs/dashboard.py:8584` (authed) → `arrivals_board.upsert_board_state` | b | builders | repo deploy |
| `GET /api/arrivals.json` | `outputs/dashboard.py:8618` | b | builders | repo deploy |

Verified: arrivals-board-v6.html present; dashboard.py routes present at the lines above.

## AC2 — Canonical registry: **ABSENT (gap declared)**
Grep evidence (vault + repo, `*.md`): no dashboard-surface/discovery registry exists.
`grep -rIl "dashboard.*registry|surface.*authoritative|dashboard-discovery|discovery.contract"`
returns only unrelated word co-occurrences (cockpit-sidebar brief, autowake brief, HR directory,
a MOVIE decision log) — none maps dashboard surfaces to authoritative update paths.
What partially covers it, none fleet-wide or class-aware:
- `flight-dashboard-build` SKILL.md — a *build workflow*, not a discovery contract; no class taxonomy.
- `design-v2.md §14` (Pattern E lock) — addresses designers, not operators; no update-path-by-class.
- per-matter `living-documents-register.md` — rule-9 staleness only; not a surface map.

**Proposed location/format:** `~/baker-vault/wiki/_ops/dashboard-discovery-contract.md` — a
single class×(example/path/update-path/owner) table + a "which surface is this?" lookup by path
pattern. Draft content in AC4 below, ready to land.

## AC3 — AO/pilot guidance audit (exact file+line)
**No committed doc mis-attributes the arrivals board to MOVIE.** Grep of the named guidance
files (`_ops/agents/ao-desk/`, `_ops/agents/movie-desk/`, `_ops/skills/flight-dashboard-build/`,
`wiki/design/design-v2.md`) returned **zero** MOVIE-attribution lines for `arrivals-board-v6` /
the arrivals board. The #11702 correction therefore targets the *live record*, not a checked-in
file — so there is no line to "fix," only a positive anchor to *add* (prevent recurrence).

Real gaps found (class-distinction language, the actual misdirection risk):
1. `~/baker-vault/_ops/skills/flight-dashboard-build/SKILL.md:34` — binding table row labels the
   BB-AUK-001 vault file **"Live canonical instance"**. It is NOT live — it is a vault
   design-reference demo whose content moves. Calling it "live" is exactly what lets a pilot edit
   a vault file expecting the production URL to change. **Relabel → "Reference demo (vault, not a live URL)".**
2. `~/baker-vault/_ops/skills/flight-dashboard-build/SKILL.md:33-37` — binding table has no
   "surface class" column and no pointer to the (missing) discovery contract.
3. `~/baker-vault/wiki/design/design-v2.md §14` (canonical-lock note) — distinguishes template vs
   "live BB-AUK-001 file" for *designers*, but never names the production surfaces (`/arrivals`,
   `/cockpit/{code}`) or their repo-deploy update path for *operators*.

## AC4 — Remediation
**Authoritative route per class:**
- (a) Design reference → look up in the discovery contract; **never edit after ratification**
  (design change = Director/codex Tier-B, design-v2 §14).
- (b) Live deployed URL → edit `outputs/dashboard.py` / `outputs/templates/` / `orchestrator/*.py`
  → PR → lead merge → Render auto-deploy. **No desk unilateral edits.**
- (c) Per-matter desk file → desk edits the vault file → lead/desk vault-commit → bound by
  content-contract v2.4.

**Proposed ONE doc/registry PR (all vault-side):**
1. NEW `~/baker-vault/wiki/_ops/dashboard-discovery-contract.md` — the registry (class table +
   path-pattern lookup + AO-attribution anchor for arrivals-board-v6). Draft ready (appendix).
2. `flight-dashboard-build/SKILL.md:34` — relabel "Live canonical instance" → "Reference demo
   (vault, not live)"; add a surface-class note + link to the discovery contract.
3. `design-v2.md §14` — one inserted clarification: frozen template + per-flight vault files are
   design references; production is `/arrivals` + `/cockpit/{code}` via repo deploy; see contract.

**Structural (proposal only, separate brief — not built):** a pre-commit lexical guard warning
when a new flight is scaffolded by copying the BB-AUK-001 demo instead of the frozen template.

## AC5 — Ship
Posted to lead on the bus, topic `baker-os-v2/arrivals-dashboard-discovery`, referencing #11702.

## DECISION FOR LEAD (vault-commit governance)
Every remediation target lives in `~/baker-vault` (separate repo; CHANDA Inv 9 = Director/Mac-Mini
commit path; b4's standing scope is repo implementation, not vault governance docs). The brief
authorises "ONE small doc/registry PR (branch, never main)" but does not resolve whether b4 opens
the **vault** PR or it routes through the vault-commit path. I have **not** written to the vault.
Options: (A) b4 opens a vault-repo branch/PR with the three edits above; (B) route the drafted doc
+ two edits through the Director/Mac-Mini vault-commit path; (C) land the discovery contract
repo-side instead (e.g. `.claude/docs/`) if a repo home is preferred. Awaiting lead's pick.
