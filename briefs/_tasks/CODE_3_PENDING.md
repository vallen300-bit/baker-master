---
dispatch: MCP_INBOX_READ_UNACKED_FILTER_1
to: b3
from: lead
dispatched_by: lead
status: COMPLETE
completed: 2026-06-03 — PR #284 merged baker-master (squash 22bc518). Gates: G0 codex-arch PASS-WITH-NOTES (#1687, 2 notes relayed/addressed) + G1 lead PASS (39/39 pytest py3.12 literal + diff matches brief) + G2 /security-review CLEAR (param+client-filter only, no SQL/injection/auth/secret surface). Live prod round-trip DONE (b3 msg 1686: post->read present->ack 200->read absent->include_acked present among 96; 96-vs-1 = bug fixed). Known >200 daemon-cap limitation noted in PR. Report: briefs/_reports/B3_MCP_INBOX_READ_UNACKED_FILTER_1_20260603.md
dispatched_at: 2026-06-03
authored: 2026-06-03
target_repo: baker-master (vallen300-bit/baker-master)
estimated_time: ~1h
complexity: Low
reply_to: lead
ship_topic: ship/mcp-inbox-read-unacked-filter-1
anchor_chat: Director 2026-06-03 "go ahead" — dispatch the queued inbox-read unacked-filter fix (b1+b3 idle). Bug surfaced by b3 #1682 during MCP_INBOX_CONTRACT_FIX_1.
---

# B3 dispatch — MCP_INBOX_READ_UNACKED_FILTER_1

## Context

