# Client PM Onboarding Checklist
> Created: 2026-04-01 | Reference implementation: AO PM (ao_pm, Andrey Oskolkov)

When spinning up a new dedicated Client PM capability, create all of the following:

## 1. Database: Capability Row
```sql
INSERT INTO capability_sets (
    slug, name, capability_type, domain, role_description,
    system_prompt, tools, trigger_patterns, output_format,
    autonomy_level, max_iterations, timeout_seconds, active, use_thinking
) VALUES (
    '{client}_pm',           -- e.g. 'wertheimer_pm'
    '{Client} Project Manager',
    'domain', 'chairman',
    '{one-line description}',
    '{full system prompt}',  -- see Soul section below
    '{tools JSON array}',   -- minimum: all 18 standard + get_ao_state, update_ao_state, delegate_to_capability
    '{trigger patterns}',   -- regex array for routing
    'prose', 'recommend_wait', 8, 90.0, TRUE, TRUE
);
```

## 2. Database: State Table
```sql
CREATE TABLE {client}_project_state (
    id SERIAL PRIMARY KEY,
    state_key TEXT NOT NULL DEFAULT 'current',
    state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INTEGER DEFAULT 1,
    last_run_at TIMESTAMPTZ,
    last_question TEXT,
    last_answer_summary TEXT,
    run_count INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_{client}_state_key ON {client}_project_state(state_key);

CREATE TABLE {client}_state_history (
    id SERIAL PRIMARY KEY,
    version INTEGER NOT NULL,
    state_json_before JSONB NOT NULL,
    mutation_source TEXT,
    mutation_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

## 3. Dropbox: Folder Structure
```
Baker-Project/01_Projects/Active_Projects/{Client}/
├── 00_Raw/              -- raw evidence
├── 01_Working/          -- prep, drafts
├── 02_Final/            -- finalized docs
└── 03_Source_Of_Truth/
    ├── The_Actual_Position.md
    └── Reported_To_{Client}/
```

## 4. Dropbox: Watch Path
Add to `DROPBOX_WATCH_PATH` env var on Render (comma-separated):
```
/Baker-Feed,/Baker-Project/01_Projects/Active_Projects/Oskolkov,/Baker-Project/01_Projects/Active_Projects/{Client}
```

## 5. Code Changes
- `memory/store_back.py`: Add `_ensure_{client}_project_state_table()`, `get_{client}_project_state()`, `update_{client}_project_state()`. Call from `__init__`.
- `orchestrator/agent.py`: Add tool definitions + handlers (or generalize existing AO tools with a `client` parameter).
- `orchestrator/capability_runner.py`: Add state injection in `_build_system_prompt()`, auto-update hook in `_maybe_store_insight()`.
- `orchestrator/context_selector.py`: Add `{client}_pm` to `_SPECIALIST_SOURCE_MAP`.

## 6. System Prompt (Soul) — Must Include
- [ ] Persona (sharp PM, challenges assumptions)
- [ ] Client relationship context (who they are, what they want, red lines)
- [ ] Active sub-matters with current status
- [ ] Red flags (what to never raise, what to monitor)
- [ ] Key financial facts table
- [ ] Key people in client's orbit
- [ ] Document hierarchy (Dropbox paths + DB queries + Qdrant filters)
- [ ] Document rules (03 is gospel, check Reported_To before comms)
- [ ] Tool protocol (load state first, update state last, delegate to specialists)
- [ ] Output format (Current Situation → Key Changes → Risk Assessment → Recommended Actions → Counter-arguments)
- [ ] Citation rules

## 7. Trigger Patterns
- Client name variations (including transliterations)
- Entity names (holding companies, SPVs)
- Project codes
- Key relationship terms (e.g. "capital call + {client}")

## 8. Matter Registry
- Ensure matter exists in `matter_registry` table
- Keywords array covers all variations
- People array covers all associated contacts
- Update `context_selector.py` matter regex if needed

## 9. Update Decomposer
```sql
UPDATE capability_sets
SET system_prompt = REPLACE(system_prompt, 'ao_pm, profiling', '{client}_pm, ao_pm, profiling')
WHERE slug = 'decomposer';
```

## 10. Seed Initial State
Run migration script to populate `{client}_project_state` with known facts from existing documents, meetings, emails.

## Estimated Time
- First client PM (AO): ~3 hours (built from scratch)
- Second client PM: ~1 hour (copy pattern, customize soul + state)
- Third+: ~30 min (if tools are generalized with client parameter)

## Future: Generalization
When client #3 arrives, refactor:
- Generic `client_project_state` table with `client_slug` column (not per-client tables)
- Generic `get_client_state(slug)` / `update_client_state(slug, updates)` tools
- Soul template with `{placeholders}` filled from a config
- `create_client_pm(name, matter_slugs, language, cadence)` factory function
