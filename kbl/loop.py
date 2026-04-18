"""Learning Loop read-side helpers (CHANDA §2).

Pure-read functions consumed across the pipeline:

    load_hot_md                  — Leg 3: hot.md (Director's current priorities)
    load_recent_feedback         — Leg 3: feedback_ledger rows
    render_ledger                — Leg 3: format ledger rows for prompt insertion
    load_gold_context_by_matter  — Leg 1: Gold wiki entries for a matter slug

Invariants:
    - Inv 1 (zero-Gold safe): missing hot.md file, empty ledger table, or a
      matter directory with zero Gold entries are valid states and must NOT
      raise. They return ``None`` / ``[]`` / ``""`` respectively. Raise only
      on true IO/permission/DB failures.
    - Inv 10 (template stability): these helpers read data only. They do
      NOT rewrite or introspect the prompt template.

Env vars:
    BAKER_VAULT_PATH       — vault root; required when ``path`` /
                             ``vault_path`` isn't passed in.
    KBL_STEP1_LEDGER_LIMIT — default row count for ``load_recent_feedback``
                             when ``limit`` is not passed. Defaults to 20.

Writer-side functions (insert into feedback_ledger, write Gold entries)
live in KBL-B impl/KBL-C — not in this module.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import yaml

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


# -------------------------- Leg 1: Gold context reader --------------------------


_WIKI_SUBDIR = "wiki"
_GOLD_VOICE_VALUE = "gold"


def _resolve_vault_root(explicit: Optional[str | Path]) -> Path:
    """Resolve the vault root used for Gold reads.

    Precedence:
        1. ``explicit`` argument
        2. ``BAKER_VAULT_PATH`` env var
    Fails loud when neither is set.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise LoopReadError(
            "BAKER_VAULT_PATH env var not set — required to locate "
            "wiki/<matter>/ (or pass an explicit vault_path)"
        )
    return Path(vault).expanduser()


def _read_frontmatter(content: str) -> Optional[dict[str, Any]]:
    """Extract the YAML frontmatter from a Markdown file.

    Returns the parsed dict when the file starts with a ``---`` fence
    closed by another ``---`` fence, else ``None``. Malformed YAML inside
    the fence also yields ``None`` — the caller (Gold filter) treats
    "unparseable frontmatter" the same as "no voice:gold declaration",
    i.e. Silver (exclude). Not a fail-loud case: Silver entries are a
    valid vault state and must not block Gold reads for the rest of the
    matter.
    """
    if not content.startswith("---"):
        return None
    # Split on the first two `---` fences. Tolerate both `---\n` and
    # `---\r\n` line endings.
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    yaml_text = "\n".join(lines[1:end_idx])
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _is_gold_file(path: Path) -> tuple[bool, str]:
    """Return ``(is_gold, full_content)`` for a single file.

    A file is Gold when its frontmatter dict contains ``voice: gold`` (case-
    insensitive on the value). Any other state (Silver, missing frontmatter,
    malformed frontmatter) yields ``(False, "")`` and is excluded.

    IO errors on the read surface as ``LoopReadError`` so operator sees them;
    individual malformed frontmatter does NOT — that's a content concern,
    not a vault-health concern.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False, ""  # race: file vanished mid-scan, treat as non-Gold
    except OSError as e:
        raise LoopReadError(f"failed to read {path}: {e}") from e

    fm = _read_frontmatter(content)
    if not fm:
        return False, ""
    voice = fm.get("voice")
    if not isinstance(voice, str):
        return False, ""
    return voice.strip().lower() == _GOLD_VOICE_VALUE, content


def load_gold_context_by_matter(
    matter: str, vault_path: Optional[str | Path] = None
) -> str:
    """Concatenate all Gold entries under ``wiki/<matter>/`` into one block.

    Feeds Leg 1 (Gold-read-by-matter) — downstream consumer is the Step 5
    Opus synthesis prompt. Each file is emitted as:

        <!-- GOLD: wiki/<matter>/<filename> -->
        <file content verbatim, including its own frontmatter>

    Files are separated by a single blank line so the block stays
    prompt-insertable. File order is ``sorted(filename)``; the vault's
    date-prefixed filename convention (``YYYY-MM-DD_topic.md``) makes that
    chronological without parsing the frontmatter date field.

    Args:
        matter: canonical matter slug. Caller is expected to have normalized
            it via ``slug_registry.normalize()`` when sourcing from model
            output; this function does not validate against the registry so
            the Leg 1 read is free of slug-registry coupling.
        vault_path: override ``$BAKER_VAULT_PATH``. Same precedence as
            ``load_hot_md``.

    Returns:
        Concatenated Markdown block, or ``""`` when there are zero Gold
        files. **Empty return is Inv 1 compliant — zero Gold is read AS
        zero Gold, not as a fault.** The caller's prompt can wrap with a
        "(no Gold context available)" fallback if the template requires
        non-empty content.

    Raises:
        LoopReadError: on IO/permission errors (unreadable matter dir, file
            permission denied, etc.). Missing matter dir is NOT an error —
            a new matter with no Gold yet is valid zero-Gold. Malformed
            frontmatter in one file is NOT an error — the file is treated
            as Silver and excluded; other files in the matter still load.
    """
    if not matter or not isinstance(matter, str):
        raise LoopReadError(f"matter must be a non-empty string (got {matter!r})")

    vault_root = _resolve_vault_root(vault_path)
    matter_dir = vault_root / _WIKI_SUBDIR / matter

    if not matter_dir.exists():
        return ""

    try:
        if not matter_dir.is_dir():
            raise LoopReadError(
                f"expected a directory at {matter_dir} (found non-dir entry)"
            )
        md_files = sorted(p for p in matter_dir.iterdir() if p.suffix == ".md" and p.is_file())
    except PermissionError as e:
        raise LoopReadError(f"permission denied listing {matter_dir}: {e}") from e
    except OSError as e:
        raise LoopReadError(f"failed to list {matter_dir}: {e}") from e

    blocks: list[str] = []
    for md_path in md_files:
        is_gold, content = _is_gold_file(md_path)
        if not is_gold:
            continue
        rel_path = f"{_WIKI_SUBDIR}/{matter}/{md_path.name}"
        blocks.append(f"<!-- GOLD: {rel_path} -->\n{content.rstrip()}")

    if not blocks:
        return ""
    return "\n\n".join(blocks)
