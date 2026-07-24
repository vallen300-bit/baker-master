# BRIEF: EDITA_LEAD_MCP_CONNECTOR_1 — remote MCP connector for edita-lead app seat (bus post/read/ack, scoped key)

## Problem

Edita Vallen (app-only, non-technical, own claude.ai account) has no two-way channel to the fleet. She needs a remote MCP connector she can paste once into claude.ai Settings > Connectors that lets her post to and read from the Brisen Lab bus AS a new scoped seat `edita-lead` — authenticated with a per-seat terminal key, NEVER the shared daemon key and NEVER baker-master's shared `BAKER_API_KEY` /mcp path (BUS_WIRING_AUDIT_1 trap, explicitly banned in the dispatch).

Dispatch: cowork-ah1 bus #15694, Director GO. `dispatched_by: cowork-ah1` — report back to cowork-ah1 AND lead.

## Context

- Pre-check done by cowork-ah1: NO existing edita seat anywhere (agent_registry.yml, 1Password Baker-API-Keys vault, brisen-lab code). Greenfield. Residual: only Edita can check her own claude.ai Settings>Connectors for leftovers — Director handles.
- Architecture ruling (lead): the MCP endpoint lives ON the brisen-lab daemon, NOT baker-master. Reasons: (a) identity is server-derived from the existing scoped `X-Terminal-Key` infra (`auth_lab.py resolve_terminal_key`) — no second keyring; (b) claude.ai custom connectors cannot set custom headers, so the key rides a `?key=` query param, same precedent as baker-master `/mcp?key=` (`outputs/dashboard.py:2068-2071`); (c) Streamable HTTP stateless JSON-RPC per Lesson #31 — NO SSE (reconnect session-id churn).
- Reference implementation to mirror: baker-master `outputs/dashboard.py:2139-2248` (`_handle_mcp_message` + `POST /mcp` + `GET /mcp` info stub). Copy the JSON-RPC envelope shape exactly (initialize / ping / tools/list / tools/call / notifications→202).

## Estimated time: ~3h
## Complexity: Medium
## Prerequisites: lead commits the `edita-lead` registry entry to `~/baker-vault/_ops/registries/agent_registry.yml` BEFORE you regenerate identity artifacts (lead does this at dispatch time — verify the entry exists with `grep -n "slug: edita-lead" ~/baker-vault/_ops/registries/agent_registry.yml` as your first act; if absent, STOP and post lead).

## Baker Agent Vault Rails
Relevant: bus-and-lanes (bus contract, seat identity), verification-surfaces (gate + tests).
Ignored: loop-runner, skills-and-playbooks, memory-and-lessons (no skill/memory surface in scope).

## Harness V2

