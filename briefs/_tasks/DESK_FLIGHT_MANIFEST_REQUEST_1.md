# BRIEF — DESK_FLIGHT_MANIFEST_REQUEST_1 (all matter desks)

**From:** lead (AH1) · **To:** hag-desk, movie-desk, ao-desk, origination-desk, baden-baden-desk
**Director directive:** 2026-07-01 — *"we did only one Flight Manifest. Now you need to ask all desks to do their own manifests. We can deal with this tomorrow."*
**Timing:** START TOMORROW (2026-07-02). Do NOT spin tonight. Not urgent-overnight — the drop-log is the safety net (no signal is lost).

---

## Why (the gap, evidence-backed)

Baker's signal-intake Gate-2 only fetches an email if it matches a keyword
(`aukera, annaberg, lilienmatt`) OR the sender is a **registered project participant**.
Today **exactly one matter is registered** — BB-AUK-001 (Aukera/Annaberg). Every other
matter has NO `project_registry` entry, so a matter email that doesn't happen to name the
project on a new thread is dropped (logged to `box5_dropped_signals`, never ticketed to a
desk). Live drop-log proof (2026-07-01): Hagenauer evidence-preservation email
(`i.gfoellner@eh.at`), MOVIE forecast (`rolf.huebner@brisengroup.com`), Brisen-governance
circular (`karin.koehler@brisengroup.com`) — all dropped, all real.

A forthcoming code lane (BOX5_GATE2_PARTICIPANT_FETCH_LANE_1) makes sender-identity a
fetch trigger — but it can only catch signals from **registered participants**. So the
mechanism is only as good as registry coverage. **Your manifest IS the coverage.**

## What each desk delivers (one Flight Manifest per matter you own)

Mirror the BB-AUK-001 pilot exactly. For EACH active matter your desk owns, produce a
participant manifest — a list of every person/entity who legitimately corresponds on that
matter, each row:

```
{ "role": "<counterparty | counterparty-counsel | internal-principal | internal-counsel | agent-gf | tax-counsel | ...>",
  "value": "<email address OR whatsapp_id (NN...@c.us)>",
  "channel": "email" | "whatsapp",
  "confidence": "high" | "medium",
  "display_name": "<name>",
  "source": "<where you confirmed it — room folder / VIP id / Director-confirmed / email header>" }
```

**Rules (from the BB-AUK-001 build):**
- HIGH confidence only for addresses you can source (room From/To, Baker VIP `whatsapp_id`,
  Director-confirmed). Mark inferred ones `medium`; drop anything you're guessing.
- Email participants are the priority (that's what Gate-2 fetches first). WhatsApp ids are a
  bonus — pull `whatsapp_id` from Baker VIP contacts where the person has one.
- Do NOT include one-off/noise senders (newsletters, booking confirmations, marketing).
- Give each matter a project number (`<DESK>-<MATTER>-NNN`), a `desk_code`, a `matter_slug`,
  and the ClickUp `list_id` if the matter has a ticket list.

## Desk assignments + known dropped signal to rescue first

- **hag-desk** → Hagenauer (RG7). **PRIORITY-1 tomorrow AM:** `i.gfoellner@eh.at` —
  *"hagenauer // Brisen | Coordination re further evidence preservation proceedings"*
  (msg `AAQk…k0HQ=`, 2026-07-01 12:01Z) is a **legal / evidence-preservation** signal that
  was dropped. Read it and action it FIRST, then build the manifest (Riel/Insolvenzverwalter,
  Ofenheimer, Bauer, Moravcik, E+H counsel, etc.).
- **movie-desk** → MOVIE / MO Vienna. Rescue `rolf.huebner@brisengroup.com` *"MOVIE updated
  Forecast review"* (msg `AAQk…PGDhs=`) + assess `mhabicher@mohg.com` *"AW: Istanbul booking"*
  (MOHG — matter vs personal). Manifest: MOHG contacts, RG7 GmbH, LCG SA, MO operating team.
- **ao-desk** → AO matters (Villa Gabbiano / Oskolkov side). Build manifest(s) for active AO
  correspondence; note russo-ru untrusted-orientation caveat for RU-side.
- **origination-desk** → Brisen corporate / origination / deals. Likely owns the
  Brisen-governance signal `karin.koehler@brisengroup.com` *"VERY URGENT: Circular resolution
  – Annual financial statements 2025"* (msg `AAQk…niaI=`) — confirm owner (you vs BEN) and
  rescue it.
- **baden-baden-desk** → beyond BB-AUK-001 (done): MRCI GmbH (Balgerstrasse) + any
  Lilienmatt correspondence NOT already under BB-AUK-001. One manifest per additional matter.

## Return path

Post your manifest(s) to **lead** on the bus (topic `manifest/<project-number>`) as the
participant JSON array + the project_number/desk_code/matter_slug/list_id header. AH1
validates + writes to `project_registry` (Tier-B, single-writer — do NOT write the registry
yourself; that's the BB-AUK-001 pattern). Once registered, the Gate-2 participant lane routes
your matter's signals to your desk automatically.

## Out of scope
- No registry writes by desks (AH1 writes, single-threaded). No keyword edits. No code.
- Alias-based matching stays retired (Director ruling §A-LEAD-0701 — explicit code +
  participant identity only; aliases are unsafe for multi-matter counterparties).
