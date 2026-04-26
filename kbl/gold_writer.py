"""GOLD_COMMENT_WORKFLOW_1 — programmatic Tier B Gold write path.

Distinct from kbl/gold_drain.py (which drains gold_promote_queue from
Director's WhatsApp /gold flow). This module is the AI Head-mediated
write surface — invoked when AI Head executes Tier B Gold commits.

Hard guards:
  1. DV-only initials check (drift detector enforces "DV." in ratification_quote)
  2. Caller-stack check (rejects callers whose stack frame includes
     `cortex_*` — those callers must use gold_proposer.py instead)
  3. File-write-target check (matter slug must be canonical in slugs.yml or
     scope must be 'global')
  4. Drift-detector pre-check (kbl.gold_drift_detector.validate_entry)

Failures are NEVER silent: log to gold_write_failures + raise.
"""
from __future__ import annotations

import inspect
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("baker.gold_writer")


class GoldWriteError(RuntimeError):
    """Raised when a Gold write violates a hard guard."""


class CallerNotAuthorized(GoldWriteError):
    """Cortex/proposer callers tried to write to ratified Gold."""


@dataclass(frozen=True)
class GoldEntry:
    iso_date: str           # YYYY-MM-DD
    topic: str              # H2 title noun phrase
    ratification_quote: str
    background: str
    resolution: str
    authority_chain: str
    carry_forward: str = "none"
    matter: Optional[str] = None  # canonical slug or None for global


def _check_caller_authorized() -> None:
    """Reject if any frame in the calling stack belongs to cortex_*."""
    for frame in inspect.stack():
        mod = frame.frame.f_globals.get("__name__", "") or ""
        if mod.startswith("cortex_") or mod.startswith("kbl.cortex"):
            raise CallerNotAuthorized(
                f"gold_writer.append rejected — caller {mod!r} must use gold_proposer"
            )


def _resolve_target_path(entry: GoldEntry, vault_root: Path) -> Path:
    """Returns the canonical file path for a ratified entry."""
    if entry.matter is None:
        return vault_root / "_ops" / "director-gold-global.md"
    from kbl import slug_registry
    if not slug_registry.is_canonical(entry.matter):
        raise GoldWriteError(
            f"matter slug {entry.matter!r} not canonical in slugs.yml"
        )
    return vault_root / "wiki" / "matters" / entry.matter / "gold.md"


def _resolve_vault_root(vault_root: Optional[Path]) -> Path:
    if vault_root is not None:
        return vault_root
    return Path(
        os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault"))
    )


def append(entry: GoldEntry, *, vault_root: Optional[Path] = None) -> Path:
    """Append a ratified Gold entry. Raises on any guard failure.

    Args:
        entry: GoldEntry instance with all fields populated.
        vault_root: override $BAKER_VAULT_PATH (mainly for tests).

    Returns:
        Path of the file written.

    Raises:
        CallerNotAuthorized: caller stack contained cortex_*.
        GoldWriteError: drift-validate failed OR matter slug not canonical OR
            target dir doesn't exist.
    """
    _check_caller_authorized()
    vault_root = _resolve_vault_root(vault_root)
    target = _resolve_target_path(entry, vault_root)

    if entry.matter is not None and not target.parent.is_dir():
        raise GoldWriteError(
            f"matter dir {target.parent} does not exist — bootstrap before writing"
        )

    from kbl import gold_drift_detector
    issues = gold_drift_detector.validate_entry(entry, target)
    if issues:
        msg = "; ".join(f"[{i.code}] {i.message}" for i in issues)
        _log_failure(entry, target, "drift_validate", msg)
        raise GoldWriteError(f"drift validation failed: {msg}")

    block = _render_entry(entry)
    if not target.exists():
        target.write_text("", encoding="utf-8")
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n" + block + "\n")
    logger.info("gold_writer.append: wrote %s", target)
    return target


def _render_entry(entry: GoldEntry) -> str:
    """Format per spec §Entry format. Matches existing director-gold-global.md style."""
    quote = entry.ratification_quote.strip()
    if not quote.rstrip().endswith("DV."):
        quote = f"{quote.rstrip()} DV."
    return (
        f"## {entry.iso_date} — {entry.topic}\n\n"
        f"**Ratification:** {quote}\n\n"
        f"**Background:** {entry.background}\n\n"
        f"**Resolution:** {entry.resolution}\n\n"
        f"**Authority chain:** {entry.authority_chain}\n\n"
        f"**Carry-forward:** {entry.carry_forward}\n"
    )


def _log_failure(
    entry: GoldEntry,
    target: Path,
    error: str,
    caller_stack: str,
    *,
    store=None,
) -> bool:
    """Insert into gold_write_failures. Fault-tolerant; non-fatal on failure."""
    if store is None:
        try:
            from memory.store_back import SentinelStoreBack
            store = SentinelStoreBack._get_global_instance()
        except Exception as e:
            logger.warning("gold_writer: store init failed (non-fatal): %s", e)
            return False
    if store is None:
        return False
    conn = store._get_conn()
    if conn is None:
        return False
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO gold_write_failures
               (target_path, error, caller_stack, payload_jsonb)
               VALUES (%s, %s, %s, %s::jsonb)""",
            (
                str(target),
                error[:512],
                caller_stack[:2048],
                _payload_json(entry),
            ),
        )
        conn.commit()
        cur.close()
        return True
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.warning("gold_writer: log_failure DB write failed (non-fatal): %s", e)
        return False
    finally:
        store._put_conn(conn)


def _payload_json(entry: GoldEntry) -> str:
    import json
    return json.dumps(
        {
            "topic": entry.topic,
            "iso_date": entry.iso_date,
            "matter": entry.matter,
        }
    )
