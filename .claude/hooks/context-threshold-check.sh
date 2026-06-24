#!/usr/bin/env bash
# Stop hook: warn workers when the transcript approaches the configured context
# window so they checkpoint and respawn instead of relying on compaction.
#
# Contract: exit 0 on every path. Missing config or transcript -> silent no-op.

PAYLOAD="$(cat 2>/dev/null || true)"
ROLLOVER_HOOK_PAYLOAD="$PAYLOAD" python3 - <<'PY'
import json
import math
import os
from pathlib import Path
from typing import Optional


def _emit(text: str, *, block: bool) -> None:
    # Stop hooks cannot use hookSpecificOutput.additionalContext; Claude's
    # schema only accepts top-level Stop fields here.
    out = {"systemMessage": text}
    if block:
        out["decision"] = "block"
        out["reason"] = text
    print(json.dumps(out))


def _coerce_int(value: object) -> Optional[int]:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _settings_window(payload: dict) -> Optional[int]:
    candidates: list[Path] = []
    explicit = os.environ.get("ROLLOVER_SETTINGS_PATH")
    if explicit:
        candidates.append(Path(explicit))
    cwd = payload.get("cwd")
    if cwd:
        candidates.append(Path(str(cwd)) / ".claude" / "settings.json")
    candidates.append(Path.cwd() / ".claude" / "settings.json")

    for path in candidates:
        try:
            settings = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        direct = _coerce_int(settings.get("rollover_window_tokens"))
        if direct:
            return direct
        nested = settings.get("rollover") if isinstance(settings.get("rollover"), dict) else {}
        nested_value = _coerce_int(nested.get("window_tokens"))
        if nested_value:
            return nested_value
    return None


try:
    payload = json.loads(os.environ.get("ROLLOVER_HOOK_PAYLOAD", "") or "{}")
except json.JSONDecodeError:
    raise SystemExit(0)

transcript = payload.get("transcript_path")
if not transcript:
    raise SystemExit(0)

path = Path(str(transcript))
try:
    size_bytes = path.stat().st_size
except OSError:
    raise SystemExit(0)

window_tokens = _coerce_int(os.environ.get("ROLLOVER_WINDOW_TOKENS")) or _settings_window(payload)
if not window_tokens:
    raise SystemExit(0)

tokens_est = math.ceil(size_bytes / 4)
percent = int((tokens_est / window_tokens) * 100)

if percent < 70:
    raise SystemExit(0)

if percent >= 85:
    _emit(
        "[rollover] context ~{}% ({} est tokens / {} window). "
        "HARD: write or refresh briefs/_checkpoints/<BRIEF_ID>.checkpoint.md now, "
        "commit + push it, post respawn request, then exit cleanly. "
        "Claim in the successor is the attempt-bump commit, not bus ack.".format(
            percent, tokens_est, window_tokens
        ),
        block=True,
    )
else:
    _emit(
        "[rollover] context ~{}% ({} est tokens / {} window). "
        "Refresh the checkpoint before the next phase boundary; at 85% checkpoint and respawn.".format(
            percent, tokens_est, window_tokens
        ),
        block=False,
    )
PY
exit 0
