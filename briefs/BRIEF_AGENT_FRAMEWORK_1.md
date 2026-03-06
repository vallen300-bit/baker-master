# BRIEF: AGENT-FRAMEWORK-1 — Capability-Based Multi-Agent Orchestration

**Ticket:** AGENT-FRAMEWORK-1 (ClickUp 86c8n1rz5)
**Author:** Code 300 (Architect)
**Builder:** Code Brisen
**Status:** Ready for implementation
**Priority:** High — Phase 2 keystone
**Version:** 2.0 — Revised after Director architectural review (2026-03-06)

---

## 1. Summary

Build Baker's capability-based orchestration framework. The core insight:
**an "agent" is not a fixed entity — it's a temporary assembly of capabilities
that Baker composes for a specific task, then dissolves.**

A task arrives → Baker decomposes it into sub-issues → selects the right
capability sets → runs them (sequential v1, parallel v2) → synthesizes one
unified answer → delivers to the Director. The decomposer and synthesizer
are themselves capabilities in the registry.

After this brief is implemented:
- Adding a new capability = inserting a row into `capability_sets` table
- Baker dynamically assembles capabilities per task
- Simple tasks (80%) take the fast path: one capability, no decomposition
- Complex tasks (20%) get decomposed, multi-capability, synthesized

---

## 2. Core Concepts — Glossary

| Term | Definition |
|------|-----------|
| **Capability Set** | A composable unit: domain knowledge + system prompt fragment + tool selection + output format. Stored as a row in the DB. What we used to call "agent." |
| **Baker** | The permanent orchestrator. Routes, assembles, monitors, reports. Never changes. |
| **Decomposer** | A special capability that breaks complex tasks into sub-issues and identifies which capabilities each needs. Only invoked on delegate mode. |
| **Synthesizer** | A special capability that combines results from multiple capability runs into one coherent deliverable. |
| **Capability Run** | A single invocation of one capability set against a sub-task. Ephemeral — exists for 10-60 seconds. |
| **Fast Path** | Simple task → one capability → direct run → no decomposition. Handles 80% of requests. |
| **Delegate Path** | Complex task → decomposer → multiple capabilities → synthesizer → unified answer. |
| **Experience Log** | Record of past decompositions, capability selections, and Director feedback. Enables experience-informed retrieval. |

---

## 3. Architecture Overview

```
TASK ARRIVES (Scan / WhatsApp / Trigger)
     │
   BAKER (orchestrator — always present)
     │
     ├── score_trigger() → domain, tier, mode [existing]
     │
     ├── mode = handle ──────────────────────── FAST PATH
     │   └── Router selects ONE capability set
     │       └── CapabilityRunner.run()
     │           └── Result → Director
     │
     └── mode = delegate ────────────────────── DELEGATE PATH
         │
         ├── [1] Experience Retrieval
         │   └── Search past similar tasks for decomposition patterns
         │
         ├── [2] Decomposer Capability
         │   └── Input: task + matter context + past patterns
         │   └── Output: list of sub-tasks + capability slug per sub-task
         │
         ├── [3] Capability Runs (sequential v1 / parallel v2)
         │   ├── Sub-task 1 → [Finance tools + prompt] → result_1
         │   ├── Sub-task 2 → [Legal tools + prompt]   → result_2
         │   └── Sub-task 3 → [IT tools + prompt]      → result_3
         │
         ├── [4] Synthesizer Capability
         │   └── Input: all sub-results + original task
         │   └── Output: unified deliverable
         │
         └── [5] Result → Director
              └── Log decomposition + outcomes to experience table
```

---

## 4. New Files to Create

### 4a. `orchestrator/capability_registry.py` — Capability Registry

**Purpose:** Load capability set definitions from PostgreSQL, cache in memory,
provide lookup by slug, domain, and trigger pattern matching. Also loads
the decomposer and synthesizer as special entries.

