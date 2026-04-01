# BRIEF: GEMINI_MIG_B_CORE_AGENTS — Migrate 3 Haiku sites in agent.py, capability_runner.py, pipeline.py

## Context
Part 2 of the Gemini migration redo. Brief A (action_handler.py, 5 sites) is deployed and verified. This brief covers the remaining Haiku sites in the core agent/pipeline files. All Opus agent loop sites in these files MUST remain untouched.

**Lesson #13**: One file at a time. Client ↔ model ↔ response pattern must be consistent.

## Estimated time: ~30min
## Complexity: Low-Medium
## Prerequisites: Brief A deployed (commit e55ddf8)
## Parallel-safe: Yes — no overlap with Brief A or C files

---

## Site 1: `agent.py` — `ToolExecutor._query_baker_data()` (line ~1198)

### Current State (lines 1204-1233):
```python
        # Use Haiku to generate a safe SELECT query
        import anthropic
        try:
            client = anthropic.Anthropic(api_key=config.claude.api_key)
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=500,
                system=(
                    "Generate a PostgreSQL SELECT query to answer the user's question about Baker's data. "
                    "ONLY SELECT — no mutations. Available tables:\n"
                    "- alerts (id, tier, title, status, source, matter_slug, created_at)\n"
                    "- deadlines (id, description, due_date, status, priority, confidence, severity, source_type)\n"
                    "- vip_contacts (id, name, email, tier, domain, last_contact_date)\n"
                    "- contact_interactions (id, contact_id, interaction_type, subject, interaction_date)\n"
                    "- email_messages (id, subject, sender, created_at)\n"
                    "- whatsapp_messages (id, sender_name, body, timestamp, is_director)\n"
                    "- matter_registry (matter_name, status, keywords, people)\n"
                    "- baker_tasks (id, title, capability_slug, status, created_at)\n"
                    "- documents (id, filename, doc_type, matter_slug, created_at)\n"
                    "- sent_emails (id, to_address, subject, created_at, replied_at)\n\n"
                    "Return ONLY the SQL query, nothing else. Always include LIMIT (max 20)."
                ),
                messages=[{"role": "user", "content": question}],
            )
            try:
                from orchestrator.cost_monitor import log_api_cost
                log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="query_baker_data")
            except Exception:
                pass
            sql = resp.content[0].text.strip()
```

### Replace with:
```python
        # Use Gemini Flash to generate a safe SELECT query
        try:
            from orchestrator.gemini_client import call_flash
            _sql_system = (
                "Generate a PostgreSQL SELECT query to answer the user's question about Baker's data. "
                "ONLY SELECT — no mutations. Available tables:\n"
                "- alerts (id, tier, title, status, source, matter_slug, created_at)\n"
                "- deadlines (id, description, due_date, status, priority, confidence, severity, source_type)\n"
                "- vip_contacts (id, name, email, tier, domain, last_contact_date)\n"
                "- contact_interactions (id, contact_id, interaction_type, subject, interaction_date)\n"
                "- email_messages (id, subject, sender, created_at)\n"
                "- whatsapp_messages (id, sender_name, body, timestamp, is_director)\n"
                "- matter_registry (matter_name, status, keywords, people)\n"
                "- baker_tasks (id, title, capability_slug, status, created_at)\n"
                "- documents (id, filename, doc_type, matter_slug, created_at)\n"
                "- sent_emails (id, to_address, subject, created_at, replied_at)\n\n"
                "Return ONLY the SQL query, nothing else. Always include LIMIT (max 20)."
            )
            resp = call_flash(
                messages=[{"role": "user", "content": question}],
                max_tokens=500,
                system=_sql_system,
            )
            try:
                from orchestrator.cost_monitor import log_api_cost
                log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="query_baker_data")
            except Exception:
                pass
            sql = resp.text.strip()
```

