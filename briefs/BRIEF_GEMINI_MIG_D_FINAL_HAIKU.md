# BRIEF: GEMINI_MIG_D_FINAL_HAIKU — Migrate last 2 Haiku sites in deadline_manager.py and chain_runner.py

## Context
Final brief in the Haiku→Flash migration. Briefs A (5 sites), B (3 sites), C (7 sites) are deployed. This brief covers the last 2 Haiku call sites in the entire codebase. After this, `grep -rn "claude-haiku" orchestrator/` should return only `cost_monitor.py` (price lookup table — correct, not a call site).

## Estimated time: ~15min
## Complexity: Low
## Prerequisites: Briefs A+B+C deployed
## Parallel-safe: Yes — no overlap with any other brief

---

## Site 1: `deadline_manager.py` — `_generate_deadline_proposal()` (line ~355)

### Current State (lines 355-367):
```python
        claude = anthropic.Anthropic(api_key=config.claude.api_key)
        resp = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            system=_DEADLINE_PROPOSAL_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens, resp.usage.output_tokens, source="deadline_proposal")
        except Exception:
            pass
        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        resp = call_flash(
            messages=[{"role": "user", "content": context}],
            max_tokens=1500,
            system=_DEADLINE_PROPOSAL_PROMPT,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens, resp.usage.output_tokens, source="deadline_proposal")
        except Exception:
            pass
        raw = resp.text.strip()
```

### Key Constraints
- `_DEADLINE_PROPOSAL_PROMPT` is a module-level variable (line 307). Pass as `system=`.
- Remove `claude = anthropic.Anthropic(...)` line.
- **Remove `import anthropic` at line 20** — no other Anthropic usage remains in this file. (The extraction function at line 74 already uses `call_flash` from Brief C wave 1 migration.)
- Everything after `raw = resp.text.strip()` (JSON parsing, validation) stays unchanged.

### Verification
This runs during the deadline cadence (daily). Check Render logs for `deadline_proposal` cost entries showing `gemini-2.5-flash`.

---

## Site 2: `chain_runner.py` — `_adapt_write_steps()` (line ~372)

### Current State (lines 372-392):
```python
        client = anthropic.Anthropic(api_key=config.claude.api_key)
        adapt_prompt = (
            "Based on the information gathered below, refine the write action inputs. "
            "Return ONLY a JSON array of updated write steps with the same structure.\n\n"
            f"Original assessment: {plan.get('assessment', '')}\n\n"
            f"Gathered context:\n{context[:3000]}\n\n"
            f"Write steps to refine:\n{json.dumps(write_steps, indent=2)}"
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": adapt_prompt}],
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("claude-haiku-4-5-20251001", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="chain_adapt")
        except Exception:
            pass

        raw = resp.content[0].text.strip()
```

### Replace with:
```python
        from orchestrator.gemini_client import call_flash
        adapt_prompt = (
            "Based on the information gathered below, refine the write action inputs. "
            "Return ONLY a JSON array of updated write steps with the same structure.\n\n"
            f"Original assessment: {plan.get('assessment', '')}\n\n"
            f"Gathered context:\n{context[:3000]}\n\n"
            f"Write steps to refine:\n{json.dumps(write_steps, indent=2)}"
        )
        resp = call_flash(
            messages=[{"role": "user", "content": adapt_prompt}],
            max_tokens=1024,
        )
        try:
            from orchestrator.cost_monitor import log_api_cost
            log_api_cost("gemini-2.5-flash", resp.usage.input_tokens,
                         resp.usage.output_tokens, source="chain_adapt")
        except Exception:
            pass

        raw = resp.text.strip()
```

### Key Constraints
- NO `system=` param — the prompt is entirely in the user message. Keep it that way.
- Remove `client = anthropic.Anthropic(...)` line.
- **KEEP `import anthropic` at line 21** — the Opus function `_generate_plan()` (line 287) still uses `anthropic.Anthropic` via the `claude_client` parameter passed from line 716.
- The `adapt_prompt` local variable stays unchanged — just remove the `client` creation.

### Verification
Chain runner is a background process triggered by T1 alerts. Check Render logs for `chain_adapt` cost entries showing `gemini-2.5-flash`.

---

## Files Modified
- `orchestrator/deadline_manager.py` — 1 site: `_generate_deadline_proposal()`
- `orchestrator/chain_runner.py` — 1 site: `_adapt_write_steps()`

## Do NOT Touch
- `orchestrator/chain_runner.py` — `_generate_plan()` (line 287, Opus), `run_chain()` client init (line 716, Opus)
- All files from Briefs A/B/C — already migrated
- `orchestrator/cost_monitor.py` — contains Haiku price table strings (correct, not call sites)

## Quality Checkpoints
1. `python3 -c "import py_compile; py_compile.compile('orchestrator/deadline_manager.py', doraise=True)"`
2. `python3 -c "import py_compile; py_compile.compile('orchestrator/chain_runner.py', doraise=True)"`
3. **Final verification**: `grep -rn "claude-haiku" orchestrator/ | grep -v cost_monitor | grep -v ".pyc"` — should return **ZERO results**
4. `import anthropic` removed from `deadline_manager.py`, kept in `chain_runner.py`
5. Render logs show no import errors after deploy
6. Commit message must include `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`

## Cost Impact
- 2 final Haiku sites migrated
- After this brief: **zero Haiku call sites remain** in production code
- All 17 original Haiku sites now running on Gemini Flash
- Total Haiku→Flash savings: ~$10-15/month
- Next cost frontier: Opus→Pro migration (separate future briefs, larger savings)
