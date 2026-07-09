# BRIEF: AO_FLIGHT_RELATIONSHIP_1 — migrate cockpit AO Dashboard into AO-OSK-001 flight page, then discard the cockpit tab

## Context

Director directive 2026-07-09 (~22:30Z, cowork-ah1 session, Director asleep — reviews in the morning): *"We may use the wiring and the information from the [cockpit] AO Dashboard for the AO-OSK-001 dashboard … in this case the AO dashboard in Baker dashboard can be discarded."*

Live investigation 2026-07-09 established what the cockpit AO tab (`/api/dashboard/ao`, nav `data-tab="ao-dashboard"`) actually is today:

**Dead or lying (verified against prod payload):**
- `view_files` — all 5 empty; `data/ao_pm/*.md` deleted from repo 2026-04-22 (`f3bbd16b`, AO_PM_EXTENSION_1 cleanup).
- comms-gap — shows `green / "Today"` **falsely**: the WA query matches `chat_id ILIKE '%oskolkov%'` but the real chat key is `491736903746@c.us` (phone-based — name can never match), and the email query selects `MAX(sent_at)` — column does not exist (`sent_emails` has `created_at`). Both fail silently → `last_contact_at=None` → default green. Real last AO WhatsApp: **2026-07-06** (verified live).
- `decisions`: 0 rows. `comms_log`: 0 rows (same dead `sent_at` column). `pending_insights`: 0.

**Alive and worth carrying:**
- `pm_state` — `pm_project_state` slug `ao_pm`, **updated 2026-07-08**, 33.7KB: `ao_psychology`, `red_flags`, `capital_calls`, `financial_summary`, `sub_matters`, `open_actions`, `decisions_log`, `rg7_equity`. This is the living relationship intelligence (maintained by the AO PM machinery; `ao_pm_lint` Sunday job just got its honest 192h threshold in CRD_2).
- `orbit_contacts` — 12 live rows from `vip_contacts`.
- `AO_INVESTMENT_TOTAL = "EUR 66.5M"` as-of 2026-06-01 (static, AO-Desk-owned, `outputs/dashboard.py` ~18319).
- The comms-gap **concept** (good wiring idea, broken implementation).

AO-OSK-001 flight page is already the Director-facing AO surface (FLIGHT_DASHBOARD_PACKET v2, desk snapshot updated 2026-07-07, flight ON TIME). This brief moves the two live assets + the fixed comms-gap wiring onto it, then discards the cockpit tab. Same doctrine as CRD_1/CRD_2: honesty + subtraction; a surface that lies (default-green gap) is worse than no surface.

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: COCKPIT_REFERENCE_DESK_2 merged first (same-file overlap in `outputs/static/index.html`; trivial rebase if reordered). Content dependency: ao-desk authors the `relationship` section (task dispatched on bus, topic `baker-os-v2/ao-flight-relationship`) — code must render gracefully if it lands first.

## Baker Agent Vault Rails

Relevant: **standing-contract** (Director-facing honesty; flight pages are the canonical CEO register), **verification-surfaces** (flight page + sentinel-health truthfulness), **skills-and-playbooks** (flight-dashboard-build governs the packet contract).
Ignored: bus-and-lanes, memory-and-lessons, loop-runner — no mechanics change.

## Harness V2