### Key Constraints
- Remove the `import anthropic` on line 1205 (it's a LOCAL import inside this method — the module-level `import anthropic` at the top of agent.py is still needed for the Opus agent loops)
- The system prompt is inline — extract it to a local variable `_sql_system` for readability
- `resp.text` not `resp.content[0].text`
- Everything after `sql = resp.text.strip()` stays unchanged (markdown stripping, safety check, SQL execution)

### Verification
Dashboard → Ask Baker → "How many active deadlines do I have?" → should return a number, not an error.

---

## Site 2: `capability_runner.py` — `_auto_extract_insights()` (line ~915)

### Current State (lines 915-936):
```python
            _HAIKU = "claude-haiku-4-5-20251001"
            prompt = (
                "Extract 1-3 key factual findings from this specialist response. "
                "Only extract concrete facts: amounts, dates, legal positions, decisions, deadlines. "
                "Skip opinions, hedging, generic statements. "
                "Return JSON array: [{\"content\": \"...\", \"matter_slug\": \"...\"|null, "
                "\"confidence\": \"high\"|\"medium\"|\"low\"}]. "
                "Return empty array [] if no concrete findings.\n\n"
                f"Question: {question[:500]}\n\nResponse:\n{answer[:4000]}"
            )

            resp = self.claude.messages.create(
                model=_HAIKU,
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            self._log_api_cost(
                _HAIKU, resp.usage.input_tokens, resp.usage.output_tokens,
                source="auto_insight", capability_id=capability.slug,
            )

            raw = resp.content[0].text.strip()
```

### Replace with:
```python
            from orchestrator.gemini_client import call_flash
            _insight_system = (
                "Extract 1-3 key factual findings from this specialist response. "
                "Only extract concrete facts: amounts, dates, legal positions, decisions, deadlines. "
                "Skip opinions, hedging, generic statements. "
                "Return JSON array: [{\"content\": \"...\", \"matter_slug\": \"...\"|null, "
                "\"confidence\": \"high\"|\"medium\"|\"low\"}]. "
                "Return empty array [] if no concrete findings."
            )
            _insight_content = f"Question: {question[:500]}\n\nResponse:\n{answer[:4000]}"

            resp = call_flash(
                messages=[{"role": "user", "content": _insight_content}],
                max_tokens=500,
                system=_insight_system,
            )
            self._log_api_cost(
                "gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens,
                source="auto_insight", capability_id=capability.slug,
            )

            raw = resp.text.strip()
```

### Key Constraints
- The original had NO system prompt — it was all in the user message. For cleanliness and to match the migration pattern, split the instruction part into `system=` and the data into the user message.
- `self.claude` is NOT used here after migration — but **do NOT remove `self.claude` from `__init__`**. It's needed by `run_single()` (line 258) and `run_streaming()` (line 466).
- `self._log_api_cost` (class method) stays — just change the model string.
- Everything after `raw = resp.text.strip()` (JSON parsing, DB insert) stays unchanged.

### Verification
This runs automatically after specialist queries. Verify by: Dashboard → Ask Specialist → Ask any question → Check that no error appears. Also check Render logs for `auto_insight` entries.

---

## Site 3: `pipeline.py` — `_generate_structured_actions()` (line ~298)

### Current State (lines 298-328):
```python
def _generate_structured_actions(claude_client, title: str, body: str, tier: int) -> dict:
    """Generate structured actions JSON for an alert using Haiku (fast + cheap)."""
    try:
        resp = claude_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2048,
            system=_STRUCTURED_ACTIONS_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Alert (Tier {tier}): {title}\n\n{body}",
            }],
        )
        # PHASE-4A: Log Haiku cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="structured_actions")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace function signature AND body:
```python
def _generate_structured_actions(claude_client, title: str, body: str, tier: int) -> dict:
    """Generate structured actions JSON for an alert using Gemini Flash (fast + cheap)."""
    try:
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{
                "role": "user",
                "content": f"Alert (Tier {tier}): {title}\n\n{body}",
            }],
            max_tokens=2048,
            system=_STRUCTURED_ACTIONS_PROMPT,
        )
        # PHASE-4A: Log Flash cost
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="structured_actions")
        except Exception:
            pass
        raw = resp.text.strip()
```

### Key Constraints
- **Keep `claude_client` parameter** in the function signature even though it's no longer used. This avoids changing the caller at line 637 (`_generate_structured_actions(self.claude, ...)`). The param is simply ignored. This is the safest approach — zero caller changes needed.
- `_STRUCTURED_ACTIONS_PROMPT` is a module-level variable (line ~268). Pass as `system=`.
- `self.claude` in `SentinelPipeline.__init__` (line 388) MUST stay — it's used by `_call_llm()` at line 514 for Opus calls.
- Everything after `raw = resp.text.strip()` (JSON parsing, validation) stays unchanged.

### Verification
This runs during alert ingestion (pipeline processing). To test: check Render logs after next email/WhatsApp trigger fires. Look for `structured_actions` in cost logs. Or: manually trigger via Baker Data → check that new alerts have `structured_actions` populated.

---

## Files Modified
- `orchestrator/agent.py` — `_query_baker_data()`: Haiku → Flash
- `orchestrator/capability_runner.py` — `_auto_extract_insights()`: Haiku → Flash
- `orchestrator/pipeline.py` — `_generate_structured_actions()`: Haiku → Flash

## Do NOT Touch
- `orchestrator/agent.py` — `run_agent_loop()`, `run_agent_loop_streaming()`, `_force_synthesis()` (Opus)
- `orchestrator/capability_runner.py` — `__init__()` self.claude, `run_single()`, `run_streaming()` (Opus)
- `orchestrator/pipeline.py` — `__init__()` self.claude, `_call_llm()` (Opus)
- `orchestrator/action_handler.py` — already migrated (Brief A)
- All other files — separate brief (Brief C)

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/agent.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('orchestrator/capability_runner.py', doraise=True)"`
3. `python3 -c "import py_compile; py_compile.compile('orchestrator/pipeline.py', doraise=True)"`
4. Dashboard → Ask Baker → "How many alerts this week?" → should return data (tests `_query_baker_data`)
5. Dashboard → Ask Specialist → any question → should stream response without error (tests `_auto_extract_insights` post-processing)
6. Check Render logs for `structured_actions` cost entries showing `gemini-2.5-flash` (tests `_generate_structured_actions`)
7. Verify `self.claude` still exists in both `CapabilityRunner.__init__` and `SentinelPipeline.__init__`
8. Commit message must include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

## Cost Impact
- 3 sites migrated: SQL generation, insight extraction, structured actions
- Structured actions is highest volume (~50-100/day × 2K tokens)
- Estimated monthly savings: ~$5-8
