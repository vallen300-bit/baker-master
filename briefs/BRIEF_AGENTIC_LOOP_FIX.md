# BRIEF: AGENTIC-LOOP-FIX — Baker agent loop fails to produce final synthesis

## Problem
When users ask Baker complex questions via Ask Baker / Ask Specialist, the agentic loop:
1. Starts correctly — classifies intent, enters agent loop
2. Runs research steps — searches emails, WhatsApp, documents, contacts (visible as "Let me search..." messages)
3. **Fails to produce a final synthesis** — the deliverable stored in `baker_tasks` is just the intermediate status messages, not the actual analysis

The user sees Baker "thinking" with status updates, then gets suggested follow-up buttons but no actual answer.

## Evidence
- `baker_tasks` ID 216: Campus Schlüterstrasse query
  - Duration: 98 seconds
  - Status: "completed"
  - Deliverable: Only contains agent status messages ("I'll run a comprehensive analysis...", "Let me dig deeper...") — no final answer
- `conversation_memory` ID 294: Same query, answer_length = 676 chars (just status messages)
- The same query was attempted twice with the same result

## Where to Investigate

### 1. `orchestrator/agent.py`
- The agent loop runs tools and streams intermediate results
- Check: after all tool iterations complete, does it make a final Claude API call to synthesize?
- Check: is there a timeout that kills the loop before the synthesis call?
- `BAKER_AGENT_TIMEOUT` env var (default: 10s) — 98 seconds suggests this isn't the issue, but verify

### 2. `orchestrator/pipeline.py` — `_scan_chat_agentic()`
- This calls the agent loop and streams results via SSE
- Check: does it stream the final answer or only the intermediate tool results?
- Check: if the agent loop returns, does the final message get yielded to SSE?

### 3. SSE streaming in `outputs/dashboard.py` — `scan_chat()`
- The SSE endpoint streams responses back to the browser
- Check: does the connection drop before the final chunk?
- Check: is there a proxy timeout (Render has a 60s default for streaming)?

### 4. `orchestrator/scan_prompt.py`
- The system prompt tells the agent what to do
- Check: does it instruct the agent to produce a final synthesis after research?

## Likely Root Causes (ranked)

1. **Render proxy timeout** — Render's default streaming timeout may kill long-running SSE connections. 98 seconds is well beyond typical proxy timeouts. The research completes server-side but the SSE connection to the browser is already dead.

2. **Missing final synthesis step** — The agent loop runs tools but the final "now synthesize everything" Claude call may not happen or its output may not be captured.

3. **Deliverable assembly** — The code that assembles the deliverable for `baker_tasks` may only capture streamed chunks (the status messages) but miss the final answer.

## How to Fix

### Quick fix: Increase Render streaming timeout
Check if Render has a request timeout setting. For SSE endpoints, it may need to be extended to 120+ seconds.

### Proper fix: Ensure final synthesis
In `orchestrator/agent.py`, after the tool loop completes:
1. Make one final Claude API call with all gathered context
2. Stream that response as the final SSE chunk
3. Store the complete response (not just intermediate messages) as the deliverable

### Verification
- [ ] Ask Baker: "Analyze the Campus Schlüterstrasse situation in depth"
- [ ] Baker should show status messages THEN a full analysis
- [ ] `baker_tasks` deliverable should contain the full analysis text
- [ ] `conversation_memory` answer should be the full analysis

## Files
- `orchestrator/agent.py` — agent loop logic
- `orchestrator/pipeline.py` — `_scan_chat_agentic()`
- `outputs/dashboard.py` — `scan_chat()` SSE endpoint
- `orchestrator/scan_prompt.py` — agent system prompt

## Rules
- Read `tasks/lessons.md` before starting
- This is a diagnosis-first task — understand the flow before changing code
- Add console logging to trace where the final answer gets lost
- Test with a real complex query on the live dashboard after fix
