"""KBL bridge package — producers that feed signal_queue from upstream subsystems.

Each module here is a thin DB-to-DB selector + mapper. No LLM calls. No
cost-gate interaction. Bridges run at their own scheduler cadence
upstream of ``kbl.pipeline_tick``.
"""
