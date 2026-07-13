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
#
# Block-at-most-once: over the hard band the hook returns decision:block EXACTLY
# once per session (marker keyed to transcript_path), then steps aside. A Stop
# hook that blocks forces the session to CONTINUE, never to stop — so blocking on
# every Stop traps it: each blocked turn grows the transcript, pushing percent
# higher, a self-feeding loop (BB desk 137->153%, +21.4k tokens, 2026-07-08,
# Director-witnessed). One block forces the checkpoint; the successor is spawned
# by orchestrator-wake, so the clean exit that follows loses nothing.
#
# KNOWN LIMIT: measurement happens only at Stop (turn end). One very long turn can
# jump from under the soft band to far over hard in a single measurement (BB desk
# first-fired at 137%). Not fixable here — mid-turn metering is the outer
# context-cost watchdog's job (context-cost-watchdog-delta spec, cowork-ah1).

PAYLOAD="$(cat 2>/dev/null || true)"
# Directory of THIS hook, so the heredoc Python can import the shared
# context_meter module (rubric #1: one band computation, no drift). Resolve the
# real path so a symlinked hook still finds its sibling module.
_HOOK_SRC="${BASH_SOURCE[0]:-$0}"
CONTEXT_METER_DIR="$(cd "$(dirname "$_HOOK_SRC")" >/dev/null 2>&1 && pwd -P || true)"
ROLLOVER_HOOK_PAYLOAD="$PAYLOAD" CONTEXT_METER_DIR="$CONTEXT_METER_DIR" python3 - <<'PY'
import json
import os
import sys
from pathlib import Path
from typing import Optional

# Import the shared band computation (same module the band-file emitter uses).
_meter_dir = os.environ.get("CONTEXT_METER_DIR") or str(Path(__file__).resolve().parent)
if _meter_dir and _meter_dir not in sys.path:
    sys.path.insert(0, _meter_dir)
try:
    import context_meter
except Exception:
    # If the shared module cannot be imported, the hook must still no-op
    # cleanly (exit-0 contract) rather than crash the session.
    raise SystemExit(0)


def _emit(text: str, *, block: bool) -> None:
    # Stop hooks cannot use hookSpecificOutput.additionalContext; Claude's
    # schema only accepts top-level Stop fields here.
    out = {"systemMessage": text}
    if block:
        out["decision"] = "block"
        out["reason"] = text
    print(json.dumps(out))


def _write_band_file(session_id: Optional[str], meter: dict) -> None:
    # P0.1 emit (B2, lead #9733): the Stop hook is the one place with the
    # measured transcript, so it writes the machine band to a local file keyed by
    # session_id (== the heartbeat ticker's SESSION_UUID). The ticker reads this
    # file and carries the fields in its next /api/heartbeat POST. Network I/O
    # stays OUT of the hook so the exit-0 contract is never at risk. Written for
    # EVERY band incl. ok, so a fresh healthy seat reports band=ok (retires the
    # E16 fresh-seat false alarm) — not only when a warning fires.
    if not session_id:
        return
    # Only [A-Za-z0-9._-] in the filename; a malformed session_id can never
    # escape the band dir.
    safe = "".join(c for c in str(session_id) if c.isalnum() or c in "._-")
    if not safe:
        return
    try:
        band_dir = Path(os.environ.get("CONTEXT_BAND_DIR") or (Path.home() / "forge-agent" / "context-band"))
        band_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "session_id": str(session_id),
            "context_percent": meter["context_percent"],
            "band": meter["band"],
            "measured": meter["measured"],
            "window_tokens": meter["window_tokens"],
        }
        tmp = band_dir / (safe + ".json.tmp")
        final = band_dir / (safe + ".json")
        tmp.write_text(json.dumps(record))
        tmp.replace(final)  # atomic swap so the ticker never reads a half file
        # P4.5 band self-read (#9986, CASE_ONE_P4): a seat is named by its
        # <session_uuid>.json but doesn't easily know its own uuid. Maintain a
        # stable <alias>.current symlink (alias = BAKER_ROLE, lowercased) that
        # points at this seat's current band file, so the seat can self-read its
        # own band by a name it knows. Advisory: if BAKER_ROLE is unset, or the
        # symlink can't be made, skip silently — the session must survive it.
        alias = (os.environ.get("BAKER_ROLE") or "").strip().lower()
        if alias:
            try:
                link = band_dir / (alias + ".current")
                link_tmp = band_dir / (alias + ".current.tmp")
                # Relative target (just the filename) so the link stays portable
                # within the band dir.
                try:
                    link_tmp.unlink()
                except FileNotFoundError:
                    pass
                os.symlink(final.name, link_tmp)
                os.replace(link_tmp, link)  # atomic swap of the alias link
            except OSError:
                # Symlink is advisory only; never let it raise out of the hook.
                try:
                    link_tmp.unlink()
                except OSError:
                    pass
    except Exception:
        # Advisory metering must never break the session; swallow everything.
        return


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

# One band computation, shared with the heartbeat band-file emitter (rubric #1).
# Prefers the transcript's own API-reported usage; falls back to bytes/4 only
# when no usage field is present (non-Claude / empty / malformed transcript).
meter = context_meter.compute(path, window_tokens, soft, hard)
if meter is None:
    raise SystemExit(0)
tokens_est = meter["tokens"]
percent = meter["context_percent"]

# Emit the machine band for the heartbeat to carry — for EVERY band, before the
# soft-gate early-exit, so a healthy ok seat still reports (retires E16).
_write_band_file(payload.get("session_id"), meter)

if percent < soft:
    raise SystemExit(0)

if percent >= hard:
    # Block-at-most-once (see header). Marker is keyed to transcript_path:
    # unique per session, local, deterministic — no cross-session leak, and no
    # race with the checkpoint commit (a local file, not a git/bus round-trip).
    marker = Path(str(transcript) + ".rollover-blocked")
    if marker.exists():
        # Already forced a checkpoint this session. Blocking again would loop
        # the session forever; let it exit. orchestrator-wake spawns the
        # successor, so nothing is lost.
        _emit(
            "[rollover] context ~{}% ({} est tokens / {} window, hard {}%). "
            "Checkpoint already demanded this session — exit now; the successor is "
            "spawned by orchestrator-wake so a clean exit loses nothing. If you have "
            "NOT yet written briefs/_checkpoints/<BRIEF_ID>.checkpoint.md + committed "
            "+ pushed + posted the respawn request, do it first, then exit.".format(
                percent, tokens_est, window_tokens, hard
            ),
            block=False,
        )
    else:
        try:
            marker.write_text(str(tokens_est))
            blocked = True
        except OSError:
            # Cannot persist the marker -> never block, or the session would loop
            # forever with no way to record that it was already told.
            blocked = False
        _emit(
            "[rollover] context ~{}% ({} est tokens / {} window, hard {}%). "
            "HARD: write or refresh briefs/_checkpoints/<BRIEF_ID>.checkpoint.md now, "
            "commit + push it, post respawn request, then exit cleanly. "
            "Claim in the successor is the attempt-bump commit, not bus ack.".format(
                percent, tokens_est, window_tokens, hard
            ),
            block=blocked,
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