```python
"""
Capability Registry — loads capability definitions from DB.
Thread-safe singleton with 5-minute cache (same pattern as VIP cache in decision_engine.py).

Capabilities are composable units of domain knowledge + tools + prompts.
Baker assembles one or more capabilities per task.
"""

@dataclass
class CapabilityDef:
    id: int
    slug: str                    # e.g., "finance", "legal", "decomposer", "synthesizer"
    name: str                    # e.g., "Finance Capability", "Task Decomposer"
    capability_type: str         # "domain" (normal) / "meta" (decomposer, synthesizer)
    domain: str                  # chairman / projects / network / private / travel / meta
    role_description: str        # One paragraph — injected into system prompt
    system_prompt: str           # Full system prompt override (or "" to use base + role)
    tools: list[str]             # Tool names this capability can use
    output_format: str           # "analysis_report" / "email_draft" / "spreadsheet" / etc.
    autonomy_level: str          # "auto_execute" / "recommend_wait" / "escalate"
    trigger_patterns: list[str]  # Regex patterns for explicit invocation detection
    max_iterations: int          # Agent loop iterations (default: 5)
    timeout_seconds: float       # Wall-clock timeout (default: 30)
    active: bool


class CapabilityRegistry:
    """Singleton registry. Loads from DB, caches 5 min."""

    _instance = None
    _cache_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "CapabilityRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_all_active(self) -> list[CapabilityDef]: ...
    def get_by_slug(self, slug: str) -> Optional[CapabilityDef]: ...
    def get_by_domain(self, domain: str) -> list[CapabilityDef]: ...
    def get_decomposer(self) -> Optional[CapabilityDef]: ...
    def get_synthesizer(self) -> Optional[CapabilityDef]: ...
    def match_trigger(self, text: str) -> Optional[CapabilityDef]: ...
    def get_multiple(self, slugs: list[str]) -> list[CapabilityDef]: ...
    def merge_tools(self, capabilities: list[CapabilityDef]) -> list[str]: ...
    def _refresh_cache(self): ...
```

**Key design notes:**
- Cache pattern: identical to `_get_vips()` in `decision_engine.py`
- `get_decomposer()` / `get_synthesizer()`: return the meta capabilities
- `get_multiple()`: return multiple capabilities by slug list (for multi-capability runs)
- `merge_tools()`: union of tool lists from multiple capabilities (deduped)
- Trigger patterns compiled once at cache refresh, not per-request

### 4b. `orchestrator/capability_router.py` — Capability Router

**Purpose:** Decide which capability set(s) should handle a task.
Two paths: fast (single capability) and delegate (decompose → multi-capability).

```python
"""
Capability Router — selects one or more capabilities for a task.

Fast path (mode=handle): pick best single capability → run directly.
Delegate path (mode=delegate): invoke decomposer → get capability list per sub-task.

Experience-informed: searches past decompositions before routing.
"""

@dataclass
class RoutingPlan:
    """Output of the router — tells Baker what to run."""
    mode: str                          # "fast" or "delegate"
    capabilities: list[CapabilityDef]  # Single item for fast, multiple for delegate
    sub_tasks: list[dict] = None       # For delegate: [{sub_task, capability_slug}, ...]
    experience_context: str = ""       # Past patterns retrieved for decomposer

class CapabilityRouter:
    def __init__(self):
        self.registry = CapabilityRegistry.get_instance()

    def route(self, text: str, domain: str = None, mode: str = None,
              scored: dict = None) -> RoutingPlan:
        """
        Main entry point. Returns a RoutingPlan.

        1. Try explicit trigger match (Director names a capability)
        2. If mode == "handle" → fast path (single best capability)
        3. If mode == "delegate" → delegate path (decompose + multi-capability)
        4. If mode == "escalate" → no capabilities (ask Director)
        5. If nothing matches → fall through (return empty plan, use generic RAG)
        """

    def route_explicit(self, text: str) -> Optional[CapabilityDef]:
        """Regex match: 'have the finance agent analyze...' → finance capability."""

    def route_fast(self, text: str, domain: str,
                   scored: dict = None) -> Optional[CapabilityDef]:
        """
        Pick the single best capability for a simple task.
        Logic:
        1. Get capabilities matching domain
        2. If exactly 1 → use it
        3. If multiple → score keyword overlap with role_description
        4. If none → return None (generic RAG fallback)
        """

    def route_delegate(self, text: str, domain: str,
                       scored: dict = None) -> RoutingPlan:
        """
        Complex task path:
        1. Retrieve similar past tasks from experience_log
        2. Call decomposer capability (Claude call with decomposition prompt)
        3. Decomposer returns: [{sub_task, capability_slug}, ...]
        4. Validate all slugs exist in registry
        5. Return RoutingPlan with sub_tasks and capabilities
        """

    def _retrieve_experience(self, text: str, domain: str) -> str:
        """
        Search decomposition_log for similar past tasks.
        Returns formatted context string for the decomposer.
        Includes: past task → sub-tasks → capabilities used → Director feedback.
        """
```

### 4c. `orchestrator/capability_runner.py` — Capability Runner

**Purpose:** Execute the agent loop with capability-specific configuration.
Extends existing `agent.py` — same ToolExecutor, same Claude API.