`baker_inbox_read` (MCP) promises in its docstring to return only **unacked** messages
(`acknowledged_at IS NULL`), but the implementation never filters — it returns whatever
the Brisen Lab daemon hands back, which includes already-acked messages. So a caller that
"reads its inbox" sees a growing pile of old, already-processed messages and cannot trust
the count. Surfaced by b3 (#1682) during the MCP_INBOX_CONTRACT_FIX_1 work (PR #283, lesson #86).

This is the sibling of lesson #86: the wire contract is verified against the canonical
client (`scripts/bus_post.py`) and the live drain fixture, not against the tool's own tests.

**Context Contract:**
- **Repo / branch:** baker-master, branch off `main` (e.g. `b3/mcp-inbox-read-unacked-filter-1`).
- **Target file:** `baker_mcp/baker_mcp_server.py` — function `_brisen_lab_read_via_http` (~line 1448) + the `baker_inbox_read` Tool docstring/schema (~line 882) + tests `tests/test_brisen_lab_consumer_mcp.py` (section 4, ~line 342).
- **Live contract source of truth:** the Brisen Lab daemon `GET /msg/<terminal>` returns ALL messages (oldest-first, daemon-capped ~200; `order`/`sort` params ignored). The ack field on each row is `acknowledged_at` (confirmed via `tests/fixtures/session-start-bus-drain.sh` line 147 `m["acknowledged_at"]`). The drain hook uses a `since`-cursor, NOT an unacked filter — do not copy the drain's approach; this tool filters on `acknowledged_at`.
- **Task class:** production bug-fix (MCP server tool, live in prod).
- **Surface contract: N/A — backend MCP tool, no clickable/dashboard surface.**

## Problem

`_brisen_lab_read_via_http` builds query params (`since`, `kind`, `topic`, `exclude_self`,
`limit`) and returns the daemon rows verbatim. It sends **no** `unread` param and does **no**
client-side filter on `acknowledged_at`. The `baker_inbox_read` docstring says it
"Returns messages where the caller's terminal slug is in `to_terminals` and
`acknowledged_at IS NULL`" — that second clause is false today.

## Current State

`baker_mcp/baker_mcp_server.py`, `_brisen_lab_read_via_http` (~1448–1495):

```python
    limit = max(1, min(limit, 200))
    params["limit"] = limit
    url = f"{_brisen_lab_url()}/msg/{terminal}"
    ...
    rows = data if isinstance(data, list) else data.get("messages") or data.get("rows") or []
    if not rows:
        return f"Inbox empty for {terminal} (filters: {json.dumps(...)})"
    return json.dumps(rows, default=_json_serial, indent=2)
```

No unacked filtering anywhere.

## Implementation

### Fix 1 — client-filter on `acknowledged_at` (load-bearing) + decouple fetch from display limit

In `_brisen_lab_read_via_http`, compute the user's requested display limit, fetch a wide window
(so unacked messages aren't hidden behind acked ones inside a small page), then client-filter,
then slice to the user's display limit. Replace the limit-setup (before the HTTP call) and the
rows-handling (after it) as follows; keep the existing `try/except` GET + 503/`>=400`/non-JSON
handling EXACTLY as-is:

```python
    # User-facing display limit (what the caller asked to SEE).
    try:
        display_limit = int(args.get("limit", 50))
    except (TypeError, ValueError):
        display_limit = 50
    display_limit = max(1, min(display_limit, 200))

    include_acked = bool(args.get("include_acked", False))

    # Fetch wide so unacked rows aren't buried behind acked ones in a small page.
    # Daemon hard-caps ~200; fetch the max when we intend to client-filter.
    params["limit"] = 200 if not include_acked else display_limit
    # Hint the daemon too (harmless if it ignores the param — contract says it might).
    if not include_acked:
        params["unread"] = "true"

    url = f"{_brisen_lab_url()}/msg/{terminal}"
    headers = {"X-Terminal-Key": _brisen_lab_terminal_key()}
    # ... existing httpx GET + status handling unchanged ...

    rows = data if isinstance(data, list) else data.get("messages") or data.get("rows") or []

    if not include_acked:
        # Load-bearing: filter regardless of whether the daemon honored `unread`.
        rows = [r for r in rows if not r.get("acknowledged_at")]

    rows = rows[:display_limit]

    if not rows:
        shown = {k: v for k, v in params.items() if k not in ("limit", "unread")}
        suffix = "" if include_acked else " (unacked only; pass include_acked=true to see acked)"
        return f"Inbox empty for {terminal} (filters: {json.dumps(shown)}){suffix}"
    return json.dumps(rows, default=_json_serial, indent=2)
```

### Fix 2 — add the `include_acked` input + tighten the docstring

In the `baker_inbox_read` Tool (~882) add to `inputSchema.properties`:

```python
                "include_acked": {
                    "type": "boolean",
                    "description": "If true, return acked messages too (default false = unacked only).",
                    "default": False,
                },
```

Append one sentence to the description so it matches behavior:
`"Unacked-only by default (client-filters acknowledged_at IS NULL even if the daemon returns acked rows); pass include_acked=true for the full set."`

### Known limitation (document in PR body, do NOT build)
The daemon caps a single GET at ~200 rows. If a terminal has >200 messages where the unacked
ones sit beyond row 200, they won't surface until earlier ones are acked. Pagination is out of
scope — note it in the ship report.

## Key Constraints
- Do NOT change `scripts/bus_post.py` / `bus_post.sh` (canonical clients, correct already).
- Do NOT change the drain hook / fixture (`since`-cursor design is intentional).
- Do NOT touch `_brisen_lab_post_via_http` / `_brisen_lab_ack_via_http`.
- Field name is `acknowledged_at` (not `acked_at`) — any truthy value = acked.
- Fail-open behavior (503 → empty list notice) stays intact.

## Files Modified
- `baker_mcp/baker_mcp_server.py` — `_brisen_lab_read_via_http` (filter + limit decouple) + `baker_inbox_read` Tool schema/docstring.
- `tests/test_brisen_lab_consumer_mcp.py` — section 4 tests (see Verification).

## Do NOT Touch
- `scripts/bus_post.py`, `scripts/bus_post.sh` — canonical correct clients.
- `tests/fixtures/session-start-bus-drain.sh` — intentional since-cursor drain.

## Verification

Add/extend tests in `tests/test_brisen_lab_consumer_mcp.py` section 4 (mock the httpx GET):
1. Daemon returns a MIX of acked + unacked rows → `baker_inbox_read` returns ONLY the unacked.
2. `include_acked=True` → returns ALL rows.
3. All rows acked → "Inbox empty ... (unacked only ...)" notice, not an error.
4. Existing happy-path / fail-open (503) tests still pass.

**Live round-trip (per lesson #86 — exercise the real flow, do not trust mock-green alone):**
post a test message to a scratch terminal via `bus_post.py`; `baker_inbox_read` shows it;
`baker_inbox_ack` it; `baker_inbox_read` no longer shows it. Capture the message_id in the ship report.

```bash
python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"
pytest tests/test_brisen_lab_consumer_mcp.py -v
```

## Quality Checkpoints (Acceptance criteria)
1. `baker_inbox_read` returns only `acknowledged_at IS NULL` rows by default.
2. `include_acked=true` returns the full set.
3. Display `limit` honored AFTER the unacked filter (count is meaningful).
4. New + existing tests pass on a literal `pytest` run (paste output in ship report).
5. Live round-trip verified against the prod daemon (message_id in ship report).
6. Docstring/schema match behavior; known >200 limitation noted in PR body.

## Done rubric (required final state)
PR open against baker-master `main`; `baker_inbox_read` unacked-only by default + `include_acked`
escape hatch; tests green on literal run; live round-trip captured; docstring truthful. Answer
this rubric in the ship report — not just "tests passed."

## Gate plan
- **G0 codex-arch** — brief review (lead requests after dispatch).
- **G1 lead** — literal `pytest tests/test_brisen_lab_consumer_mcp.py -v` + diff review.
- **G2 /security-review** — light (no new external surface; param + filter only).
- Merge on green → lead flips this mailbox to COMPLETE + bus-posts.

Harness-V2: applies (production MCP-server bug-fix) — Context Contract, task class, done rubric, gate plan all above.
