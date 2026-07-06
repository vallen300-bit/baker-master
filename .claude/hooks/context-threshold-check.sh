#!/usr/bin/env bash
# Stop hook: warn workers when the transcript approaches the configured context
# window so they checkpoint and respawn instead of relying on compaction.
#
# Contract: exit 0 on every path. Missing config or transcript -> silent no-op.
#
# Thresholds are config-driven. Defaults soft 70 / hard 85. Per key, precedence:
#   env  (ROLLOVER_SOFT_PERCENT / ROLLOVER_HARD_PERCENT / ROLLOVER_WINDOW_TOKENS)
#   -> .claude/settings.local.json  (per-seat, gitignored — where workers set 50)
#   -> .claude/settings.json        (shared/tracked base)
#   -> built-in default.
# This lets a worker picker soft-warn at 50 via settings.local.json while lead
# (bm-aihead1) stays at the 70/85 default with no local override.

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


def _settings_docs(payload: dict) -> list:
    # settings.local.json (per-seat override) is read before settings.json
    # (shared base) so a picker can override any key locally.
    paths: list[Path] = []
    explicit = os.environ.get("ROLLOVER_SETTINGS_PATH")
    if explicit:
        paths.append(Path(explicit))
    # Use payload.cwd EXCLUSIVELY when present so a per-seat percent can never
    # leak from the process cwd (a different picker); fall back to process cwd
    # only when the payload carries no cwd.
    cwd = payload.get("cwd")
    roots: list[Path] = [Path(str(cwd)) / ".claude"] if cwd else [Path.cwd() / ".claude"]
    for root in roots:
        paths.append(root / "settings.local.json")
        paths.append(root / "settings.json")

    docs: list[dict] = []
    for path in paths:
        try:
            docs.append(json.loads(path.read_text()))
        except (OSError, json.JSONDecodeError):
            continue
    return docs


def _settings_int(docs: list, flat_key: str, nested_key: str) -> Optional[int]:
    for settings in docs:
        direct = _coerce_int(settings.get(flat_key))
        if direct:
            return direct
        nested = settings.get("rollover") if isinstance(settings.get("rollover"), dict) else {}
        nested_value = _coerce_int(nested.get(nested_key))
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

docs = _settings_docs(payload)

window_tokens = _coerce_int(os.environ.get("ROLLOVER_WINDOW_TOKENS")) or _settings_int(
    docs, "rollover_window_tokens", "window_tokens"
)
if not window_tokens:
    raise SystemExit(0)

soft = (
    _coerce_int(os.environ.get("ROLLOVER_SOFT_PERCENT"))
    or _settings_int(docs, "rollover_soft_percent", "soft_percent")
    or 70
)
hard = (
    _coerce_int(os.environ.get("ROLLOVER_HARD_PERCENT"))
    or _settings_int(docs, "rollover_hard_percent", "hard_percent")
    or 85
)

# Sanity: keep 0 < soft <= hard <= 100; fall back to defaults if misconfigured.
if not (0 < soft <= 100) or not (0 < hard <= 100) or soft > hard:
    soft, hard = 70, 85

tokens_est = math.ceil(size_bytes / 4)
percent = int((tokens_est / window_tokens) * 100)

if percent < soft:
    raise SystemExit(0)

if percent >= hard:
    _emit(
        "[rollover] context ~{}% ({} est tokens / {} window, hard {}%). "
        "HARD: write or refresh briefs/_checkpoints/<BRIEF_ID>.checkpoint.md now, "
        "commit + push it, post respawn request, then exit cleanly. "
        "Claim in the successor is the attempt-bump commit, not bus ack.".format(
            percent, tokens_est, window_tokens, hard
        ),
        block=True,
    )
else:
    _emit(
        "[rollover] context ~{}% ({} est tokens / {} window, soft {}% / hard {}%). "
        "Refresh the checkpoint before the next phase boundary; at {}% checkpoint and respawn.".format(
            percent, tokens_est, window_tokens, soft, hard, hard
        ),
        block=False,
    )
PY
exit 0
