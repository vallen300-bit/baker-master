---
dispatch: M365_GRAPH_MAIL_POLL_2
target: b4
status: COMPLETE
from: cowork-ah1 (Director-directed 2026-06-04)
gate_G0: codex PASS — bus #1806 (G0 v3; Findings 1-3 across #1801/#1804 all folded)
merged: PR #292 squash dfdab00 (G1 lead + G2 /security-review NO-findings + G3 architect SHIP); dormant post-deploy AC PASS (scheduler 64 jobs, graph_mail inert)
dispatched_by: cowork-ah1
reply_to: cowork-ah1
---

# CODE_4_PENDING — M365_GRAPH_MAIL_POLL_2

**b4 — MANDATORY before any reply:** Read this file + `~/baker-vault/_ops/agents/b4/orientation.md` + `~/.claude/projects/-Users-dimitry-Vallen-Dropbox-Dimitry-vallen-Baker-Project/memory/MEMORY.md`. Confirmation phrase: `"B4 oriented. Read: CODE_4_PENDING.md, MEMORY.md."`

**Ship-report recipient:** cowork-ah1 (NOT lead). Bus on every state change (claim / ship / blocker). Gate chain after your ship: G1 lead-static (cowork-ah1) -> G2 /security-review -> G3 architect -> merge -> dormant post-deploy AC.