```python
"""
Capability Runner — executes an agent loop with capability-specific config.
Reuses ToolExecutor from agent.py but filters tools per capability definition.

Two modes:
  run_single()     — one capability, one task (fast path)
  run_multi()      — multiple capabilities, multiple sub-tasks (delegate path)
  run_streaming()  — SSE streaming variant of run_single
"""

class CapabilityRunner:
    def __init__(self):
        self.executor = ToolExecutor()
        self.claude = anthropic.Anthropic(api_key=config.claude.api_key)

    def run_single(self, capability: CapabilityDef, question: str,
                   history: list = None) -> AgentResult:
        """
        Fast path — one capability, one question.
        Builds system prompt from capability definition.
        Filters tools to capability's tool list.
        Same agent loop structure as run_agent_loop() in agent.py.
        """

    def run_multi(self, plan: RoutingPlan, question: str,
                  history: list = None) -> AgentResult:
        """
        Delegate path — multiple sub-tasks, each with its own capability.
        V1 (sequential):
          for each sub_task in plan.sub_tasks:
            result = run_single(capability, sub_task, accumulated_context)
            accumulated_context += result
          synthesized = run_synthesizer(all_results, original_question)
          return synthesized

        V2 (parallel, future):
          results = asyncio.gather(*[run_single(c, st) for c, st in plan])
          return run_synthesizer(results, original_question)
        """

    def run_synthesizer(self, sub_results: list[AgentResult],
                        original_question: str) -> AgentResult:
        """
        Invoke the synthesizer capability to combine sub-results.
        Input: all sub-task results + the original question.
        Output: one unified deliverable.
        """

    def run_streaming(self, capability: CapabilityDef, question: str,
                      history: list = None) -> Generator[dict, None, AgentResult]:
        """
        SSE streaming variant for Scan dashboard.
        Same structure as run_agent_loop_streaming() in agent.py.
        """

    def _build_system_prompt(self, capability: CapabilityDef,
                              domain: str = None, mode: str = None) -> str:
        """
        Build system prompt for a capability run.
        1. If capability.system_prompt is non-empty → use verbatim
        2. Otherwise → base_prompt + capability role injection
        3. Apply build_mode_aware_prompt() for domain/mode/preferences
        """

    def _get_filtered_tools(self, capability: CapabilityDef) -> list[dict]:
        """
        Filter TOOL_DEFINITIONS to capability's tool list.
        Empty list → all tools (backward compat).
        """

    def _get_merged_tools(self, capabilities: list[CapabilityDef]) -> list[dict]:
        """
        Merge tool lists from multiple capabilities (for decomposer/synthesizer
        that may need broader tool access). Deduped by name.
        """
```

---

## 5. Database Changes

### 5a. New table: `capability_sets` (replaces `specialist_agents`)

```sql
CREATE TABLE IF NOT EXISTS capability_sets (
    id                  SERIAL PRIMARY KEY,
    slug                TEXT NOT NULL UNIQUE,
    name                TEXT NOT NULL,
    capability_type     TEXT NOT NULL DEFAULT 'domain',  -- 'domain' or 'meta'
    domain              TEXT NOT NULL,
    role_description    TEXT NOT NULL,
    system_prompt       TEXT DEFAULT '',
    tools               JSONB DEFAULT '[]'::jsonb,
    output_format       TEXT DEFAULT 'prose',
    autonomy_level      TEXT DEFAULT 'recommend_wait',
    trigger_patterns    JSONB DEFAULT '[]'::jsonb,
    max_iterations      INTEGER DEFAULT 5,
    timeout_seconds     REAL DEFAULT 30.0,
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_capability_sets_slug ON capability_sets(slug);
CREATE INDEX IF NOT EXISTS idx_capability_sets_domain ON capability_sets(domain);
CREATE INDEX IF NOT EXISTS idx_capability_sets_type ON capability_sets(capability_type);
CREATE INDEX IF NOT EXISTS idx_capability_sets_active ON capability_sets(active) WHERE active = TRUE;
```

### 5b. Extend `baker_tasks` table

```sql
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS capability_slugs JSONB DEFAULT '[]'::jsonb;
ALTER TABLE baker_tasks ADD COLUMN IF NOT EXISTS decomposition JSONB;
CREATE INDEX IF NOT EXISTS idx_baker_tasks_capability ON baker_tasks USING gin(capability_slugs);
```

- `capability_slugs`: array of capability slugs used for this task (e.g., `["finance", "legal"]`)
- `decomposition`: the decomposer's output (sub-tasks + capability assignments) — for audit

### 5c. New table: `capability_runs` (observability — per capability invocation)