- **Task class:** production-facing UI+backend, **Tier-B**. No migrations, no env changes, no external sends.
- **Context Contract:** worker needs — (1) this brief; (2) repo at main with CRD_2 merged; (3) `orchestrator/flight_dashboard.py` + `orchestrator/flight_dashboards/AO-OSK-001.json` + the two cockpit surfaces being retired; (4) prod read for post-deploy checks (`X-Baker-Key`, Render env `BAKER_API_KEY` — never commit); (5) bus seat for the verdict. NOT needed: baker-vault wikis, Fireflies/Cortex anything, Director chat history, AO matter documents (the desk owns content — worker builds the frame only).
- **Done rubric:** every Quality Checkpoint answered pass / fail / ⏳ POST-DEPLOY / N-A + reason in the ship report. If the ao-desk `relationship` content has not landed by deploy time, checkpoint 6 is answered "renders empty-state honestly" — that is a PASS for the code; do not block the deploy on desk content.
- **Done-state class:** DEPLOYED + post-deploy AC verified + `POST_DEPLOY_AC_VERDICT` on bus (post-deploy-ac-bus-gate).
- **Gate plan:** lead reviews brief → main → dispatch b-seat → PR → codex G3 → lead merge → Render deploy → post-deploy checkpoints → verdict on bus → AH1 spot-verify. No /security-review (Tier-B; no auth-surface change — flight page keeps its existing `_mcp_verify_key` gate; the scoped-key hardening brief owns that lane).

---

## Fix 1: Honest machine comms-gap element on the flight page

### Problem
"Days since last direct AO contact" is the one machine signal the cockpit tab promised and never delivered (silent double-failure → fake green). It belongs on AO-OSK-001 as a ledger-sourced machine element (packet rule 5), computed with the verified wiring.

### Current State
- `orchestrator/flight_dashboard.py::build_flight_dashboard` (line ~225) merges desk snapshot + machine §4 ticket counts (`count_flight_tickets`); `render_dashboard_html` (line ~523) fixed section order: header → decide → money → tickets(§4 machine) → ball → risks/changed → comms → footer.
- Verified prod schema: `whatsapp_messages(chat_id text, timestamp timestamptz, sender_name text, is_director bool)`; Oskolkov chat = `491736903746@c.us`, 71 msgs, latest 2026-07-06. `sent_emails(created_at timestamptz, to_address text — NO sent_at)`.
- Snapshot JSON top-level keys (AO-OSK-001.json): contract, snapshot_mode, project_code, matter_slug, suspected_flight, desk_owner, controller, header, decide_now, money_kpis, ball_in_court, top_risks, what_changed, communications.

### Engineering Craft Gates
- Diagnose: applies — root cause of the old lie proven pre-brief (wrong chat key + dead column + silent-default-green). Regression = the new element must render "no data — wiring unverified" on query failure, never a colored status.
- Prototype: N/A — single-line machine strip, established §4 pattern.
- TDD: applies — unit-test the pure gap→tone function and the fail-path BEFORE wiring SQL (see Verification).

