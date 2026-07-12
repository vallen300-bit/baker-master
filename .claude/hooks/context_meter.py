"""Shared context-window band computation — the ONE source of truth.

CASE_ONE_P0_CONTEXT_METERING_1 (b3, rubric #1: one band computation, no drift).
Both the Stop hook (`context-threshold-check.sh`, which warns a human in the
transcript) and the machine band field it writes for the heartbeat emitter call
`compute()` here, so the human-facing warning and the machine-readable band can
never disagree for the same transcript.

Pure + import-safe: no I/O beyond reading the transcript it is handed, no network,
no process exit. Callers own settings resolution and emit/marker side effects.

Band vocabulary is {ok, soft, hard} — the same 3 bands the 70/85 thresholds
already express. This is DELIBERATELY separate from brisen-lab's TokenPressure
machine (green/yellow/orange/red), which is the forge-side H3 enforcement meter
that auto-kills sessions. This module measures context-window occupancy only and
is advisory; the two meters must not be conflated (brief P0.3 / lead #9733).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional


def context_tokens_from_usage(path: Path) -> Optional[int]:
    """True context occupancy = the LAST turn's API-reported usage, not the
    transcript's on-disk byte count. The JSONL stores full tool-result dumps +
    envelopes + every prior turn verbatim and never shrinks on compaction, so
    bytes/4 runs 1.5x-4.6x high and only climbs (CONTEXT_METER_FIX_1). Each
    assistant turn carries message.usage; the running context is
        input_tokens + cache_read_input_tokens + cache_creation_input_tokens
    (output_tokens excluded — matches Claude Code's own /context measure).
    Returns None when no usage is present so the caller falls back to bytes/4.
    """
    last: Optional[int] = None
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                # Cheap pre-filter: skip the (large, frequent) tool-result lines
                # that carry no usage before paying for a json.loads.
                if '"usage"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                # A JSONL line may be any valid JSON value (e.g. a list) that still
                # contains the substring "usage" and passes the prefilter above.
                # Guard before .get() so a non-dict record falls through to the
                # bytes/4 fallback instead of raising (keeps the hook fault-tolerant).
                if not isinstance(obj, dict):
                    continue
                message = obj.get("message")
                usage = message.get("usage") if isinstance(message, dict) else None
                if not isinstance(usage, dict):
                    usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else None
                if not isinstance(usage, dict):
                    continue
                total = 0
                found = False
                for key in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
                    value = usage.get(key)
                    if isinstance(value, bool) or not isinstance(value, int):
                        continue
                    total += value
                    found = True
                if found:
                    last = total
    except OSError:
        return None
    return last if last and last > 0 else None


def measure_tokens(path: Path) -> tuple[Optional[int], bool]:
    """Return (tokens, measured). measured=True when tokens come from the
    transcript's API usage fields; measured=False when we fall back to bytes/4
    (non-Claude / empty / malformed transcript). tokens is None only when the
    transcript cannot be read at all."""
    tokens = context_tokens_from_usage(path)
    if tokens is not None:
        return tokens, True
    try:
        size_bytes = path.stat().st_size
    except OSError:
        return None, False
    return math.ceil(size_bytes / 4), False


def band_for(percent: int, soft: int, hard: int) -> str:
    """Map an occupancy percent to a band using the same soft/hard cutoffs the
    Stop hook warns on. hard takes precedence over soft."""
    if percent >= hard:
        return "hard"
    if percent >= soft:
        return "soft"
    return "ok"


def compute(
    transcript_path: str | Path,
    window_tokens: int,
    soft_percent: int,
    hard_percent: int,
) -> Optional[dict]:
    """The single band computation. Returns
        {context_percent, band, window_tokens, measured, tokens}
    or None when the transcript cannot be read or the window is unset. Callers
    (the Stop hook warning + the band-file the heartbeat carries) use ONE call
    each so their bands are identical by construction."""
    if not window_tokens or window_tokens <= 0:
        return None
    tokens, measured = measure_tokens(Path(str(transcript_path)))
    if tokens is None:
        return None
    percent = int((tokens / window_tokens) * 100)
    return {
        "context_percent": percent,
        "band": band_for(percent, soft_percent, hard_percent),
        "window_tokens": window_tokens,
        "measured": measured,
        "tokens": tokens,
    }