```sql
CREATE TABLE IF NOT EXISTS capability_runs (
    id                  SERIAL PRIMARY KEY,
    baker_task_id       INTEGER REFERENCES baker_tasks(id),
    capability_slug     TEXT NOT NULL,
    sub_task            TEXT,
    answer              TEXT,
    tools_used          JSONB DEFAULT '[]'::jsonb,
    retrieved_docs      JSONB DEFAULT '[]'::jsonb,  -- what was retrieved (audit trail)
    iterations          INTEGER,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    elapsed_ms          INTEGER,
    status              TEXT NOT NULL DEFAULT 'running',
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_capability_runs_slug ON capability_runs(capability_slug);
CREATE INDEX IF NOT EXISTS idx_capability_runs_task ON capability_runs(baker_task_id);
CREATE INDEX IF NOT EXISTS idx_capability_runs_created ON capability_runs(created_at DESC);
```

Note: `retrieved_docs` stores document IDs / sources that were retrieved during the run.
This is the audit trail for debugging "why did the capability say X."

### 5d. New table: `decomposition_log` (experience-informed retrieval)

```sql
CREATE TABLE IF NOT EXISTS decomposition_log (
    id                  SERIAL PRIMARY KEY,
    baker_task_id       INTEGER REFERENCES baker_tasks(id),
    original_task       TEXT NOT NULL,
    domain              TEXT,
    sub_tasks           JSONB NOT NULL,           -- [{sub_task, capability_slug}, ...]
    capabilities_used   JSONB NOT NULL,           -- ["finance", "legal"]
    director_feedback   TEXT,                     -- "good" / "bad" / specific correction
    feedback_at         TIMESTAMPTZ,
    outcome_quality     TEXT,                     -- "good" / "partial" / "poor" (set by feedback)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decomp_log_created ON decomposition_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_decomp_log_domain ON decomposition_log(domain);
```

This table is what enables the decomposer to "learn" — before decomposing a new task,
Baker searches this table for similar past tasks and injects the results as context.

### 5e. Table creation

Add `_ensure_capability_sets_table()`, `_ensure_capability_runs_table()`, and
`_ensure_decomposition_log_table()` to `SentinelStoreBack.__init__()`, following
the same pattern as `_ensure_baker_tasks_table()`.

---

## 6. Experience-Informed Retrieval — The "Learning" Layer

Three mechanisms, built incrementally. These are what make the decomposer improve over time.

### Mechanism 1: Experience Log + Retrieval (build in v1)

Every time the delegate path runs, the decomposition is logged:
- What task came in
- How it was decomposed (sub-tasks + capabilities)
- What results were produced
- Whether Director was satisfied (feedback)

Before the next decomposition, `CapabilityRouter._retrieve_experience()` searches
this log for similar past tasks (keyword match on original_task + domain filter).
The decomposer receives these as few-shot context:

```
## PAST DECOMPOSITION PATTERNS
Task: "Full status update on Hagenauer" (domain: projects)
→ Sub-tasks: legal claims + asset_mgmt timeline + email search
→ Capabilities: legal, asset_mgmt, comms
→ Director feedback: good

Task: "Analyze the Vienna loan options" (domain: chairman)
→ Sub-tasks: single task, no decomposition needed
→ Capabilities: finance
→ Director feedback: good — don't decompose simple finance questions
```

### Mechanism 2: Director Feedback Loop (build in v1)

The existing `director_feedback` field in `baker_tasks` already captures corrections.
New: when Director gives feedback on a decomposed task, it propagates to `decomposition_log`:

```python
# In update_baker_task, when director_feedback is set:
if task.decomposition:
    update decomposition_log SET director_feedback = ..., outcome_quality = ...
    WHERE baker_task_id = task.id
```

This creates a correction dataset. The decomposer learns: "When Director says X,
this decomposition pattern was wrong/right."

### Mechanism 3: Curated Prompt Evolution (manual, ongoing)

Monthly (or as needed), review decomposition_log for patterns. Update the
decomposer's system_prompt in the capability_sets table with better few-shot
examples. This is done via the MCP tool `baker_upsert_capability` — no code deploy.

---

## 7. Seed Data — 12 Capability Sets (10 domain + 2 meta)

