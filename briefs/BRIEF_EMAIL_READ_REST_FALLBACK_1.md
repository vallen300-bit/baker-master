# BRIEF: EMAIL_READ_REST_FALLBACK_1 — X-Baker-Key REST email search/read so desks aren't blind when the Baker MCP drops

## Context
On 2026-06-29 the claude.ai Baker MCP disconnected mid-session in the Baden-Baden Desk picker. All 54 `baker_*` tools vanished — including `baker_email_search` / `baker_email_read` / `baker_email_attachment_read` — leaving the desk blind to brisengroup.com email while codex-arch pushed two fresh Balazs emails it needed to read (bus #4588, Director-routed to AH1).

The backend was healthy the whole time (baker-master HTTP 200, db connected, 29/29 sentinels). The drop was a transient **client-side MCP connection** failure, not an outage. Today there is **no REST read fallback**: `dashboard.py` exposes only `POST /api/emails/backfill` + `/api/emails/backfill-attachments` (ingestion). Desks confirmed `/api/email|emails|email/read` all 404.

We already have the proven resilience pattern: `GET /api/whatsapp/messages` (PR #218) lets every desk read WhatsApp via one X-Baker-Key curl when the MCP is down — same way we read the bus via brisen-lab curl when the MCP drops. This brief gives email the same fallback.

### Surface contract: N/A — pure backend. Two read-only JSON/markdown REST endpoints consumed by desk agents via curl; no dashboard card, no clickable UI, no static asset, no mobile surface.

## Estimated time: ~1.5h
## Complexity: Low
## Prerequisites: none (reuses existing `tools/email.py` + `email_messages` table already in prod)

---

## Harness V2

**Context Contract** — Stakeholder: matter desks (and any agent) that read brisengroup.com email through the claude.ai Baker MCP. When that MCP connection drops mid-session the consumer is fully email-blind with no fallback. Producer surface = two new read-only REST routes on baker-master, gated by X-Baker-Key, consumed via curl (no UI). Out of contract: attachments (Phase 2), any write path, any `tools/email.py` change.

**Task class** — additive backend REST endpoints (read-only) + live-prod verification. Not a bug fix (backend was healthy); a resilience capability mirroring `GET /api/whatsapp/messages` (PR #218).

**Done rubric / done-state class** — TWO distinct states, never conflated: (1) **Build-done** = PR merged + AC1 (`py_compile` clean) + AC2 (no duplicate route) green. (2) **Arc-done** = `POST_DEPLOY_AC_VERDICT v1` posted to lead with AC3/AC4/AC5 PASS against live prod (per `post-deploy-ac-bus-gate` SKILL).

**Gate plan** — G1: builder runs `py_compile` + the no-duplicate-route grep, opens PR → codex gate-3 (independent review, effort medium) → lead merges → builder runs the 4 live prod probes post-deploy → `POST_DEPLOY_AC_VERDICT v1` to lead.

---

## Feature 1: `GET /api/emails/search` + `GET /api/emails/read` (X-Baker-Key gated)

### Problem
Desks have no non-MCP path to read brisengroup.com email. When the claude.ai Baker MCP drops mid-session, the desk is fully email-blind until it reconnects/relaunches.

### Current State
- The MCP email tools are backed by `tools/email.py`. The clean public entry point is **`dispatch_email(name: str, args: dict) -> str`** (`tools/email.py:897`), which routes `baker_email_search` → `_search()` and `baker_email_read` → `_read()`, returns a **JSON string**, and is **fault-tolerant (never raises)**.
- Search reuses `_build_email_search_sql()` / `_store_search()` over the merged **`email_messages`** store (cols: `message_id, thread_id, sender_name, sender_email, subject, full_body, received_date, priority, ingested_at, source`). Supports `provider` = `store` (default, reliable) | `graph` (live M365, freshest pre-ingestion) | `all`, and an optional `source` filter (`gmail|graph|exchange`).
- `_store_search()` already surfaces a backend outage **loudly** via `backend_unavailable: true` + a `notice` — so an empty result is never misread as "no mail".
- WhatsApp endpoint at `outputs/dashboard.py:2543` is the structural template (Query params, `format=json|md`, `verify_api_key` dep, `PlainTextResponse` for md).
- `verify_api_key` dependency is at `outputs/dashboard.py:188`. Imports already present (lines 24/26/30/32): `date`, `datetime`, `Literal`, `Optional`, `Query`, `Depends`, `Header`, `JSONResponse`, `PlainTextResponse`.
- Collision check: **no existing** `GET /api/emails/(search|read)` route — clear to add.

### Engineering Craft Gates
- **Diagnose: N/A** — not a bug. The MCP drop is transient/client-side and already diagnosed (backend healthy). This is a new resilience capability, not a fix.
- **Prototype: N/A** — data shape + query logic already exist and are proven in `tools/email.py`. No UI/state/data-shape uncertainty. The endpoint is a thin REST wrapper over an existing, tested public function.
- **TDD/verification: applies** — public interface = the two new GET routes. First vertical probe is a **live prod curl** (below). A live probe is the honest seam here, not a local unit test: `email_messages` is empty in local/CI (no `TEST_DATABASE_URL` rows), so only prod exercises the real read path. The pure SQL builder (`_build_email_search_sql`) is already covered in the tools-layer tests; do not duplicate.

### Implementation

**File: `outputs/dashboard.py`** — add directly **after** the WhatsApp messages endpoint block (after the `return {... "messages": messages}` that ends `whatsapp_messages_endpoint`, ~line 2624). Two small md formatters first, then the two routes.

```python
# ============================================================
# EMAIL_READ_REST_FALLBACK_1: X-Baker-Key email search/read so desks
# aren't blind to brisengroup.com mail when the claude.ai Baker MCP drops
# mid-session (bus #4588). Mirrors GET /api/whatsapp/messages (PR #218).
# Logic is single-sourced from tools.email.dispatch_email — NO SQL here,
# so the email_messages schema (PK is message_id, the outlier table —
# lesson #211) stays owned in one place.
# ============================================================
def _format_email_search_md(data: dict) -> str:
    if data.get("backend_unavailable"):
        return ("⚠️ Email search backend unavailable — retry; do NOT read this "
                "as 'no mail'.")
    matches = data.get("matches", []) or []
    if not matches:
        return f"No emails matched: {data.get('query', '')}"
    lines = [f"# Email search: {data.get('query', '')} ({len(matches)} match(es))", ""]
    for m in matches:
        lines.append(
            f"- **{m.get('subject') or '(no subject)'}** — "
            f"{m.get('sender') or '?'} — {m.get('date') or '?'}"
        )
        lines.append(f"  `{m.get('message_id')}` [{m.get('source') or '?'}]")
        snip = (m.get('snippet') or '').strip().replace("\n", " ")
        if snip:
            lines.append(f"  {snip[:300]}")
    return "\n".join(lines)


def _format_email_read_md(data: dict) -> str:
    if data.get("error"):
        return (f"⚠️ {data['error']} "
                f"(message_id: {data.get('message_id', '?')})"
                + (f" — {data['hint']}" if data.get("hint") else ""))
    msg = data.get("message", {}) or {}
    body = msg.get("full_body") or "(empty body)"
    return "\n".join([
        f"# {msg.get('subject') or '(no subject)'}",
        f"From: {msg.get('sender_name') or msg.get('sender_email') or '?'}",
        f"Date: {msg.get('received_date') or '?'}  |  Source: {msg.get('source') or '?'}",
        f"Message-ID: {msg.get('message_id')}",
        "",
        body,
    ])


@app.get("/api/emails/search", tags=["emails"], dependencies=[Depends(verify_api_key)])
async def emails_search_endpoint(
    query: str = Query(..., min_length=1,
                       description="Tokenized search; ANDs tokens across "
                                   "subject/sender/body; supports Gmail-style "
                                   "after:/before: date operators"),
    provider: Literal["store", "graph", "all"] = Query(
        "store", description="store = merged email_messages (reliable, default); "
                             "graph = live M365 (freshest, pre-ingestion); all = both"),
    source: Optional[str] = Query(None,
                       description="Optional exact source filter: gmail | graph | exchange"),
    limit: int = Query(10, ge=1, le=50),
    fmt: Literal["json", "md"] = Query("json", alias="format"),
):
    """Read-only email search — REST fallback for the Baker MCP (EMAIL_READ_REST_FALLBACK_1).

    Reuses tools.email.dispatch_email so query logic + email_messages schema stay
    single-sourced. provider=graph gives live M365 freshness when an email is too
    recent to be ingested into the store yet.
    """
    from tools.email import dispatch_email
    try:
        raw = dispatch_email("baker_email_search", {
            "query": query,
            "max_results": limit,
            "provider": provider,
            "source": (source or None),
        })
        data = json.loads(raw)
    except Exception as e:
        logger.error(f"emails_search_endpoint failed: {e}")
        return JSONResponse(status_code=500,
                            content={"status": "error", "message": str(e)})
    if fmt == "md":
        return PlainTextResponse(content=_format_email_search_md(data))
    return JSONResponse(content=data)


@app.get("/api/emails/read", tags=["emails"], dependencies=[Depends(verify_api_key)])
async def emails_read_endpoint(
    message_id: str = Query(..., min_length=1,
                       description="email_messages.message_id (Gmail/Graph string ID)"),
    provider: Literal["store", "graph"] = Query(
        "store", description="store = merged email_messages (default); "
                             "graph = live M365 read for a very recent message"),
    fmt: Literal["json", "md"] = Query("json", alias="format"),
):
    """Read-only single-email read by message_id — REST mirror of baker_email_read.

    On a store miss, the underlying tool returns a hint to retry provider=graph
    for a message too recent to be ingested. See EMAIL_READ_REST_FALLBACK_1.
    """
    from tools.email import dispatch_email
    try:
        raw = dispatch_email("baker_email_read", {
            "message_id": message_id,
            "provider": provider,
        })
        data = json.loads(raw)
    except Exception as e:
        logger.error(f"emails_read_endpoint failed: {e}")
        return JSONResponse(status_code=500,
                            content={"status": "error", "message": str(e)})
    if fmt == "md":
        return PlainTextResponse(content=_format_email_read_md(data))
    return JSONResponse(content=data)
```

### Key Constraints
- **Reuse only — do NOT write new SQL against `email_messages` in `dashboard.py`.** The PK is `message_id` (string Gmail/Graph ID), not `id` — `email_messages` is the outlier table (lesson #211). Routing through `dispatch_email` keeps that owned in `tools/email.py`.
- **Read-only.** No INSERT/UPDATE. No new env vars. No new dependencies.
- Both routes gated by `verify_api_key` (X-Baker-Key) — same auth as WhatsApp/backfill routes.
- `dispatch_email` never raises and always returns valid JSON; the `try/except` around `json.loads` is belt-and-suspenders per the fault-tolerant hard rule. Keep it.
- Do **not** widen `provider`/`source` validation beyond the `Literal` sets shown — bad input must 422 at the FastAPI layer, not reach the tool.
- Attachment-read (`baker_email_attachment_read`) is **explicitly out of scope** — see Phase 2 note below. Do not add it here.

### Verification
**Live prod probes (run after Render deploys). URL-encode the message_id — it contains `=` and `+`.**

1. Search (md), should return matches incl. the live Balazs emails:
```bash
KEY="$(op read 'op://Baker API Keys/X-Baker-Key/credential')"   # or the picker's X-Baker-Key
curl -sS -H "X-Baker-Key: $KEY" \
  "https://baker-master.onrender.com/api/emails/search?query=Annaberg&limit=5&format=md"
```
Expect: a markdown list of matching subjects/senders/dates with message_ids. Non-empty if any "Annaberg" mail is ingested.

2. Read a known message by id (the #4588 "Annaberg Status - Closing actions" email; `--data-urlencode` handles the `=`):
```bash
curl -sS -G -H "X-Baker-Key: $KEY" \
  "https://baker-master.onrender.com/api/emails/read" \
  --data-urlencode "message_id=AAQkAGEzNGM4OWM4LWZjN2YtNDg2ZS05Y2NkLWIxNzkwODEyOGUxMAAQAPUrHikBccNAkrrb0De3zfU=" \
  --data-urlencode "format=md"
```
Expect: the email header + body. If the M365 message isn't ingested into the store yet, expect the store-miss hint (`try provider=graph...`) — that still **validates the route works**; re-run with `&provider=graph` to confirm live M365 read.

3. Auth gate — missing key must 401/403:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" \
  "https://baker-master.onrender.com/api/emails/search?query=test"
```
Expect: `401` or `403`, never `200`.

4. Bad provider must 422:
```bash
curl -sS -o /dev/null -w "%{http_code}\n" -H "X-Baker-Key: $KEY" \
  "https://baker-master.onrender.com/api/emails/search?query=test&provider=bogus"
```
Expect: `422`.

---

## Files Modified
- `outputs/dashboard.py` — add 2 md formatters + 2 GET routes (`/api/emails/search`, `/api/emails/read`) after the WhatsApp messages endpoint (~line 2624). ~90 lines, additive only.

## Do NOT Touch
- `tools/email.py` — reuse `dispatch_email` as-is; do not modify the tool layer. (If a real bug is found in it, that's a separate brief.)
- `POST /api/emails/backfill` + `/api/emails/backfill-attachments` — unrelated ingestion routes; leave unchanged.
- `email_messages` schema / migrations — read-only feature, no schema change.
- The WhatsApp endpoint — template only; do not edit it.

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"` passes.
2. `grep -nE '@app.get\("/api/emails/(search|read)"' outputs/dashboard.py` returns exactly one of each (no shadow/duplicate — lesson #11).
3. All 4 live probes above behave as specified (200+content, auth-gate, 422).
4. `provider=graph` path returns live M365 results (confirms freshness fallback works while MCP is down).
5. No new env vars, no new pip deps, no INSERT/UPDATE introduced.

## Verification SQL (sanity — confirm the store the endpoint reads)
```sql
SELECT message_id, subject, sender_email, received_date, source
FROM email_messages
WHERE subject ILIKE '%Annaberg%'
ORDER BY received_date DESC NULLS LAST
LIMIT 5;
```

---

## Phase 2 (separate brief — NOT this one): `GET /api/emails/attachment`
The desk's live impact also included **attachments** (Annaberg VDR Index .xlsx, Aukera ESG Questionnaire .xlsx). Attachment-read is a bigger lift (R2 byte fetch via `_r2_get_bytes` / on-demand Graph fetch + content-type handling + size caps) and should be its own brief (`EMAIL_ATTACHMENT_REST_FALLBACK_2`) once Phase 1 is live. Note it in the dispatch so it isn't forgotten; do not scope-creep it into Phase 1.

## Follow-on (AH1, after deploy): desk pull skill
Mirror `whatsapp-pull-via-api` with an `email-read-via-api` skill documenting the two curls so every desk has a one-paste fallback path. AH1 authors this; not a B-code task.
