"""Learning Loop read-side helpers (CHANDA §2 Leg 3).

Three small pure-read functions consumed by KBL-B Step 1 prompt assembly:

    load_hot_md          — read `hot.md` from the vault (Director-maintained
                           high-signal bullets). Zero-Gold if absent.
    load_recent_feedback — pull the most recent N rows from
                           `feedback_ledger` (written by Leg 2 Capture).
    render_ledger        — format feedback_ledger rows into a block a
                           prompt template can drop in verbatim.

Invariants:
    - Inv 1 (zero-Gold safe): missing hot.md file or empty ledger table are
      valid states and must NOT raise. They return ``None`` and ``[]``
      respectively. Raise only on true IO/permission/DB failures.
    - Inv 10 (template stability): these helpers read data only. They do
      NOT rewrite or introspect the prompt template.

Env vars:
    BAKER_VAULT_PATH       — vault root; required when `path` is not passed
                             to ``load_hot_md``.
    KBL_STEP1_LEDGER_LIMIT — default row count for ``load_recent_feedback``
                             when ``limit`` is not passed. Defaults to 20.

Writer-side functions (insert into feedback_ledger) live in KBL-B
impl/KBL-C — not in this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

_DEFAULT_LEDGER_LIMIT = 20
_LEDGER_LIMIT_ENV = "KBL_STEP1_LEDGER_LIMIT"
_HOT_MD_VAULT_SUBPATH = Path("wiki") / "hot.md"


class LoopReadError(RuntimeError):
    """Raised when a Leg-3 read fails for IO/permission/DB reasons.

    Distinct from the zero-Gold case (file absent / table empty), which is
    not an error and is signalled by sentinel returns (``None`` / ``[]``).
    """


# ---------------------------- hot.md reader ----------------------------


def _resolve_hot_md_path(explicit: Optional[str | Path]) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser()
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise LoopReadError(
            "BAKER_VAULT_PATH env var not set — required to locate "
            "wiki/hot.md (or pass an explicit path)"
        )
    return Path(vault).expanduser() / _HOT_MD_VAULT_SUBPATH


def load_hot_md(path: Optional[str | Path] = None) -> Optional[str]:
    """Read ``hot.md`` from the vault.

    Args:
        path: Explicit file path. If omitted, resolves to
            ``$BAKER_VAULT_PATH/wiki/hot.md``.

    Returns:
        File contents as ``str``, or ``None`` if the file does not exist
        (valid zero-Gold state per CHANDA Inv 1).

    Raises:
        LoopReadError: when ``BAKER_VAULT_PATH`` is unset and no explicit
            path was given, or when the file exists but cannot be read
            (permission denied, other IO error).
    """
    resolved = _resolve_hot_md_path(path)
    try:
        return resolved.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise LoopReadError(f"failed to read {resolved}: {e}") from e


# -------------------------- feedback_ledger reader --------------------------


_LEDGER_COLUMNS = (
    "id",
    "created_at",
    "action_type",
    "target_matter",
    "target_path",
    "signal_id",
    "payload",
    "director_note",
)


def _resolve_ledger_limit(explicit: Optional[int]) -> int:
    if explicit is not None:
        if not isinstance(explicit, int) or explicit <= 0:
            raise LoopReadError(
                f"limit must be a positive int (got {explicit!r})"
            )
        return explicit
    raw = os.environ.get(_LEDGER_LIMIT_ENV)
    if raw is None or raw == "":
        return _DEFAULT_LEDGER_LIMIT
    try:
        parsed = int(raw)
    except ValueError as e:
        raise LoopReadError(
            f"{_LEDGER_LIMIT_ENV}={raw!r} must be a positive int"
        ) from e
    if parsed <= 0:
        raise LoopReadError(
            f"{_LEDGER_LIMIT_ENV}={raw!r} must be a positive int"
        )
    return parsed


def load_recent_feedback(
    conn: Any, limit: Optional[int] = None
) -> list[dict[str, Any]]:
    """Query ``feedback_ledger`` for the N most recent rows.

    Args:
        conn: psycopg2 connection. Caller owns lifecycle.
        limit: Row cap. When omitted, reads env var
            ``KBL_STEP1_LEDGER_LIMIT`` (default 20).

    Returns:
        List of dicts with keys: ``id``, ``created_at``, ``action_type``,
        ``target_matter``, ``target_path``, ``signal_id``, ``payload``,
        ``director_note``. Most-recent-first. Empty list when the table is
        empty (valid zero-Gold state per CHANDA Inv 1).

    Raises:
        LoopReadError: on DB errors, or when the resolved ``limit`` is not
            a positive int.
    """
    effective_limit = _resolve_ledger_limit(limit)
    sql = (
        "SELECT " + ", ".join(_LEDGER_COLUMNS) + " "
        "FROM feedback_ledger "
        "ORDER BY created_at DESC "
        "LIMIT %s"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (effective_limit,))
            rows = cur.fetchall()
    except Exception as e:
        # Roll back so the caller's connection isn't stuck in an aborted
        # transaction. Best-effort — rollback itself can fail on a dead
        # connection and we still want to surface the original error.
        try:
            conn.rollback()
        except Exception:
            pass
        raise LoopReadError(f"failed to read feedback_ledger: {e}") from e
    return [dict(zip(_LEDGER_COLUMNS, row)) for row in rows]


# ---------------------------- renderer ----------------------------


def _format_timestamp(value: Any) -> str:
    """Render a row's created_at as ``YYYY-MM-DD``.

    Accepts datetime, date, or a string whose first 10 chars are the date.
    Falls back to ``????-??-??`` when the shape is unrecognized rather than
    raising — the renderer is best-effort display, not validation.
    """
    if hasattr(value, "strftime"):
        try:
            return value.strftime("%Y-%m-%d")
        except Exception:
            pass
    if isinstance(value, str) and len(value) >= 10:
        return value[:10]
    return "????-??-??"


def _target_label(row: dict[str, Any]) -> str:
    matter = row.get("target_matter")
    if isinstance(matter, str) and matter.strip():
        return matter
    path = row.get("target_path")
    if isinstance(path, str) and path.strip():
        return path
    return "—"


def _payload_summary(payload: Any) -> str:
    if payload in (None, "", {}, []):
        return ""
    if isinstance(payload, (dict, list)):
        try:
            return json.dumps(payload, default=str, sort_keys=True)
        except Exception:
            return str(payload)
    return str(payload)


def _detail(row: dict[str, Any]) -> str:
    note = row.get("director_note")
    if isinstance(note, str) and note.strip():
        return note
    summary = _payload_summary(row.get("payload"))
    return summary or "(no detail)"


def _collapse(text: str) -> str:
    """Collapse whitespace so each row renders on a single line.

    director_note and payload summaries may contain newlines/markdown;
    tabs and newlines would break one-row-per-line output. We normalize
    to spaces without touching other markdown punctuation.
    """
    return " ".join(text.split())


def render_ledger(rows: list[dict[str, Any]]) -> str:
    """Format ledger rows into a prompt-insertable Markdown block.

    One line per row, Director-scannable:
        [YYYY-MM-DD] <action_type> <target_matter|target_path>: <detail>

    Args:
        rows: Output of ``load_recent_feedback`` (order preserved).

    Returns:
        Multi-line string, or ``(no recent Director actions)`` when
        ``rows`` is empty (zero-Gold state).
    """
    if not rows:
        return "(no recent Director actions)"
    lines: list[str] = []
    for row in rows:
        date = _format_timestamp(row.get("created_at"))
        action = str(row.get("action_type") or "unknown")
        target = _target_label(row)
        detail = _collapse(_detail(row))
        lines.append(f"[{date}] {action} {target}: {detail}")
    return "\n".join(lines)