```sql
-- META capabilities (decomposer + synthesizer)
INSERT INTO capability_sets (slug, name, capability_type, domain, role_description, system_prompt, tools, output_format, autonomy_level, max_iterations, timeout_seconds) VALUES
('decomposer', 'Task Decomposer', 'meta', 'meta',
 'Analyzes incoming tasks and breaks them into independent sub-issues. For each sub-issue, identifies which capability set should handle it. Returns a structured decomposition plan.',
 E'You are Baker''s task decomposer. Given a complex task, break it into independent sub-issues.\n\nFor each sub-issue, specify:\n1. A clear, self-contained sub-task description\n2. The capability_slug that should handle it\n\nAvailable capability slugs: sales, finance, legal, asset_mgmt, research, comms, it, ib, marketing, ai_dev\n\nRules:\n- If the task is simple (single domain, single question), return it as ONE sub-task with ONE capability. Do NOT over-decompose.\n- Only decompose when the task genuinely spans multiple domains or requires multiple independent analyses.\n- Each sub-task must be self-contained — the capability handling it should be able to work without seeing other sub-tasks'' results.\n\nReturn JSON array: [{"sub_task": "...", "capability_slug": "..."}]\n\n## PAST PATTERNS\n{experience_context}',
 '[]'::jsonb, 'json', 'auto_execute', 1, 15.0),

('synthesizer', 'Result Synthesizer', 'meta', 'meta',
 'Combines results from multiple capability runs into one coherent, unified deliverable for the Director. Resolves contradictions, removes redundancy, and presents in the Director''s preferred style.',
 E'You are Baker''s result synthesizer. You receive results from multiple capability runs that analyzed different aspects of the Director''s task.\n\nYour job:\n1. Combine all results into ONE coherent answer\n2. Resolve any contradictions between results (flag if unresolvable)\n3. Remove redundancy\n4. Structure the output: bottom-line first, then supporting detail per domain\n5. Cite which capability produced each finding\n\nThe Director expects: warm but direct, like a trusted advisor. Bottom-line first.',
 '[]'::jsonb, 'prose', 'auto_execute', 1, 15.0)
ON CONFLICT (slug) DO NOTHING;

-- DOMAIN capabilities (10 specialist areas)
INSERT INTO capability_sets (slug, name, capability_type, domain, role_description, tools, trigger_patterns, output_format, autonomy_level) VALUES
('sales',       'Sales Capability',              'domain', 'projects',
 'MO Residences sales — pitch decks, buyer follow-ups, market comparisons, unit availability, pricing analysis, broker relationships.',
 '["search_memory", "search_emails", "search_whatsapp", "get_contact", "get_matter_context", "search_deals_insights"]'::jsonb,
 '["\\b(sales|pitch|buyer|unit|MO\\s?residences|pricing|apartment|penthouse|broker)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('finance',     'Finance Capability',             'domain', 'chairman',
 'Loan analysis, LP term sheets, cash flow models, investment returns, fund economics, capital allocation, treasury, bank communication.',
 '["search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "get_deadlines"]'::jsonb,
 '["\\b(finance|loan|term.?sheet|cash.?flow|LP|fund|capital|IRR|yield|interest|bank)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('legal',       'Legal/Claims Capability',        'domain', 'projects',
 'Dispute analysis, construction claim tracking, deadline monitoring, evidence review, Gewaehrleistung, contract interpretation, Austrian law context.',
 '["search_memory", "search_emails", "search_whatsapp", "search_meetings", "get_contact", "get_matter_context", "get_deadlines", "get_clickup_tasks"]'::jsonb,
 '["\\b(legal|claim|dispute|contract|lawsuit|evidence|Gew.hrleistung|arbitration|deadline|court)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('asset_mgmt',  'Asset Management Capability',    'domain', 'projects',
 'Hotel KPI reporting, operational benchmarks, occupancy analysis, RevPAR tracking, property performance, MO Vienna operations.',
 '["search_memory", "search_emails", "search_meetings", "get_matter_context", "search_deals_insights"]'::jsonb,
 '["\\b(hotel|KPI|RevPAR|occupancy|benchmark|asset.?management|property.?performance|ADR|GOP)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('research',    'Research Capability',            'domain', 'network',
 'Market intelligence, competitor analysis, due diligence, industry trends, market sizing, investment thesis validation.',
 '["search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights"]'::jsonb,
 '["\\b(research|market.?intelligence|competitor|due.?diligence|industry|trend|benchmark)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('comms',       'Communications Capability',      'domain', 'chairman',
 'Email drafts, presentation outlines, board memos, stakeholder communication, press releases — in the Director''s voice and style.',
 '["search_memory", "search_emails", "search_whatsapp", "get_contact", "get_matter_context"]'::jsonb,
 '["\\b(draft|memo|presentation|board.?memo|communication|stakeholder|press.?release|letter)\\b"]'::jsonb,
 'email_draft', 'recommend_wait'),

('it',          'IT Infrastructure Capability',   'domain', 'projects',
 'M365 migration, Entra ID, Conditional Access, Defender, BYOD security architecture, hardware specs, vendor management (BCOMM/EVOK), troubleshooting, Graph API, SharePoint/OneDrive, cybersecurity triage.',
 '["search_memory", "search_emails", "search_whatsapp", "search_meetings", "get_contact", "get_matter_context", "get_clickup_tasks", "get_deadlines"]'::jsonb,
 '["\\b(IT|M365|Azure|migration|infrastructure|security|Microsoft|tenant|SharePoint|BCOMM|EVOK|Entra|Defender|laptop|printer|VPN|hardware|software)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('ib',          'Investment Banking Capability',  'domain', 'chairman',
 'Raising finance, project economics analysis, investor relations, placement memoranda, co-investment structuring, LP communication, deal flow.',
 '["search_memory", "search_emails", "search_meetings", "get_contact", "get_matter_context", "search_deals_insights", "get_deadlines"]'::jsonb,
 '["\\b(invest(?:ment|or)|placement|fundrais|LP.?relation|co.?invest|placement.?memo|capital.?raise|deal.?flow)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('marketing',   'Marketing & PR Capability',      'domain', 'network',
 'Social media strategy, advertising campaigns, promotional materials, marketing collaterals, brand management, PR outreach.',
 '["search_memory", "search_emails", "get_contact", "get_matter_context"]'::jsonb,
 '["\\b(marketing|PR|social.?media|campaign|brand|promotion|advertis|collateral)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait'),

('ai_dev',      'AI Development Capability',      'domain', 'projects',
 'Baker system development — architecture decisions, feature planning, bug analysis, codebase context, deployment strategy.',
 '["search_memory", "search_emails", "search_meetings", "get_clickup_tasks", "get_matter_context"]'::jsonb,
 '["\\b(Baker|Sentinel|AI.?development|agent.?framework|pipeline|RAG|MCP|Render)\\b"]'::jsonb,
 'analysis_report', 'recommend_wait')
ON CONFLICT (slug) DO NOTHING;
```

