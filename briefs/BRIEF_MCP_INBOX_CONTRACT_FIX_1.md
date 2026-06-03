---
type: ops
author: aihead1
created: 2026-06-03
status: DISPATCHABLE — design-reviewed by deputy/AH2 (#1675); codex-arch G0 waived (mid-G3 on PR #282; AH2 is qualified reviewer)
---

# BRIEF: MCP_INBOX_CONTRACT_FIX_1 — align baker_inbox_* MCP tools to the live daemon contract

## Context
The `baker_inbox_*` MCP tools (`baker_mcp/baker_mcp_server.py`) drifted from the Brisen Lab bus
daemon contract that `scripts/bus_post.py` correctly follows. **`baker_inbox_post` POSTs to
`/msg/{from_terminal}` (the SENDER) instead of `/msg/{recipient}`** — so every message sent via the
MCP tool is stored addressed to the sender and never delivered. The unit tests
(`tests/test_brisen_lab_consumer_mcp.py`) **assert the wrong contract**, so they pass green while
the tool is broken end-to-end (Lesson #8: compile-clean ≠ works). The fleet never noticed because
every agent uses the shell helpers (`bus_post.sh` / drain hooks), which use the correct path+key.
Surfaced by deputy/AH2 (bus #1675) after codex-arch hit it.

### Surface contract: N/A — backend MCP tool + tests; no clickable/dashboard surface.

## Estimated time: ~1.5h
## Complexity: Low-Medium
## Prerequisites: none. Verify against `scripts/bus_post.py` (the canonical correct contract).

---

## Context Contract

### Router
- Routed owner: b3 (idle — PR #281 merged).
- Why this owner: small self-contained backend fix in AH1's MCP-server lane; b3 free.
- Alternatives explicitly rejected: AID-T (enquiry-only per Director 2026-06-03); lead-build (orchestrator lane).

### Problem Evidence
- Desired outcome: `baker_inbox_post/read/ack` MCP tools work end-to-end, matching the daemon contract `bus_post.py` already follows.
- Evidence (verified by AH1 2026-06-03): `baker_mcp/baker_mcp_server.py` `baker_inbox_post` builds `url = f"{_brisen_lab_url()}/msg/{from_terminal}"` (~L1404) and `payload = {"to_terminals": to, ...}` (~L1390). Canonical correct contract: `scripts/bus_post.py` `_post()` uses `url = f"{DAEMON_URL}/msg/{recipient}"` (L90). Daemon reads recipient from the URL path; the body `to_terminals` is ignored.
- Current behavior verified by: deputy #1675 + AH1 direct code read (grep/sed) 2026-06-03.

### Current State
- Existing code searched: `baker_mcp/baker_mcp_server.py` (baker_inbox_post ~L1376-1410; baker_inbox_read ~L1434-1456; baker_inbox_ack ~L1484-1501); `scripts/bus_post.py` (canonical); `tests/test_brisen_lab_consumer_mcp.py` (asserts at ~L128/143/158).
- Prior brief checked: none (git log clean for this fix).
- Code graph search: N/A — grep/Read sufficient.
- DB schema verified: N/A — no DB; HTTP-to-daemon only.
- API/function contracts verified: daemon route `POST /msg/{recipient}` (path = recipient); `GET /msg/{terminal}` reads the caller's inbox; `POST /msg/{id}/ack`. The `X-Terminal-Key` is per-terminal and bound to ONE slug — reading/acking a slug != the key's slug returns 403 `reader_slug_mismatch` (verified this session on lead's own key).

### Interface (interface-first)
- No public-interface change to the MCP tool *schemas* (callers still pass `to`/`kind`/`body`). The fix is internal wire-contract alignment only. The observable behavior change: messages actually reach the recipient; read/ack stop 403-ing for the caller's own inbox.

### Stable Paths
- Files expected to change: `baker_mcp/baker_mcp_server.py` (3 handlers), `tests/test_brisen_lab_consumer_mcp.py` (correct the asserts + add a round-trip test).
- Files explicitly NOT to touch: `scripts/bus_post.py` / `bus_post.sh` (canonical — they are correct; do not "align" them to the broken tool), the daemon, any other MCP tool.
- Volatile files: none.

### Constraints
- Repo hard rules: all HTTP in try/except (already present — preserve); no secrets in code.
- Match `scripts/bus_post.py` EXACTLY — it is the source of truth. Do not invent a new contract.
- Multi-recipient: the daemon URL path takes ONE recipient. Replicate `bus_post.py`'s behavior for multi-recipient (post per recipient, or first-recipient + body list — match whatever bus_post.py does; do NOT guess).
- Security: the read/ack 403 is the daemon CORRECTLY refusing a slug≠key mismatch. The fix is to make the MCP read/ack default the URL-path terminal to the SAME slug the `X-Terminal-Key` is bound to (both derived from the caller's terminal). Do NOT weaken the daemon's slug-key check; do NOT send another terminal's key.
- UI pre-brief: N/A.

### Acceptance Criteria
- Build AC: `python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"` clean.
- Test AC (literal `pytest tests/test_brisen_lab_consumer_mcp.py -v` GREEN, py3.12):
  1. Correct the existing asserts: `baker_inbox_post` URL must be `/msg/{recipient}` (the `to` slug), NOT `/msg/{sender}`; body key `to` (or whatever bus_post.py sends), NOT the drifted `to_terminals`.
  2. **NEW end-to-end round-trip test** (the regression guard): post-as-A-to-B (mock daemon captures), assert the captured URL path = B (recipient) and the recipient is B — so a future sender/recipient swap can't pass green again.
  3. read/ack: assert the URL-path terminal and the key slug are consistent (caller's own slug).
- Post-deploy AC: after merge+deploy, a live MCP round-trip — `baker_inbox_post` from one terminal to `lead`, then `baker_inbox_read` as `lead` returns it. State the live result in the ship report (this is the Lesson-#8 guard — do NOT report "tests pass" as done).
- Done-state terminal class: production MCP fix — terminal = live round-trip delivers + read returns the message.

### Gate Plan
- G0 / Codex: WAIVED — design-reviewed by deputy/AH2 (#1675), a qualified reviewer; codex-arch is mid-G3 on PR #282. (If b3 finds the multi-recipient or slug-key fix non-obvious, escalate to lead.)
- G1 / static review: lead.
- G2 / security-review: LIGHT — touches bus auth (X-Terminal-Key / slug match). Confirm the fix does not send a wrong-slug key or weaken the daemon's mismatch check. Lead runs a focused pass; full `/security-review` only if the diff grows past the 3 handlers.
- G3 / Architect: N/A — small contract-alignment, no new architecture.

### Bus + Writeback
- dispatched_by: lead (aihead1)
- Expected ship-report recipient: lead
- Bus topics: dispatch `dispatch/mcp-inbox-contract-fix-1`; ship `ship/mcp-inbox-contract-fix-1`.
- Memory/writeback: append `tasks/lessons.md` — "MCP inbox tools drifted from daemon contract; tests encoded the drift (green-but-broken); add end-to-end round-trip tests for any wire contract" (Lesson #8 reinforcement).

---

## Implementation notes (verified line refs; b3 confirms before editing — file is volatile)
1. **`baker_inbox_post`** (~L1390-1405): change `payload = {"to_terminals": to, ...}` → key `to` per `bus_post.py`; change `url = f"{_brisen_lab_url()}/msg/{from_terminal}"` → `/msg/{recipient}` where recipient = the `to` slug (mirror `bus_post.py._post(recipient=...)`). Handle multi-recipient exactly as `bus_post.py` does.
2. **`baker_inbox_read`** (~L1434-1456): ensure `terminal` (URL path) defaults to the caller's own slug, derived the same way the `X-Terminal-Key` slug is, so no `reader_slug_mismatch`.
3. **`baker_inbox_ack`** (~L1484-1501): same slug-key consistency.
4. **Tests** (`tests/test_brisen_lab_consumer_mcp.py` ~L128/143/158): rewrite the drifted asserts to the correct contract + add the round-trip regression test.

## Files Modified
- `baker_mcp/baker_mcp_server.py` — 3 inbox handlers.
- `tests/test_brisen_lab_consumer_mcp.py` — correct asserts + new round-trip test.

## Do NOT Touch
- `scripts/bus_post.py` / `bus_post.sh` — canonical correct contract.
- The daemon / its slug-key check — the 403 is correct behavior.

## Quality Checkpoints
1. MCP post lands at `/msg/{recipient}`, not `/msg/{sender}` — proven by the new round-trip test.
2. Body key matches `bus_post.py` exactly.
3. read/ack use the caller's own slug+key (no 403 on own inbox).
4. Old drifted asserts are gone; a sender/recipient swap now fails the test.
5. `pytest tests/test_brisen_lab_consumer_mcp.py -v` GREEN on a literal run + live round-trip in ship report.

## Verification
```
python3 -c "import py_compile; py_compile.compile('baker_mcp/baker_mcp_server.py', doraise=True)"
pytest tests/test_brisen_lab_consumer_mcp.py -v
# post-deploy: baker_inbox_post to lead, then baker_inbox_read as lead returns it
```
