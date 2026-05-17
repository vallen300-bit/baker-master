---
paths:
  - "*.py"
  - "**/*.py"
---

# Python Backend Rules

- PostgreSQL: MUST `conn.rollback()` in except blocks before any new query
- Always LIMIT unbounded SQL queries. Key columns: whatsapp=`full_text`, meetings=`full_transcript`
- Fault-tolerant writes: wrap DB/API calls in try/except
- Python regex: use `re.IGNORECASE` flag, not inline `(?i)` after `|`
- Syntax check before commit: `python3 -c "import py_compile; py_compile.compile('file.py', doraise=True)"`
- Email/WA conversation history: 2 turns only for outbound (CONV-SAFETY-1)
- Render env vars: use MCP merge mode, NEVER raw PUT. Python path: `from tools.render_env_guard import safe_env_put` (forces single-key `PUT /env-vars/{KEY}` merge-mode; rejects array-form PUT). Anchor: 2026-05-17 catastrophic wipe.
