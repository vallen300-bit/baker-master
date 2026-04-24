"""Log Claude cache-usage telemetry to baker_actions.

Every call site that wants cache tracking calls `log_cache_usage()` with
the SDK response's `usage` object + a call-site label. Emits a single
baker_actions row of action_type='claude:cache_usage'.

Zero dependencies on call-site details - just reads usage.input_tokens /
output_tokens / cache_read_input_tokens / cache_creation_input_tokens.
Silent on failure (cache metric loss << call failure).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("baker.kbl.cache_telemetry")


def log_cache_usage(
    usage: Any,
    call_site: str,
    model: Optional[str] = None,
    trigger_source: str = "claude_call",
) -> None:
    """Fire-and-forget cache-usage log. No return value."""
    try:
        cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        input_tok = int(getattr(usage, "input_tokens", 0) or 0)
        output_tok = int(getattr(usage, "output_tokens", 0) or 0)
    except Exception:
        return  # usage object malformed - skip silently

    try:
        from memory.store_back import SentinelStoreBack
        store = SentinelStoreBack._get_global_instance()
        if store is None:
            return
        denom = cache_read + input_tok
        hit_ratio = (cache_read / denom) if denom > 0 else 0.0
        store.log_baker_action(
            action_type="claude:cache_usage",
            payload={
                "call_site": call_site,
                "model": model,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cache_read_tokens": cache_read,
                "cache_write_tokens": cache_write,
                "cache_hit_ratio": hit_ratio,
            },
            trigger_source=trigger_source,
            success=True,
        )
    except Exception as e:
        logger.warning("log_cache_usage failed (non-fatal): %s", e)