**This dispatch passed codex G0 v3 (#1806). Implement exactly as the brief below specifies — the three folded findings (raise-on-ready-None, the imports, and the fully-inert dormant path) are load-bearing; do not regress them.**

---

# BRIEF: M365_GRAPH_MAIL_POLL_2 — Microsoft Graph inbound mail poller (delta query)

## Context
Phase 2 of the M365 migration (`~/baker-vault/_ops/briefs/BRIEF_M365_MIGRATION_PROGRAM.md`). Phase 0 (Azure app reg), Phase 1 (Graph client foundation, PR #282), and cert-auth + host-pin (PR #289, `458e3cb`) are merged and live. Live mailbox read was proven this morning (cert-auth `GET /messages` → 200 on dvallen mailbox). The 4 M365 env vars are now wired to baker-master (dormant behind `BAKER_USE_GRAPH=false`).

This brief adds the **inbound mail poller**: a new Graph source adapter that pulls new mail via delta query and feeds Baker's existing email-ingestion pipeline (classification → `signal_queue` → `documents`/Qdrant), running in parallel with the Gmail/Exchange pollers until parity is proven.

Director request: "/write-brief ... and Harness v2 skill. go" (2026-06-04) — produce the Phase 2 mail-poller brief under the Harness V2 contract.

### Surface contract: N/A — backend poller. No Director-facing or clickable UI surface; no new API endpoint; no dashboard change.

## Estimated time: ~3–4h
## Complexity: Medium
## Task class: Medium feature (one new subsystem — a poller source adapter — feeding an existing sink)
## Prerequisites: PR #282 + #289 merged (live on main); 4 M365 env vars on baker-master (done, dormant)
## Harness-V2: applies — Context Contract + gate plan + done stop-gate below.

---

## Context Contract

### Router
- **Routed owner:** B-code (b4 recommended — continuity on the M365 lane; b1 is on INGEST durability in lead's lane).
- **Why this owner:** Implementation task with a self-contained brief; b4 already holds the M365 cert-auth context.
- **Alternatives explicitly rejected:** Researcher (no research gap); AID-T (scopes already delivered #1667); Architect (consulted at G3, not as builder).

### Problem Evidence
- **Desired outcome:** Baker ingests the Director's M365 mailbox automatically, so deal/matter email flows into `signal_queue` + `documents` like Gmail does today.
- **Evidence / source:** Program brief Phase 2 mandate (lines 62–68, 81); live 200 proof this morning; Director directive to build Phase 2.
- **Current behavior verified by:** Graph client merged + host-pin present (`git show origin/main:kbl/graph_client.py`); no Graph poller exists yet (`triggers/` has gmail/bluewin/exchange only).

### Current State
- **Existing code searched:** `triggers/email_trigger.py`, `triggers/exchange_poller.py`, `triggers/scheduler.py`, `triggers/state.py`, `kbl/graph_client.py` (origin/main), `config/settings.py` (origin/main).
- **Prior brief checked:** Program brief Phase 2; cert brief `BRIEF_M365_GRAPH_CERT_AUTH_1`.
- **Code graph search:** N/A — Read/Grep sufficient; the source→sink path is fully traced (below).
- **DB schema verified:** `trigger_watermarks(source PK, last_seen, updated_at, cursor_data TEXT)` — `cursor_data` is the existing opaque-cursor store (used by Dropbox delta). No new table. `signal_queue` is written downstream by the pipeline, not by this poller.
- **API/function contracts verified:**
  - `GraphClient.get(path, params=None, timeout=8) -> dict|None` and `GraphClient.get_url(url, timeout=8) -> dict|None` (host-pinned to `graph.microsoft.com`+https BEFORE token attach; never raises; never logs the URL).
  - `GraphClient.is_ready() -> bool` (True only if `BAKER_USE_GRAPH=true` AND creds present).
  - Sink: `triggers.email_trigger._process_email_threads(new_threads: list)` — consumes thread dicts and runs the full pipeline (dedup, `store_email_message`, `SentinelPipeline.run()` → classify → `signal_queue` → documents/Qdrant, briefing batch).
  - Cursor: `trigger_state.get_cursor(source) -> str|None`, `trigger_state.set_cursor(source, cursor)`, `trigger_state.set_watermark(source, ts)`.
  - Health: `triggers.sentinel_health.report_success/report_failure/should_skip_poll`.

### Stable Paths
- **Files expected to change:**
  - NEW `triggers/graph_mail_trigger.py` (the adapter — the bulk of the work).
  - `triggers/scheduler.py` — register one job in `SentinelScheduler._register_jobs()` (cite the function, not line numbers).
  - `config/settings.py` — add `graph_mail_check_interval` to `TriggerConfig`; add `mail_user` to `GraphConfig`.
- **Files explicitly NOT to touch:** `kbl/graph_client.py` (reuse as-is — do NOT weaken the host-pin), `triggers/email_trigger.py` (import `_process_email_threads`, do not modify it), `triggers/exchange_poller.py` (reference pattern only).
- **Volatile files:** none of the edits are in `dashboard.py`.

### Constraints
- **Repo hard rules:** all DB/API in try/except; `conn.rollback()` in except for any direct DB; every SELECT bounded; never instantiate `SentinelStoreBack()` directly (use `_get_global_instance()`); fault-tolerant or it doesn't ship.
- **Security / auth / external surface:** Graph calls go ONLY through `GraphClient` (host-pin enforced). The stored `deltaLink` MUST be followed via `GraphClient.get_url()` (which re-pins host) — NEVER via a raw `requests.get`. No secrets in code; creds are env-only.
- **Migration / singleton / try-except:** no new migration (reuse `trigger_watermarks.cursor_data`). Poller independence: the job runs in its own scheduler entry with its own try/except — a failure must not affect Gmail/Exchange (program-brief standing rule).
- **UI pre-brief:** N/A — no UI surface.

### Acceptance Criteria
- **Build AC:** `python3 -c "import py_compile; py_compile.compile('triggers/graph_mail_trigger.py', doraise=True)"` clean; `from triggers.graph_mail_trigger import check_new_graph_messages, poll_graph_mail` imports clean.
- **Test AC:** new `tests/test_graph_mail_trigger.py` — (1) with `is_ready()` False, `check_new_graph_messages()` is FULLY inert — no Graph call, no sink call, AND no `set_watermark`/`report_success`/`should_skip_poll` (zero DB + health side effects, per G0 v2 Finding 3); (2) a mocked delta response with 2 messages produces 2 thread dicts in the exact `{"text","metadata":{source,thread_id,subject,primary_sender,primary_sender_email,received_date}}` shape; (3) `@removed` entries are skipped; (4) the returned `@odata.deltaLink` is persisted via `set_cursor`; (5) pagination via `@odata.nextLink` is followed; (6) **failure path** — with `is_ready()` True and the Graph call mocked to return `None`, `poll_graph_mail()` raises, and `check_new_graph_messages()` calls `report_failure` while NOT calling `set_watermark`/`set_cursor` (the silent-success bug must not regress). `pytest tests/test_graph_mail_trigger.py -v` green (literal output in ship report).
- **Post-deploy AC (dormant — fires now):** with `BAKER_USE_GRAPH` unset/false on baker-master, after deploy: scheduler logs `Registered: graph_mail_poll`; the job runs and returns a no-op (`is_ready()` False) with NO error in logs; Gmail/Exchange pollers unaffected (`/api/status` email poll still healthy).
- **Live-cutover AC (later, Director-gated — NOT this deploy):** when `BAKER_USE_GRAPH=true`, a test email to dvallen appears in `signal_queue` (source='graph') and is retrievable via `/api/documents/search` within ~10 min; delta cursor advances; no duplicate processing on the next cycle.
- **Done-state terminal class:** Merged + Deployed + dormant post-deploy AC passed + writeback (PINNED/activity). Live-cutover AC is tracked as a separate Phase-2 go-live step.

### Gate Plan
- **G0 / Codex:** cross-vendor pre-review of this brief + the diff (external surface + SSRF-sensitive host-pin reuse → default-on).
- **G1 / static review:** AH1 (cowork-ah1) static read + literal pytest.
- **G2 / security-review:** REQUIRED — external API + auth + new poller. Focus: deltaLink only ever followed via `get_url` (host-pin), no token/PEM logging, no raw `requests` to Graph.
- **G3 / Architect:** REQUIRED — confirm the source-adapter pattern matches Exchange/Bluewin, the flag-gate keeps it inert, and poller independence holds.

### Bus + Writeback
- **dispatched_by:** cowork-ah1
- **Expected ship-report recipient:** cowork-ah1 (reply to the dispatcher, not `lead`).
- **Bus topics:** claim, ship, gate verdicts, merge, post-deploy AC.
- **Memory/writeback:** AH1 PINNED §M365 + `wiki/_activity/ah1.md` on merge; update program brief Phase 2 row to DONE-dormant.

---

## Feature 1: Graph mail poller (source adapter)

### Problem
No Graph inbound poller exists. Baker cannot see the M365 mailbox even though auth works.

### Current State
`triggers/email_trigger.py:check_new_emails()` already runs Bluewin + Exchange + Gmail as **independent source adapters**, each producing a list of thread dicts and calling the shared sink `_process_email_threads(threads)`. Phase 2 adds a Graph adapter in the same shape. Reference implementation: `triggers/exchange_poller.py:poll_exchange()` (returns `[{"text":..., "metadata":{"source":"exchange","thread_id":...,"subject":...,...}}]`).

### Implementation

**Step 1 — config (`config/settings.py`).**
- In `GraphConfig`, add: `mail_user: str = os.getenv("M365_MAIL_USER", "dvallen@brisengroup.com")`.
- In `TriggerConfig`, add: `graph_mail_check_interval: int = int(os.getenv("GRAPH_MAIL_CHECK_INTERVAL", "300"))`.

**Step 2 — new file `triggers/graph_mail_trigger.py`.** Mirror `exchange_poller.py` + the gate/health pattern from `email_trigger.py`. Import `trigger_state`, `report_success/report_failure/should_skip_poll`, and `_process_email_threads` **exactly as `triggers/email_trigger.py` imports them** (verify the symbols in that file's header — do not invent import paths).

```python
"""M365_GRAPH_MAIL_POLL_2: Microsoft Graph inbound mail poller (delta query).

Independent source adapter — mirrors triggers/exchange_poller.py. Produces
thread dicts and hands them to the shared sink _process_email_threads().
Dormant unless BAKER_USE_GRAPH=true (GraphClient.is_ready() is the single gate).
Never raises to the scheduler; one failure must not affect other pollers.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

from kbl.graph_client import GraphClient
from config.settings import GraphConfig
from triggers.state import trigger_state
from triggers.sentinel_health import report_success, report_failure, should_skip_poll

logger = logging.getLogger(__name__)

_SOURCE = "graph_mail_poll"          # watermark/cursor key
_FOLDER = "Inbox"
_SELECT = "id,conversationId,subject,from,receivedDateTime,body,isDraft"


def _html_to_text(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:10000]              # cap, mirroring exchange_poller


def _to_thread(m: dict) -> dict | None:
    if m.get("isDraft"):
        return None
    sender = (m.get("from") or {}).get("emailAddress") or {}
    body = (m.get("body") or {})
    text_block = (
        f"Email Thread: {m.get('subject','(no subject)')}\n"
        f"From: {sender.get('name','')} <{sender.get('address','')}>\n"
        f"Date: {m.get('receivedDateTime','')}\n\n"
        f"{_html_to_text(body.get('content',''))}"
    )
    return {
        "text": text_block,
        "metadata": {
            "source": "graph",
            "thread_id": m.get("conversationId") or m.get("id"),
            "subject": m.get("subject", ""),
            "primary_sender": sender.get("name", ""),
            "primary_sender_email": sender.get("address", ""),
            "received_date": m.get("receivedDateTime", ""),
        },
    }


def poll_graph_mail() -> list:
    """Pull new mail via delta query. Returns thread dicts (same shape as poll_exchange).

    RAISES on a ready-but-None response (G0 Finding 1): GraphClient never raises and
    returns None on token/HTTP failure (401/403/429/500). When is_ready() is True, a
    None from the delta/nextLink call is a FAILURE, not an empty inbox — raise so the
    caller reports failure and does NOT advance the watermark/cursor. A genuinely empty
    inbox returns a real page with value:[] (no raise). Returns [] only when dormant.
    """
    client = GraphClient(GraphConfig())
    if not client.is_ready():
        return []                    # dormant gate — no token, no HTTP

    results: list = []
    cursor = trigger_state.get_cursor(_SOURCE)   # stored @odata.deltaLink, or None on first run
    if cursor:
        page = client.get_url(cursor)            # host-pinned follow
    else:
        page = client.get(
            f"/users/{client.cfg.mail_user}/mailFolders/{_FOLDER}/messages/delta",
            params={"$select": _SELECT, "$top": 50},
        )
    if page is None:                 # ready but no response → auth/HTTP/429 failure, NOT empty
        raise RuntimeError("graph mail: delta call returned None while ready (auth/HTTP failure)")

    guard = 0
    while page is not None and guard < 50:       # bounded pagination
        guard += 1
        for m in page.get("value", []):
            if "@removed" in m:                  # delta tombstone
                continue
            t = _to_thread(m)
            if t:
                results.append(t)
        nxt = page.get("@odata.nextLink")
        delta = page.get("@odata.deltaLink")
        if nxt:
            page = client.get_url(nxt)
            if page is None:         # mid-pagination failure → raise BEFORE persisting a partial cursor
                raise RuntimeError("graph mail: nextLink page returned None (HTTP failure mid-pagination)")
            continue
        if delta:
            trigger_state.set_cursor(_SOURCE, delta)   # persist ONLY on clean completion
        break
    return results


def check_new_graph_messages():
    """Scheduler entry — every GRAPH_MAIL_CHECK_INTERVAL seconds. Independent try/except.

    Fully inert when dormant (G0 v2 Finding 3): if BAKER_USE_GRAPH is off, return BEFORE
    any should_skip_poll / set_watermark / report_success — zero DB or health side effects,
    so a disabled source never looks 'healthy' in sentinel_health.
    """
    if not GraphClient(GraphConfig()).is_ready():
        return                       # dormant — zero side effects at all
    if should_skip_poll("graph_mail"):
        return
    try:
        threads = poll_graph_mail()
        if threads:
            logger.info("Graph mail: %d new threads to process", len(threads))
            from triggers.email_trigger import _process_email_threads
            _process_email_threads(threads)
        trigger_state.set_watermark(_SOURCE, datetime.now(timezone.utc))
        report_success("graph_mail")
    except Exception as e:
        report_failure("graph_mail", str(e))
        logger.error("Graph mail trigger failed (non-fatal): %s", type(e).__name__)
```

**Step 3 — register the job (`triggers/scheduler.py`, in `SentinelScheduler._register_jobs()`).** Mirror the `email_poll` registration:

```python
from triggers.graph_mail_trigger import check_new_graph_messages
self.scheduler.add_job(
    check_new_graph_messages,
    IntervalTrigger(seconds=config.triggers.graph_mail_check_interval),
    id="graph_mail_poll",
    name="Microsoft Graph mail polling",
)
logger.info(f"Registered: graph_mail_poll (every {config.triggers.graph_mail_check_interval}s)")
```

### Key Constraints
- **Flag-gate is load-bearing:** `is_ready()` False → `poll_graph_mail()` returns `[]` with zero side effects. Shipping with `BAKER_USE_GRAPH` unset is fully inert.
- **deltaLink only via `get_url`:** never reconstruct or raw-`requests` the stored cursor — the host-pin in `get_url` is the SSRF/token-exfil guard.
- **Independence:** the job has its own try/except and its own scheduler entry; never chained to email_poll.
- **No startup backfill:** the delta cursor handles catch-up via the normal poll. Do NOT add a startup catch-up loop (OOM scar) — first run with no cursor does the initial delta sync inside the regular poll, paginated.
- **Dedup is the sink's job:** `_process_email_threads` dedups on `("email", thread_id)` via `trigger_state.is_processed/mark_processed`. Using `conversationId` as `thread_id` matches that contract.
- **Ready-but-None = failure (G0 Finding 1 fold — HIGH):** `GraphClient` never raises; it returns `None` on token/HTTP failure (401/403/429/500). When `is_ready()` is True, a `None` from the delta/nextLink call is a FAILURE, not an empty inbox. `poll_graph_mail` MUST `raise` on `None` (both the initial call and any nextLink page) so `check_new_graph_messages` hits its `except` → `report_failure` and does NOT set the watermark or persist the cursor. A genuinely empty inbox returns a real page with `value: []` (no raise). This makes 429/throttling visible in `sentinel_health` instead of looking like a healthy empty poll.
- **Accepted v1 limitation — Retry-After auto-backoff only:** with the fix above, a 429 surfaces as a visible poll failure; the next fixed-interval (5-min) poll retries. Automatic `Retry-After`-driven backoff is deferred to **Phase 2b** (throttling improbable for one mailbox at delta volume; ~10k req/10min/mailbox limit). Throttling is no longer hidden — only the auto-backoff is deferred.

### Verification
- Build + Test AC above (literal `pytest` in the ship report).
- Dormant post-deploy AC: deploy with flag off, confirm `Registered: graph_mail_poll` in logs + no-op run + Gmail/Exchange unaffected.

---

## Files Modified
- `triggers/graph_mail_trigger.py` — NEW: Graph source adapter (poll + delta + scheduler entry).
- `triggers/scheduler.py` — register `graph_mail_poll` job.
- `config/settings.py` — `GraphConfig.mail_user` + `TriggerConfig.graph_mail_check_interval`.
- `tests/test_graph_mail_trigger.py` — NEW: unit tests (mocked Graph).

## Do NOT Touch
- `kbl/graph_client.py` — reuse as-is; do NOT weaken the host-pin.
- `triggers/email_trigger.py` — import `_process_email_threads`; do not modify the sink.
- `triggers/exchange_poller.py` — reference pattern only.
- No new DB migration — reuse `trigger_watermarks.cursor_data`.

## Quality Checkpoints
1. `is_ready()` False → no Graph HTTP, no sink call (test 1).
2. Thread-dict shape byte-matches what `_process_email_threads` reads (`metadata.thread_id/subject/primary_sender/primary_sender_email/received_date`, top-level `text`).
3. `@removed` tombstones skipped; drafts skipped.
4. deltaLink persisted; nextLink paginated; pagination bounded (guard ≤ 50).
5. Stored cursor followed only via `get_url` (host-pin).
6. Job independent — kill-test: force `poll_graph_mail` to raise, confirm Gmail/Exchange still poll.
7. Deploy dormant; `Registered: graph_mail_poll` in logs; no errors with flag off.

## Verification SQL
```sql
-- After live cutover only (flag on): confirm Graph mail reached the signal queue.
SELECT id, source, primary_matter, summary, created_at
FROM signal_queue
WHERE source = 'graph'
ORDER BY created_at DESC
LIMIT 20;

-- Confirm the delta cursor is advancing (opaque deltaLink stored):
SELECT source, last_seen, (cursor_data IS NOT NULL) AS has_cursor, updated_at
FROM trigger_watermarks
WHERE source = 'graph_mail_poll'
LIMIT 1;
```

---

### Done stop gate
- **Task class:** medium-feature
- **Current lifecycle state:** Briefed (this brief written)
- **Required final state:** Merged + Deployed + dormant post-deploy AC passed + writeback resolved
- **Tests / verification:** `pytest tests/test_graph_mail_trigger.py -v` (literal in ship report) + dormant post-deploy log check
- **Review gates:** G0 codex + G1 lead + G2 /security-review + G3 architect
- **Bus posts:** dispatch → claim → ship → gate verdicts → merge → post-deploy AC (dispatched_by: cowork-ah1)
- **Memory/writeback:** PINNED §M365 + activity log + program-brief Phase 2 row → DONE-dormant
- **STOP conditions checked:** yes — owner named, schema verified (no new table), signatures verified, no UI surface, post-deploy AC defined (dormant now + live-cutover later)
- **Verdict:** NOT DONE — Briefed; next gate is G0 codex pre-review, then dispatch.