### Surface contract
- **Surface:** `/flight/AO-OSK-001` — Director-canonical Pattern E CEO view (flight-dashboard-build + content-contract v2.4 govern).
- **Change:** one machine line appended inside the §4 machine card (tickets zone): `LAST DIRECT AO CONTACT — <n> days (<channel>, <date>)` with tone green ≤10d / amber 11-14 / red >14 (cockpit thresholds, now honest); on any query failure or zero rows: `LAST DIRECT AO CONTACT — no data (wiring check needed)`, neutral tone, **never green by default**.
- **Config, not hardcode:** new OPTIONAL snapshot key `comms_contact`: `{"wa_chat_id": "491736903746@c.us", "email_patterns": ["ao@aelioholding.com", "%oskolkov%"], "label": "AO"}`. Absent key (BB-AUK-001) → no line, zero behavior change. Machine reads config from the desk snapshot; desk owns who counts as "direct contact". _(Pattern list corrected by lead #7671 / ao-desk #7576: the exact `ao@aelioholding.com` replaces the original broad `%aelio%`, which also matched the Aelio-entity gatekeeper's mail and recreated the blind spot this signal exists to catch.)_
- **Verify:** post-deploy page shows the line with a real date (expect gap ≈ days since 2026-07-06 unless newer contact).

### Implementation
In `orchestrator/flight_dashboard.py`:

```python
def _gap_tone(days: Optional[int]) -> str:
    """Pure: gap days -> tone class. None = unknown -> neutral (never green)."""
    if days is None:
        return "none"
    if days > 14:
        return "red"
    if days > 10:
        return "amber"
    return "green"


def last_direct_contact(comms_contact: dict) -> Optional[dict]:
    """Ledger query: most recent WA message in the configured chat OR sent email
    matching the configured patterns. Returns {'at': datetime, 'channel': str}
    or None on no-data/failure (caller renders the honest no-data line)."""
    try:
        from kbl.db import get_conn
        with get_conn() as conn:
            with conn.cursor() as cur:
                best = None
                wa_chat = (comms_contact or {}).get("wa_chat_id")
                if wa_chat:
                    cur.execute(
                        "SELECT MAX(timestamp) FROM whatsapp_messages WHERE chat_id = %s LIMIT 1",
                        (wa_chat,),
                    )
                    r = cur.fetchone()
                    if r and r[0]:
                        best = {"at": r[0], "channel": "WhatsApp"}
                pats = (comms_contact or {}).get("email_patterns") or []
                if pats:
                    cur.execute(
                        "SELECT MAX(created_at) FROM sent_emails WHERE to_address ILIKE ANY(%s) LIMIT 1",
                        (pats,),
                    )
                    r = cur.fetchone()
                    if r and r[0] and (best is None or r[0] > best["at"]):
                        best = {"at": r[0], "channel": "email"}
                return best
    except Exception:
        logger.exception("last_direct_contact failed")
        return None
```

(Verify the module's actual DB-access idiom first — if `flight_dashboard.py`/`count_flight_tickets` uses a different connection helper than `kbl.db.get_conn`, use THAT one; grep before writing. `logger` exists in the module.)

Wire into `build_flight_dashboard`: read `snapshot.get("comms_contact")`; if present, compute gap days vs `datetime.now(timezone.utc)` (guard naive datetimes like `_apply_staleness` does) and attach `data["last_contact"] = {"days": n, "channel": ..., "date": ..., "tone": _gap_tone(n)}` or `{"days": None}` on no-data. Render inside `_tickets_html` as one extra row. Add the `comms_contact` block to `AO-OSK-001.json`.

### Key Constraints
- READ-ONLY, D-23: zero writes from the flight page path.
- Fail-loud rendering; the silent-default-green pattern is the defect this brief exists to kill.
- Do not touch BB-AUK-001.json.

### Verification
- Unit (write first): `_gap_tone(None)=="none"`, `(2)=="green"`, `(12)=="amber"`, `(20)=="red"`; render with `last_contact.days=None` contains "no data"; snapshot without `comms_contact` renders §4 unchanged (BB-AUK-001 regression).
- Post-deploy: `curl -s -H "X-Baker-Key: $BAKER_API_KEY" https://baker-master.onrender.com/flight/AO-OSK-001 | grep -c "LAST DIRECT AO CONTACT"` = 1, and the rendered date matches Verification SQL below.

---

## Fix 2: Optional `relationship` desk section on the flight page

### Problem
The living relationship intelligence (pm_state `ao_psychology`, `red_flags`, comms rules; orbit roster) has no Director-facing home once the cockpit tab dies. It is desk-curated content → belongs in the desk snapshot, rendered like every other section.

### Current State
Packet v2 has no relationship section; renderer is a fixed chain. Desk snapshot is the single content source (`load_snapshot`); all desk values HTML-escaped on render.

### Engineering Craft Gates
- Diagnose: N/A — new section, not a bug.
- Prototype: N/A — same card grammar as `top_risks`/`ball_in_court`; no design uncertainty (Pattern E card, existing CSS).
- TDD: applies — renderer test with section present / absent / empty before implementation.

### Surface contract
- **Surface:** `/flight/AO-OSK-001`, Pattern E.
- **Change:** new card `RELATIONSHIP — COUNTERPARTY READ` rendered between `_risks_changed_html` and `_comms_html`. OPTIONAL section: absent/empty → card omitted entirely (BB-AUK-001 and every other flight unaffected; forward-compatible).
- **Schema (add to FLIGHT_DASHBOARD_PACKET v2 as optional):**
```json
"relationship": {
  "updated_at": "2026-07-09T...",
  "read": [ {"point": "one-line counterparty read", "receipt": "source · date"} ],
  "red_flags": [ {"flag": "...", "receipt": "..."} ],
  "orbit": [ {"name": "Constantinos", "role": "gatekeeper / Aelio", "note": "channel for written intent"} ]
}
```
- **Content authority:** ao-desk authors from pm_state (which it maintains — updated 2026-07-08) + `vip_contacts` orbit. Machine renders, never generates. Desk keeps truly sensitive material in desk docs — the CEO card carries the operational distillation only (bus task to ao-desk covers this; not the worker's job).
- **Verify:** with desk content absent, page renders with no relationship card and no errors; with content present, card renders escaped with per-section `updated_at` stamp + staleness flag (reuse `staleness_flag`).

### Implementation
- `_relationship_html(data)` following `_table_card`/`_ball_html` conventions: `read` bullets, `red_flags` bullets (red tone), `orbit` as name — role — note rows; stamp `desk · updated YYYY-MM-DD` + `staleness_flag`. Insert into `render_dashboard_html` chain before `_comms_html`.
- Bump the packet contract string only if the loader validates it (grep `FLIGHT_DASHBOARD_PACKET` in `load_snapshot` — if it pins `v2` exactly, keep `v2` and document the optional key; do NOT invent `v2.1` unless something parses the version).

### Key Constraints
- Escape everything (existing `_esc` discipline).
- Do not seed placeholder content in AO-OSK-001.json — empty-state honesty until ao-desk delivers (its task is on the bus, topic `baker-os-v2/ao-flight-relationship`).
- Investment-total note: `AO_INVESTMENT_TOTAL` (EUR 66.5M @2026-06-01) is DESK-owned — whether it joins `money_kpis` is ao-desk's call in its content pass, not this worker's.

### Verification
Unit tests (present/absent/empty + escaping). Post-deploy: page 200, no card until desk content lands; card renders correctly after.

---

## Fix 3: Discard the cockpit AO Dashboard (nav + endpoint)

### Problem
Director-ratified discard once Fixes 1-2 exist. The tab's unique live assets are carried by the flight page; what remains is dead groups + a lying gap indicator.

### Current State
- Nav: `outputs/static/index.html` `data-tab="ao-dashboard"` (~line 78 post-CRD_2, includes `aoDot` nav-dot span — locate by grep, CRD_2 shifts lines).
- Frontend: `app.js` `loadAOTab()` (~10764), `_renderAODashboard`, `_updateAODot`, tab wiring at ~817, `FUNCTIONAL_TABS` entry `'ao-dashboard'`, view div `viewAO`.
- Backend: `GET /api/dashboard/ao` (`outputs/dashboard.py` ~18324) + `_load_ao_view_files` (~18280, reads a directory deleted 2026-04-22) + `_get_ao_orbit_names` + `AO_INVESTMENT_TOTAL` constants.

### Engineering Craft Gates
- Diagnose: N/A — ratified removal. Prototype: N/A.
- TDD: applies — endpoint 410 test + grep asserts; test-suite reconciliation for anything referencing `ao-dashboard`/`viewAO`/`/api/dashboard/ao` (invert to guard the removal, CRD_1 pattern; report inversions).

### Surface contract
- **Surface:** old cockpit SPA (reference desk, Pattern C) + its API.
- **Change:** remove the `ao-dashboard` nav item (+ its divider if orphaned). Keep `viewAO` div + guarded JS (CRD_1 retention doctrine — deep-link shows the honest error banner once the endpoint is gone). Endpoint returns **410 Gone** with body `{"detail": "AO dashboard moved to /flight/AO-OSK-001"}` — do not delete the route (a 404 would read as a bug; 410 is a signpost). Delete `_load_ao_view_files` (reads a deleted directory) and its cache; keep `_get_ao_orbit_names` ONLY if anything else imports it (grep; if unused, delete), keep `AO_INVESTMENT_TOTAL` constants ONLY as a comment breadcrumb pointing to ao-desk ownership — or move the figure verbatim into the 410 body comment; either way no orphan silent constants.
- **Verify:** nav grep = 0; `curl -s -o /dev/null -w '%{http_code}' -H "X-Baker-Key: $KEY" .../api/dashboard/ao` = 410; landing + other tabs regress-free, console clean.

### Implementation
Straightforward per above. Tombstone comments name this brief + Director directive 2026-07-09.

### Key Constraints
- Same-file overlap with CRD_2 (index.html) — this brief merges AFTER CRD_2; rebase conflicts are expected to be trivial (different regions).
- Ship all three fixes in ONE PR/deploy — the discard must never be live before the flight-page replacements (single-deploy atomicity satisfies the ordering).

---

## Files Modified
- `orchestrator/flight_dashboard.py` — comms-gap machine element + relationship renderer (Fixes 1-2)
- `orchestrator/flight_dashboards/AO-OSK-001.json` — `comms_contact` config (Fix 1)
- `outputs/dashboard.py` — `/api/dashboard/ao` → 410 + dead-helper cleanup (Fix 3)
- `outputs/static/index.html` — ao-dashboard nav removal (Fix 3)
- `tests/` — new flight-dashboard tests + reconciled cockpit tests

## Do NOT Touch
- `orchestrator/flight_dashboards/BB-AUK-001.json` — zero change; its render must be byte-identical (regression test).
- `outputs/static/app.js` — guarded loaders stay (CRD_1/CRD_2 doctrine); no cache-bust churn unless app.js is actually edited (it should not be).
- `orchestrator/arrivals_board.py`, `flight_snapshot.py`, cockpit_serve — different surfaces.
- `pm_project_state` machinery (`ao_pm` writers) — the intelligence source keeps its owner.
- CRD_2 scope (sentinel retirement etc.) — separate brief, do not fold.

## Quality Checkpoints
1. Compile clean: `flight_dashboard.py`, `dashboard.py`; `node --check outputs/static/app.js` (sanity, unchanged).
2. New unit tests pass; full `pytest` zero new failures vs main (junit failing-id diff, CRD_1 method).
3. BB-AUK-001 regression: rendered HTML byte-identical pre/post (snapshot test or manual diff) — the optional-section machinery must be invisible to flights without the keys.
4. Post-deploy: `/flight/AO-OSK-001` shows `LAST DIRECT AO CONTACT` with a real date matching Verification SQL; tone matches the true gap; NO green on failure paths (spot-check by temporarily impossible config in a unit test, not in prod).
5. Post-deploy: `/api/dashboard/ao` returns 410 with the pointer body; cockpit nav has no AO item; console clean.
6. Relationship card: renders honestly per desk-content state at deploy time (empty → omitted; present → escaped + stamped).
7. Ship report states explicitly whether ao-desk content had landed (and if not, that the empty-state path is what was verified).
8. `POST_DEPLOY_AC_VERDICT` on bus.

## Verification SQL
```sql
-- ground truth the flight page's LAST DIRECT AO CONTACT line must match
SELECT GREATEST(
  (SELECT MAX(timestamp) FROM whatsapp_messages WHERE chat_id = '491736903746@c.us'),
  (SELECT MAX(created_at) FROM sent_emails WHERE to_address ILIKE ANY(ARRAY['ao@aelioholding.com','%oskolkov%']))
) AS last_direct_contact
LIMIT 1;

-- living intelligence source freshness (context for reviewers; ao-desk owns content)
SELECT updated_at FROM pm_project_state
WHERE pm_slug='ao_pm' AND state_key='current' LIMIT 1;
```
```bash
# post-deploy
curl -s -o /dev/null -w '%{http_code}\n' -H "X-Baker-Key: $BAKER_API_KEY" https://baker-master.onrender.com/api/dashboard/ao   # 410
curl -s -H "X-Baker-Key: $BAKER_API_KEY" https://baker-master.onrender.com/flight/AO-OSK-001 | grep -o "LAST DIRECT AO CONTACT[^<]*"
```