---

## 8. Integration Points (Modify Existing Files)

### 8a. `orchestrator/action_handler.py` — New intent type

Add `capability_task` to classify_intent():

```python
# In classify_intent(), add regex fast-path BEFORE Haiku:
def _quick_capability_detect(question: str) -> Optional[dict]:
    """Detect explicit capability invocations like 'have the finance agent analyze...'"""
    import re
    pattern = re.compile(
        r"\b(?:have|ask|tell|get|use)\s+(?:the\s+)?(\w+)\s+agent\b",
        re.IGNORECASE,
    )
    match = pattern.search(question)
    if match:
        capability_hint = match.group(1).lower()
        return {"type": "capability_task", "capability_hint": capability_hint}
    return None
```

### 8b. `outputs/dashboard.py` — Route capability tasks

In `scan_chat()`, after existing intent routing:

```python
elif intent.get("type") == "capability_task":
    return _scan_chat_capability(req, start, intent,
                                  task_id=_task_id, domain=_domain)
```

New function `_scan_chat_capability()`:
1. Loads CapabilityDef via `CapabilityRouter.route()`
2. If routing plan is "fast" → `CapabilityRunner.run_streaming(single capability)`
3. If routing plan is "delegate" → `CapabilityRunner.run_multi(plan)` then stream result
4. Stores `capability_slugs` in baker_tasks
5. Streams `{"capabilities": ["finance", "legal"]}` SSE event for frontend
6. Logs to `capability_runs` table on completion

If no capability matches → fall through to normal agentic path (backward compat).

### 8c. `outputs/dashboard.py` — Implicit routing in RAG path

In the existing tier/mode routing block:

```python
from orchestrator.capability_router import CapabilityRouter
_cap_router = CapabilityRouter()
_plan = _cap_router.route(req.question, _domain, _mode, _scored)

if _plan and _plan.capabilities:
    return _scan_chat_capability(req, start, {"plan": _plan},
                                  task_id=_task_id, domain=_domain)
# else: existing routing (legacy / generic agentic)
```

### 8d. `triggers/waha_webhook.py` — Capability routing for WhatsApp

Same logic in `_handle_director_question()`, using blocking `CapabilityRunner.run_single()`
or `CapabilityRunner.run_multi()`.

### 8e. `baker_tasks` updates

In `create_baker_task()` and `update_baker_task()`:
- Add `capability_slugs` and `decomposition` to the field whitelist
- Log which capabilities were used and how the task was decomposed

---

## 9. MCP Server Extension

Add to Baker MCP server (`baker_mcp_server.py`):

1. **`baker_upsert_capability`** — Insert or update a capability definition.
   Uses `INSERT ... ON CONFLICT (slug) DO UPDATE`.

2. **`baker_get_capabilities`** — List all capability sets (active only by default).

