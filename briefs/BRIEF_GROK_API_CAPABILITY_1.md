---
brief_id: GROK_API_CAPABILITY_1
trigger_class: MEDIUM
target_branch: b2/grok-api-capability-1
matter_slug: baker-internal
cross_matter_usage: [all-matter-desks, ao, mo-vie-am, hagenauer-rg7, cupial, baker-internal]
dispatched_by: AH1
dispatched_at: 2026-05-17
director_auth: 2026-05-17 chat — "Draft the brief now. Send it to B2. By bus. Don't worry about confidentiality. Let's try to use it. See what happens."
pattern_source: BRIEF_CLAIMSMAX_API_CAPABILITY_1 (commit 3cbc287) — mirror end-to-end
---

# GROK_API_CAPABILITY_1 — Baker capability: xAI Grok Heavy API client + MCP tools

## Problem

Today Baker's X/Twitter + real-time-web access is fragile:

- **X/Twitter:** Chrome MCP via port-9222 logged-in browser breaks on Chrome quit; syndication endpoint only returns short tweets; truncated previews + articles + threads require Chrome MCP.
- **Real-time web:** Perplexity Ask API works (already wired) but doesn't have native X access.
- **Today's workaround:** Director runs Grok Heavy queries manually for X-data; reads results back into chat.

Director already subscribes to SuperGrok Heavy ($300/mo). xAI exposes a Grok API (`https://api.x.ai/v1`) with native X-data search + real-time web search + long context, priced at $2/M input / $6/M output.

This brief wires the Grok API into Baker as a permanent capability so any matter Desk or AH can call X-data + real-time-web search natively, killing the manual Director-runs-it pattern and replacing the fragile Chrome-MCP path for X data.

**Pilot scope:** "let's try to use it, see what happens" (Director 2026-05-17). Not a high-stakes rollout. Goal is to learn what Grok delivers in our context.

## Authentication

API key NOT yet provisioned. **AH1 will create the xAI API key + store in 1Password + set Render env var `XAI_API_KEY` before B2's merge.** This is a separate Tier B action that runs in parallel to B2's coding.

B2 reads from `os.environ["XAI_API_KEY"]` — never hardcodes, never prompts for it.

Auth pattern (OpenAI-compatible per xAI docs):

```
Authorization: Bearer <key>
```

## Scope

### 1. HTTP client (`kbl/grok_client.py`)

Sync httpx wrapper. Patterned after `kbl/claimsmax_client.py` and `kbl/anthropic_client.py`:

