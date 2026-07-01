# BRIEF — BOX5_OUTBOUND_INGEST_1 (Baker OS V2 · Signal Journey · outbound email into ticketing)

**Author:** lead (AH1). **dispatched_by:** lead. **Ship report + gate verdicts → lead.**
**Task class:** production feature, additive + DARK. **Harness-V2:** full (Context Contract + AC + done rubric + gate plan below).
**Builder:** b4 (built airport_ticketing_bridge.py A–E; keep the savepoint/rollback + terminal_status-orthogonality patterns intact).

## Context
Director ruling (2026-07-01): Brisen OUTBOUND email must enter the ticketing system — it drives the ClickUp timetable and the flight process, because outbound is often the RATIFICATION of what humans proposed to the Director. Today `airport_ticketing_bridge.fetch_email_arrivals()` scans `email_messages` by `received_date` + keyword and treats every row as an inbound arrival; there is no direction model (ledger U-1 / U-6). This brief is **Increment 1 — direction-aware ingestion**. The ratification→ClickUp-timetable + flight-state advance is **Increment 2** (codex-arch spec pending, bus #4834) — OUT OF SCOPE here.

### Surface contract: N/A — pure backend bridge change (email→ticket ingestion), no clickable UI surface.

## Estimated time: ~2-3h · Complexity: Medium · Prerequisites: none (outbound already in email_messages)

## Diagnose gate (already run by lead — build on these facts, do not re-litigate)
- `email_messages` columns: message_id, thread_id, sender_name, sender_email, subject, full_body, received_date, priority, ingested_at, source. **No direction/folder/is_sent column. No recipient column.**
- Outbound IS ingested: `dvallen@brisengroup.com` = sender 26,013×; 59,580 rows sender `@brisengroup.com`; sample subjects are clearly sent mail ("Annaberg Status - Closing actions", "Re: Aukera / Annaberg financing - step plan to signing", "DV to sign").
- ⇒ Direction is derivable from `sender_email` (Brisen-controlled address ⇒ outbound). No Graph/`triggers/` change needed; bridge-only change.
- Anchors: `fetch_email_arrivals()` at `orchestrator/airport_ticketing_bridge.py:457`; select at :479-489 (`WHERE received_date >= %s` + keyword/skip filters, `ORDER BY received_date ASC`); schema bootstrap `ensure_airport_ticket_table` ~ :320-370; automated-sender skip = `_SKIP_EMAIL_SENDER_PATTERNS`. **Re-pin all line refs by grep at build time — file is volatile.**

## Engineering Craft Gates
- **Diagnose:** applies — done above (feedback loop = the 5 AC pytest; symptom = outbound never modeled; probe = AC2/AC4).
- **Prototype:** N/A — data shape known, no UI, direction heuristic is a settled engineering call.
- **TDD/verification:** applies — write AC1 (`_classify_direction` unit) first as the vertical seam, then AC2-AC5. No implementation-coupled mocks; use a real temp-conn or the existing bridge test harness.

## Implementation

### 1. Direction classifier (pure function)
Add to `orchestrator/airport_ticketing_bridge.py`:
```python
_BRISEN_OUTBOUND_DOMAINS = {d.strip().lower() for d in
    os.environ.get("BRISEN_OUTBOUND_DOMAINS", "brisengroup.com").split(",") if d.strip()}
_BRISEN_OUTBOUND_ADDRESSES = {a.strip().lower() for a in
    os.environ.get("BRISEN_OUTBOUND_ADDRESSES",
        "vallen300@gmail.com,dvallen@bluewin.ch,office.vienna@brisengroup.com").split(",") if a.strip()}

def _classify_direction(sender_email: str) -> str:
    """'outbound' iff sender is a Brisen-controlled address, else 'inbound'. Never raises."""
    try:
        s = (sender_email or "").strip().lower()
        if not s or "@" not in s:
            return "inbound"
        if s in _BRISEN_OUTBOUND_ADDRESSES:
            return "outbound"
        return "outbound" if s.rsplit("@", 1)[1] in _BRISEN_OUTBOUND_DOMAINS else "inbound"
    except Exception:
        return "inbound"
```

### 2. Additive schema (new migration + bootstrap mirror)
New file `migrations/<next_seq>_airport_tickets_direction.sql`:
```sql
ALTER TABLE airport_tickets ADD COLUMN IF NOT EXISTS direction TEXT NOT NULL DEFAULT 'inbound';
```
Mirror the same `ADD COLUMN IF NOT EXISTS` inside `ensure_airport_ticket_table`. No CHECK constraint (keeps future values open). Do NOT edit any applied migration.

### 3. Tag + persist direction
In the arrival→ticket build path, compute `direction = _classify_direction(arrival.sender_email)` and write it on the INSERT. `AirportArrival`/`AirportTicket` carry a `direction: str = "inbound"` field; include it in `payload()`.

### 4. Dark flag + outbound short-circuit
```python
_OUTBOUND_INGEST_ENV = "AIRPORT_OUTBOUND_INGEST_ENABLED"
def _outbound_ingest_enabled() -> bool:
    return os.environ.get(_OUTBOUND_INGEST_ENV, "false").strip().lower() in {"1","true","yes","on"}
```
In `run_tick`/arrival processing, when `direction == "outbound"`:
- if flag OFF → `continue` (skip exactly as today; zero change to live inbound path).
- if flag ON → persist a `direction='outbound'` row, do NOT create a desk boarding-pass, do NOT nudge, do NOT enter fast/soft lanes, and log exactly one action:
```python
# inside a try/except with conn.rollback() on error
cur.execute(
    "INSERT INTO baker_actions (action_type, target_task_id, payload, trigger_source, success) "
    "VALUES (%s, %s, %s, %s, TRUE)",
    ("airport_ticket.outbound_signal", ticket_id,
     _json_param({"sender": sender_email, "subject": subject[:200],
                  "thread_id": thread_id, "message_id": message_id,
                  "received_at": received_iso}),
     "airport_outbound_ingest"),
)
```

## Key Constraints
- Inbound path behavior byte-identical when flag OFF (regression guard AC4).
- Outbound NEVER boards a desk / nudges / escalates / fast-soft-routes.
- No ClickUp writes, no flight-state/returned-package logic (Increment 2).
- All new DB calls in try/except with `conn.rollback()` before any re-query (`.claude/rules/python-backend.md`); one bad row never stops the batch.
- No new terminal states; `terminal_status` orthogonality unchanged.
- No `triggers/` change.

## Verification (pytest, literal — no "by inspection")
- AC1: `_classify_direction` — brisengroup.com + each Director personal ⇒ `outbound`; counterparty/unknown/junk/empty ⇒ `inbound`; never raises.
- AC2: flag ON — outbound-sender arrival persists `direction='outbound'`, creates NO desk ticket / NO nudge, logs exactly one `airport_ticket.outbound_signal`.
- AC3: flag ON — inbound-sender arrival unchanged (routes as today), persists `direction='inbound'`.
- AC4: flag OFF — outbound-sender arrivals skipped; inbound path byte-identical (regression guard).
- AC5: migration applies clean on a table with existing rows (backfill `'inbound'`); bootstrap idempotent.

## Files Modified
- `orchestrator/airport_ticketing_bridge.py` — classifier, direction field, dark flag, outbound short-circuit + action log.
- `migrations/<next_seq>_airport_tickets_direction.sql` — additive column.
- `tests/test_airport_*` — AC1-AC5.

## Do NOT Touch
- `orchestrator/airport_checkin_reader.py` — receipt loop, unrelated.
- Any applied migration — create new only.
- Fast/soft lane logic (D/E) — outbound short-circuits BEFORE the lanes.
- `triggers/` — outbound already ingested.

## Gate plan
G1 self-check (py_compile + full AC pytest + `bash scripts/check_singletons.sh`) → codex **G3 on the BUS** (topic `gate/box5-outbound-ingest-g3`, effort MEDIUM; focus: additive-only, dark-default-off, outbound-never-boards, inbound-path-unchanged, migration-safe) → lead **G4 `/security-review`** → lead squash-merge. FAIL → route findings to b4, rework, re-gate codex.

## Done rubric
Done = flag OFF is a provable no-op on the inbound path; flag ON captures outbound as a tagged action-evidence signal with zero desk-facing side effects; migration safe; all 5 AC green; codex G3 PASS; G4 clean. Ship report answers this rubric (not "tests pass").

## Branch / hygiene
Branch `box5-outbound-ingest-1`. Path-scoped commits. Co-author trailer: Claude Opus 4.7 (1M context).