3. **`baker_get_decomposition_log`** — View recent decompositions with feedback.
   Used by PM/Director to review how the decomposer is performing.

---

## 10. API Endpoints

### 10a. `GET /api/capabilities` — List capability sets
Returns all active capabilities with slug, name, domain, type, and status.

### 10b. `GET /api/capability-runs` — Run history
Returns recent capability_runs. Optional filters: `?capability=finance&limit=20`.

### 10c. `GET /api/decompositions` — Decomposition history
Returns recent decomposition_log entries with feedback status. For observability.

### 10d. `POST /api/scan` — No endpoint change
New SSE events: `{"capabilities": ["finance", "legal"]}` and `{"phase": "decomposing"}` / `{"phase": "synthesizing"}`.

---

## 11. Implementation Order

### Step 1: Database + Registry (no behavior change)
1. Create `capability_sets` table in store_back.py `_ensure_*`
2. Create `capability_runs` table
3. Create `decomposition_log` table
4. Add `capability_slugs` + `decomposition` columns to `baker_tasks`
5. Create `orchestrator/capability_registry.py` with `CapabilityRegistry`
6. Insert seed data (12 capabilities: 10 domain + 2 meta)
7. Test: `CapabilityRegistry.get_instance().get_all_active()` returns 12

### Step 2: Router — Fast Path Only (single capability)
1. Create `orchestrator/capability_router.py` with `CapabilityRouter`
2. Implement `route_explicit()` and `route_fast()` only (NO decomposer yet)
3. Add `_quick_capability_detect()` regex to action_handler.py
4. Test: `CapabilityRouter().route("have the finance agent analyze X")` → finance
5. Test: `CapabilityRouter().route("what's the weather?")` → None

### Step 3: Capability Runner — Single Mode
1. Create `orchestrator/capability_runner.py` with `CapabilityRunner`
2. Implement `run_single()` (blocking) — reuse ToolExecutor, filter tools, custom prompt
3. Implement `run_streaming()` (SSE)
4. Test: `CapabilityRunner().run_single(finance_cap, "analyze the Vienna loan")` works
5. This is equivalent to the old SpecialistAgentRunner — same behavior, new name

### Step 4: Integration — Dashboard + WhatsApp (fast path)
1. Add `capability_task` intent routing in `scan_chat()`
2. Add `_scan_chat_capability()` function (fast path: single capability)
3. Add implicit routing (mode=handle/delegate with single capability match)
4. WhatsApp: add routing in `_handle_director_question()`
5. Log to `capability_runs` table
6. Test end-to-end: "Baker, have the IT agent review the BCOMM situation"

### Step 5: Delegate Path — Decomposer + Multi-Capability + Synthesizer
1. Implement `route_delegate()` in CapabilityRouter — calls decomposer capability
2. Implement `run_multi()` in CapabilityRunner — sequential sub-task execution
3. Implement `run_synthesizer()` — combines results
4. Log decompositions to `decomposition_log` table
5. Test: "Full status update on Hagenauer" → decomposes into legal + asset_mgmt + email search
6. Test: Simple question still takes fast path (no unnecessary decomposition)

### Step 6: Experience Layer
1. Implement `_retrieve_experience()` — search decomposition_log for past patterns
2. Inject experience context into decomposer's system prompt
3. Implement Director feedback propagation to decomposition_log
4. Test: After giving feedback on a decomposition, similar tasks use the improved pattern

### Step 7: Observability + MCP
1. Add MCP tools: `baker_upsert_capability`, `baker_get_capabilities`, `baker_get_decomposition_log`
2. Add API endpoints: `/api/capabilities`, `/api/capability-runs`, `/api/decompositions`
3. Frontend: capability indicators (optional)

---

## 12. What NOT to Build (Scope Guard)

- **No parallel execution in v1.** Sub-tasks run sequentially. Parallel = v2 optimization.
- **No new tools.** Capabilities use existing 9 tools. Web search, calendar, doc reader = separate tickets.
- **No proactive triggering.** Capabilities are invoked from Scan and WhatsApp only. Proactive = Phase 3.
- **No per-capability model selection.** All use `config.claude.model` (Opus).
- **No cost caps per capability.** Tokens are tracked but not limited. Cost Monitor = Step 4.
- **No cross-task state.** Each capability run is ephemeral. No persistent "agent sessions."

---

## 13. Safety Invariants