- **Task class:** feature (production, auth surface) — full gate chain.
- **Context Contract:** inputs = this brief + brisen-lab origin/main (≥ @87e369e) + vault registry @e1298a3 (edita-lead AG-406 already committed) + reference impl `outputs/dashboard.py:2139-2248`. b3 needs NO other agent's library; unknowns route to lead on bus.
- **Done rubric / done-state class:** DONE = both PRs open with literal pytest output + 14-row table in ship report + codex gate PASS. NOT done at compile-clean; NOT done at self-verify (Lesson #131b). Live E2E is lead's post-merge lane, excluded from b3's done-state.
- **Gate plan:** codex gate (cite repo+branch+sha) + `/security-review` on the brisen-lab PR (new public auth surface) → lead merge/deploy → ARM 14-row stamp (three-signature done-gate; registry `pending-arm-stamp` until ARM PASS).

---

## Fix/Feature 1: `POST /mcp` Streamable HTTP endpoint on brisen-lab daemon

### Problem
brisen-lab has no MCP surface (verified: no `mcp`/`jsonrpc` hits in `app.py`/`bus.py`). claude.ai needs one URL exposing three tools: `bus_post`, `bus_read`, `bus_ack`.

### Current State
- Auth: `auth_lab.py:53-89` — `load_terminal_keys()` reads `BRISEN_LAB_TERMINAL_KEYS` JSON env; `resolve_terminal_key(presented_key)` constant-time-matches and returns the seat slug. Identity is ALWAYS server-derived from the key (E12 rule, `bus.py:~2121`).
- Bus internals: `POST /msg/{terminal}` → `post_msg()` at `bus.py:2045`; `GET /msg/{terminal}` → `get_msg()` at `bus.py:2490` (policy RECIPIENT_OF_TERMINAL); ack core `_ack_core_sync(msg_id, slug, is_director)` at `bus.py:1057`.
- Line numbers are from a checkout at @4e5f27a — RE-VERIFY against your base (origin/main ≥ @87e369e, post-librarian); functions may have moved.

### Engineering Craft Gates
- Diagnose: N/A — greenfield feature, no bug.
- Prototype: N/A — transport + envelope already proven by baker-master `/mcp`; no open design question.
- TDD/verification: applies — public interface = `POST /mcp`. Write the first vertical test BEFORE implementing: authed `tools/call bus_post` from a test key mapped to a test slug lands a row in `brisen_lab_msg` with `from_terminal=<that slug>`. Then the envelope tests.

### Implementation
New module `mcp_lab.py` in brisen-lab repo root (keep `bus.py` growth down), router included from the main app.

1. **Auth helper** — key via query param or header, resolved to a slug:
```python
from auth_lab import resolve_terminal_key

def _mcp_seat_slug(request) -> str | None:
    """Return the authenticated seat slug, or None. Key rides ?key= (claude.ai
    connectors cannot set headers) or X-Terminal-Key (curl/tests). NEVER log
    the key value; log only the resolved slug."""
    key = request.query_params.get("key") or request.headers.get("x-terminal-key", "")
    if not key:
        return None
    return resolve_terminal_key(key)  # constant-time; None on miss
```

2. **Three tools**, dispatched inside `tools/call`. Do NOT re-implement validation — call the existing core paths that `post_msg`/`get_msg` use (extract a sync core if needed, the same way `_ack_core_sync` already exists). Contract (mirror `scripts/bus_post.py` wire contract — Lesson #86: field is `to`, not `to_terminals`, on the POST body path you reuse):
   - `bus_post {to: str, body: str, topic?: str}` → posts as `from_terminal=<derived slug>`; recipient canonicalized via the existing `canonical_recipient()`; unknown recipient returns the tool-error envelope, not a 500.
   - `bus_read {status?: "unacked"|"all", limit?: int<=20}` → reads ONLY the caller's own inbox (`terminal = derived slug` — hard-code, never a caller-supplied terminal; that is the RECIPIENT_OF_TERMINAL fence). Default unacked, limit 10. Return compact JSON: id, from, topic, body, created_at, acked.
   - `bus_ack {message_id: int}` → `_ack_core_sync(message_id, slug, is_director=False)`; idempotent.
   - Tool descriptions must be written FOR EDITA — plain English, no fleet jargon (she is non-technical; the description is her only UI). Example for bus_post: "Send a message to a Brisen team agent. 'to' is the agent name, e.g. lead (chief of staff) or cowork-ah1."
3. **Endpoint** — mirror `dashboard.py:2197-2248` exactly: 401 JSON-RPC envelope on auth fail; parse-error 400; batch array handling; notifications → 202; blocking work via `asyncio.to_thread` (the MCP_EVENTLOOP_OFFLOAD_502_FIX_1 lesson — never run blocking psycopg2 inline on the event loop). Add the `GET /mcp` info stub too (legacy-client redirect message).
4. **Rate guard**: reuse whatever per-seat rate limiting `post_msg` already applies; if none is reusable at the core layer, add a simple per-slug in-process counter (e.g. 30 calls/min) on the MCP route only — this is a public-internet auth surface.

### Key Constraints
- NEVER accept or fall back to the shared daemon key or any non-seat key. `resolve_terminal_key` only.
- NEVER log the presented key (query params leak into access logs by default — confirm uvicorn access-log format does not print query strings for /mcp, or strip/mask it).
- Identity is server-derived ONLY. No tool argument may override the sender or the read-target inbox.
- No SSE. No sessions. Stateless JSON-RPC only.
- All DB calls fault-tolerant: try/except with `conn.rollback()` in except blocks; every SELECT has a LIMIT.
- Do not touch existing `/msg/*` endpoint behavior — additive module only.

### Verification
- `pytest` unit tests (new `tests/test_mcp_lab.py`): (a) no key → 401; (b) wrong key → 401; (c) valid key `tools/list` → 3 tools; (d) `bus_post` inserts with correct `from_terminal`; (e) `bus_read` returns only own-inbox rows; (f) `bus_read` cannot read another seat's inbox via any argument; (g) `bus_ack` idempotent; (h) batch + notification envelope shapes; (i) initialize returns protocolVersion.
- Literal pytest output in the PR description. No pass-by-inspection.

---

## Fix/Feature 2: seat wiring — 14-row install map (enumerated per SOP; external App seat ⇒ most rows N/A)

### Problem
`edita-lead` must exist as a first-class bus slug or `canonical_recipient()` rejects her and no agent can post to her.

### Implementation
Registry entry (lead commits to vault at dispatch; shown for reference — mirror `cowork-bb-desk`, the prior talk-only App seat):
```yaml
  - agent_id: AG-<next>
    display_name: Edita Lead
    slug: edita-lead
    status: active
    bus_enabled: true
    aliases: []
    scope: matter-desk
    runtime: app-claude
    wakeable: false
    reports_to: lead
```
Then b3: run `python3 scripts/generate_agent_identity_artifacts.py --write` in the brisen-lab checkout AND in baker-master; commit regenerated `agent_identity_generated.py` (brisen-lab) + `agent_identity_generated.sh`/`agent_identity_data.py` (baker-master). Verify `edita-lead` lands in `VALID_BUS_SLUGS` and is ABSENT from `WAKEABLE_TERMINALS` + `REFRESHABLE_SLUGS` (the `wakeable: false` + `app-claude` predicates do this at the source — `generate_agent_identity_artifacts.py:130-155`).

Safety net: `grep -rn "cowork-bb-desk" <brisen-lab>/ --include="*.py" --include="*.js" --include="*.html"` — every hand-maintained list where the prior talk-only App seat appears, add `edita-lead` the same way; every list where it does not appear, leave alone.

**Row-by-row (never silently omit — SOP hard rule):**
- Row 1 picker folder: N/A — external claude.ai app seat, no Mac session. (Her doc pack lives in shared Dropbox `Edita-Claude` folder — Director/cowork lane, not this brief.)
- Row 2 zshrc alias: N/A — no local session.
- Row 3 Terminal.app profile: N/A — no local session.
- Row 4 picker CLAUDE.md: N/A in-repo. Deliverable instead: a short plain-English "how to use your Brisen connector" note (3 tools, when to message lead vs cowork-ah1) as `briefs/_reports/B3_edita_mcp_usage_note.md` — lead folds it into her Dropbox CLAUDE.md pack.
- Row 5 bus_post.sh recipient whitelist: check — modern bus_post.sh validates recipients against generated artifacts; if a hardcoded case remains, add `edita-lead`.
- Row 6 bus_post.sh sender whitelist: N/A — she never runs bus_post.sh.
- Row 7 SessionStart drain hook: N/A — no Claude Code session; her inbox drains via `bus_read` tool.
- Row 8 1Password key: lead Tier-B post-merge (`BRISEN_LAB_TERMINAL_KEY_edita-lead`, category "API Credential", field `credential` — Lesson #78).
- Row 9 Render env `BRISEN_LAB_TERMINAL_KEYS` + explicit deploy: lead Tier-B post-merge.
- Row 10 front-end card: follow the cowork-bb-desk precedent grep above — if talk-only App seats render cards, mirror; if not, N/A. State which in your ship report.
- Row 11 server slug lists (FOUR places): the generated `VALID_BUS_SLUGS` covers canonical validation; run the SOP pre-flight `grep -nE '"lead"|"deputy"|"b1"' bus.py app.py` and mirror `cowork-bb-desk` membership in `KNOWN_CARD_SLUGS` / `_build_terminals_response` / `app.py TERMINALS` / regression tests `tests/test_a3_a8_a9_bus.py`.
- Row 12 snapshot pusher: N/A — no Mac host, nothing to snapshot.
- Row 13 wake-handler (both maps): N/A — `wakeable: false`, no Terminal to wake.
- Row 14 wake-listener allowlist: N/A — same; verify `edita-lead` NOT in generated `WAKEABLE_TERMINALS` so no wake_request ever fires (cowork-bb-desk precedent, codex G3 #5729 H1).

### Verification
- Regression tests updated where `cowork-bb-desk` appears in tests.
- `pytest tests/test_a3_a8_a9_bus.py -v` literal output in PR.

---

## Files Modified
- brisen-lab: `mcp_lab.py` (new), main-app router include (`app.py` or `bus.py` — one line), `agent_identity_generated.py` (regen), `tests/test_mcp_lab.py` (new), `tests/test_a3_a8_a9_bus.py` (+ any list files the cowork-bb-desk grep surfaces).
- baker-master: `scripts/agent_identity_generated.sh` + `scripts/agent_identity_data.py` (regen only).
- baker-master: `briefs/_reports/B3_edita_mcp_usage_note.md` (new, ship report sibling).

## Do NOT Touch
- `auth_lab.py` key-loading/matching logic — consume `resolve_terminal_key`, do not modify.
- Existing `/msg/*` endpoints' behavior — additive only.
- `~/baker-vault/_ops/registries/agent_registry.yml` — lead's lane (verify it, don't edit it).
- Any Render env var — lead Tier-B only (2026-05-17 wipe anchor; merge-mode via `tools/render_env_guard`).

## Quality Checkpoints
1. Base = brisen-lab origin/main at dispatch time (≥ @87e369e). Cite repo+branch+sha in your ship post — never a PR number (#15295 lesson).
2. Syntax check every touched .py; full `pytest` both repos' touched suites.
3. Security: this adds a public auth surface — the PR runs `/security-review` at the gate (Lesson #52 class).
4. Ship report: literal test output + the row-by-row 14-row table with your actual dispositions.
5. Report-backs: bus to lead AND cowork-ah1 (`dispatched_by: cowork-ah1`).

## Lead Tier-B post-merge (NOT b3 — listed so the brief is the one source of truth)
1. 1P key gen (Lesson #78 category rule) → merge into `BRISEN_LAB_TERMINAL_KEYS` on brisen-lab Render (merge-mode, never raw PUT) → explicit `POST /deploys` (env PUT alone does not apply).
2. E2E smoke: curl JSON-RPC `tools/call bus_post` with the new key → row lands `from_terminal=edita-lead`; lead posts a reply → `bus_read` returns it; `bus_ack` clears it.
3. Hand Director the one-time paste: `https://brisen-lab.onrender.com/mcp?key=<edita-key>` + the usage note for her Dropbox pack.
4. Three-signature done-gate: codex gate → lead merge/deploy → ARM stamp (registry row `pending-arm-stamp` until ARM files PASS at `wiki/_fleet/audits/`).

## Verification SQL
```sql
SELECT id, from_terminal, to_terminals, topic, created_at
FROM brisen_lab_msg
WHERE from_terminal = 'edita-lead' OR 'edita-lead' = ANY(to_terminals)
ORDER BY id DESC LIMIT 5;
```
