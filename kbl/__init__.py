"""KBL (Knowledge Base Layer) — Baker's compiled-wiki knowledge architecture.

Phase 1 scope (KBL-A):
- Schema migrations applied via memory/store_back.py _ensure_* methods.
- Mac Mini runtime: pipeline tick wrapper, Gold drain worker, heartbeat.
- Retry + circuit breaker + cost tracking + logging primitives.
- Config sourced from baker-vault/config/env.mac-mini.yml via yq.

Pipeline orchestration body (8-step Triage → Opus) is KBL-B, not this module.
"""
