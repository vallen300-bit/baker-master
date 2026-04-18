"""KBL pipeline step evaluators (Step 1 triage, Step 3 extract, ...).

Each step is a thin module owning its own state transitions against
``signal_queue``. Shared concerns (Ollama client, prompt templates,
loop helpers) live in sibling modules under ``kbl/``.
"""