1. **No new ClickUp write surface.** Capabilities use existing tools — same BAKER-space-only guard.
2. **No autonomous email sending.** Autonomy_level governs capability output, not external actions. Email always goes through draft→confirm flow.
3. **Timeout enforced.** CapabilityRunner respects `capability.timeout_seconds`. Exceeded → partial result, log status=timed_out.
4. **Decomposer bounded.** Decomposer limited to max 4 sub-tasks per decomposition. Prevents runaway.
5. **Graceful degradation.** If capability_sets table missing, DB down, or no capability matches → fall through to existing generic RAG. Zero regression.
6. **Experience retrieval is additive.** If decomposition_log is empty → decomposer works without experience context. No dependency on past data.

---

## 14. Testing Checklist

- [ ] `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_registry.py', doraise=True)"`
- [ ] `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_router.py', doraise=True)"`
- [ ] `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"`
- [ ] `python3 -c "import py_compile; py_compile.compile('orchestrator/action_handler.py', doraise=True)"`
- [ ] `python3 -c "import py_compile; py_compile.compile('outputs/dashboard.py', doraise=True)"`
- [ ] `python3 -c "import py_compile; py_compile.compile('triggers/waha_webhook.py', doraise=True)"`
- [ ] `python3 -c "import py_compile; py_compile.compile('memory/store_back.py', doraise=True)"`
- [ ] All existing imports still work (no circular imports)
- [ ] Existing scan flow (no capabilities defined) works exactly the same
- [ ] Fast path: explicit "have the X agent" → single capability, no decomposer
- [ ] Fast path: mode=handle + domain match → single capability, no decomposer
- [ ] Delegate path: mode=delegate → decomposer fires, produces sub-tasks
- [ ] Delegate path: simple question in delegate mode → decomposer returns single sub-task (no over-decomposition)
- [ ] Synthesizer produces coherent output from 2+ sub-results
- [ ] CapabilityRegistry gracefully returns empty list if table doesn't exist
- [ ] CapabilityRunner falls back to all tools if capability.tools is empty
- [ ] decomposition_log gets populated on every delegate path run
- [ ] Director feedback on baker_tasks propagates to decomposition_log

---

## 15. Code Brisen — Opening Prompt

```
Read CLAUDE.md. Read briefs/BRIEF_AGENT_FRAMEWORK_1.md.
This is a capability-based agent framework, NOT fixed agents.
Key concepts: capability sets, decomposer, synthesizer, experience-informed retrieval.
Implement Steps 1-7 in order.
Commit locally after each step. Do NOT push.
Each commit message: "feat: AGENT-FRAMEWORK-1 step N — [description]"
```

---

## 16. Architect Review Checklist (Code 300)

After Code Brisen commits, Code 300 reviews against:

- [ ] No duplication with agent.py — CapabilityRunner CALLS or WRAPS, doesn't copy
- [ ] CapabilityRegistry uses connection pool (store._get_conn / _put_conn)
- [ ] Trigger patterns compile once at cache refresh, not per-request
- [ ] `_quick_capability_detect()` doesn't conflict with existing regex detectors
- [ ] `_scan_chat_capability()` reuses SSE Queue bridge pattern from `_scan_chat_agentic()`
- [ ] capability_runs INSERT is inside try/except (non-fatal)
- [ ] decomposition_log INSERT is inside try/except (non-fatal)
- [ ] Decomposer prompt includes `{experience_context}` placeholder that gets filled
- [ ] Decomposer bounded: max 4 sub-tasks enforced in code, not just in prompt
- [ ] Synthesizer handles edge case: only 1 sub-result → pass through without re-processing
- [ ] All new files have module docstring
- [ ] No new env vars required (all config from DB)
- [ ] Backward compatible — zero behavior change when capability_sets table is empty
- [ ] Experience retrieval returns empty string (not error) when decomposition_log is empty

---

## 17. Reference: IT Capability — Full Specification

The IT capability is the first to be fully specified (PM + Director session, 2026-03-06).
Full spec available in: PM deliverable `it-agent-specification.md`

Key points for implementation:
- **Role:** M365 migration + hardware/software + operational IT support + cybersecurity triage
- **Tools:** All 8 retrieval tools + get_deadlines (broadest tool set of all capabilities)
- **Trigger patterns:** IT, M365, Azure, migration, Microsoft, BCOMM, EVOK, hardware, software, laptop, printer, VPN
- **Autonomy:** recommend_wait for all external actions. auto_execute for: memory updates, ClickUp task creation, security triage (low/medium), weekly digest
- **Proactive triggers (Phase 3):** BCOMM email auto-parse, Defender alert triage, vendor renewal flags, weekly Monday digest
- **Human counterpart:** Dennis Egorenkov (IT Administrator) — Dennis executes, capability analyzes and prepares

This capability definition should be used as the test case for Steps 4-6 of the implementation.