- Base URL from `XAI_BASE_URL` env var (default `https://api.x.ai/v1`)
- Bearer auth from `XAI_API_KEY` env var
- Default request timeout 60s (real-time web may stream slow)
- 429 backoff: honour `Retry-After` header, max 3 retries
- 5xx: surface error, no retry
- Typed exception hierarchy: `GrokAuthError`, `GrokForbiddenError`, `GrokValidationError`, `GrokRateLimitError`, `GrokServerError`, `GrokTransportError`
- All HTTP calls wrapped try/except per repo hard rule (fault-tolerant or it doesn't ship)

Public methods (verify against xAI docs FIRST — see §First step):

- `x_search(query, max_results=10, language=None)` → dict — searches X/Twitter, returns `{summary, tweets: [{url, author, date, text, engagement}]}`
- `web_search(query, freshness="week", max_results=10)` → dict — real-time web search, returns `{summary, citations: [{url, title, date, snippet}]}`
- `ask(prompt, model="grok-4-heavy", max_tokens=4000, tools=None)` → dict — plain Grok chat completion for general reasoning (cost-arbitrage path)

### 2. MCP tools (`tools/grok.py` — new module)

Follow the existing `baker_*` tool pattern (see `.claude/docs/baker-mcp-api.md` for the 24+ tool convention). Register three tools:

| Tool | Args | Returns |
|---|---|---|
| `baker_grok_x_search` | `query, max_results?, language?` | `{summary, tweets: [...]}` |
| `baker_grok_web_search` | `query, freshness?, max_results?` | `{summary, citations: [...]}` |
| `baker_grok_ask` | `prompt, max_tokens?` | `{text, model, tokens_in, tokens_out, cost_usd}` |

Mirror the registration pattern from `tools/claimsmax.py` (commit 3cbc287). Read `tools/__init__.py` and `tools/claimsmax.py` before authoring.

### 3. Capability set registration

Migration `migrations/2026<MMDD>_grok_capability_set.sql` (use today's date):

- `capability_type`: **`'archive'`** (NOT `'domain'`) — mirrors ClaimsMax PR #213 ROUND_2 fix. Reason: `capability_type='domain'` triggers `cortex_phase3_reasoner._load_active_domain_capabilities` which loads tools from `TOOL_DEFINITIONS`, NOT from MCP. Our `baker_grok_*` tools live in MCP, so a 'domain' type would feed Opus a tool-less prompt and silently fail. `'archive'` keeps the capability MCP-invocable by matter Desks without hijacking Cortex Phase 3b.
- `name`: `grok_realtime`
- `description`: "Real-time X/Twitter + web search via xAI Grok Heavy API. Replaces fragile Chrome-MCP X-data path and Director-manual-Grok pattern."
- `trigger_patterns`: `['grok', 'x search', 'twitter search', 'real-time web', 'realtime news']` — narrow, NOT generic 'search' / 'lookup' (which would hijack matter routing per ClaimsMax C1 lesson).
- `active`: `true`

Idempotent INSERT with `ON CONFLICT DO NOTHING` (mirror ClaimsMax migration shape).

### 4. Tests (`tests/test_grok_client.py`)

Target ≥15 pytest cases for parity with `test_claimsmax_client.py`:

- one happy-path test per public method (`x_search`, `web_search`, `ask`)
- one test per exception path (auth / forbidden / validation / rate-limit / server / transport)
- 429 `Retry-After` backoff test (mocked httpx)
- env-var missing test (`XAI_API_KEY` unset → `GrokAuthError`)
- malformed-response test (server returns non-JSON or missing required field)

Mock `httpx.Client` responses. Do NOT call live xAI in unit tests.

Run `python3 -m pytest tests/test_grok_client.py -v` and paste literal output into PR description.

### 5. baker_mcp/baker_mcp_server.py extension

Mirror ClaimsMax integration (commit 3cbc287):

```python
from tools.grok import GROK_TOOL_DEFS, dispatch_grok, GROK_TOOL_NAMES
TOOLS.extend(GROK_TOOL_DEFS)

# inside _dispatch():
if name in GROK_TOOL_NAMES:
    return dispatch_grok(name, arguments)
```

### 6. Doc update (`.claude/docs/baker-mcp-api.md`)

Add a "Grok real-time tools (3)" section mirroring the "ClaimsMax archive tools (7)" section format added in commit 3cbc287.

## First step (BEFORE coding)

Read xAI API docs: `https://docs.x.ai/docs` (verify URL via WebFetch). Confirm:

1. Exact model names available (is it `grok-4`, `grok-4-heavy`, `grok-4-latest`?)
2. How to invoke X-data search vs general web search vs plain text completion — is it a separate endpoint, a tool/function parameter, or a model-side capability triggered by prompt?
3. Response schema — does Grok return structured citations / tweet metadata, or just text?
4. Rate limits + quota visibility
5. Auth header format (confirm Bearer)

**If anything diverges materially from §Scope, bus-post `lead` topic `grok-api-spec-mismatch` with the diff BEFORE coding.** AH1 will amend the brief.

## Out of scope

- Cortex Phase 3b specialist integration (deferred — needs TOOL_DEFINITIONS path, separate brief if Director ratifies)
- Image generation / image edit / image analysis Grok features (deferred to v2)
- Code execution Grok feature (deferred — Baker already has its own sandbox)
- Grok Build CLI install (separate experiment, NOT API integration — Director mentioned `curl -fsSL https://x.ai/cli/install.sh | bash`; you MAY install locally to understand xAI's surface but do NOT wire CLI into Baker in this brief)
- Replacing Perplexity Ask API (parallel capability, NOT a displacement — both stay live)

## Hard rules (from ClaimsMax scar tissue)

1. **NO hardcoded keys.** Env var only. PR fails review if `XAI_API_KEY` literal appears anywhere.
2. **capability_type='archive'** (NOT 'domain'). Mirrors ClaimsMax PR #213 C1 fix. Tool-less-prompt failure mode is invisible until Cortex cycle runs.
3. **Narrow trigger_patterns.** No generic 'search' / 'lookup' — hijacks matter routing.
4. **Fault-tolerant.** Every API call wrapped try/except, return error dict, never raise to MCP caller.
5. **Singleton pattern.** If `GrokClient` ends up holding state, use `_get_global_instance()` factory (`scripts/check_singletons.sh` will block otherwise).
6. **Ship gate.** Literal `pytest` green output pasted into PR description. No "pass by inspection" (Lesson #8 + #65).

## Acceptance criteria

- [ ] All 6 files committed on branch `b2/grok-api-capability-1`
- [ ] PR opened against `main` with literal pytest output in description
- [ ] Migration validated locally (capability_sets row inserted on a test DB)
- [ ] Smoke test (post-merge, AH1 runs against prod): `baker_grok_x_search("Brisen Group")` returns non-empty result; `baker_grok_web_search("EU construction defect law 2026")` returns non-empty result with citations
- [ ] `.claude/docs/baker-mcp-api.md` updated
- [ ] Ship report at `briefs/_reports/B2_GROK_API_CAPABILITY_1_<YYYYMMDD>.md`
- [ ] Bus-post `lead` on PR open with topic `pr-open/grok-api-capability-1`

## Deprecation check

- xAI Grok API: confirmed live as of 2026-05-17 per Director card (Grok 4.20 Heavy, $2/M in, $6/M out)
- Verify model name `grok-4-heavy` (or current equivalent) is the active default — if sunset, use current.
- httpx: latest stable (mirror ClaimsMax client version)

## Migration-vs-bootstrap DDL check

N/A — no `ADD COLUMN`. Single idempotent `INSERT` into existing `capability_sets` table.

## Pre-flight

1. `cd ~/bm-b2 && git pull --ff-only origin main`
2. Read this brief end-to-end
3. Read `kbl/claimsmax_client.py` + `tools/claimsmax.py` + `migrations/20260517_claimsmax_capability_set.sql` — the exact template you're mirroring (commit 3cbc287)
4. WebFetch `https://docs.x.ai/docs` to verify §Scope assumptions
5. If §Scope diverges materially from xAI docs → bus-post `lead` BEFORE coding

## Reporting

- Bus-post `lead` (AH1) when starting (topic `claim/grok-api-capability-1`)
- Bus-post `lead` on PR open (topic `pr-open/grok-api-capability-1`)
- AH1 runs `/security-review` + `feature-dev:code-reviewer` 2nd-pass (mandatory per trigger_class MEDIUM + external API surface)
- AH1 sets Render env var `XAI_API_KEY` before merge (separate Tier B action — runs in parallel to your coding; do NOT block on it for PR open)
- AH1 merges on green; runs smoke test against prod deploy

## Co-Authored-By

```
Co-authored-by: Code Brisen #2 <b2@brisengroup.com>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```
