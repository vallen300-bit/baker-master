"""GOLD_COMMENT_WORKFLOW_1 — Cortex agent-drafted proposed-gold writes.

Cortex (when M2 lands) imports this module ONLY. Never imports gold_writer.

Writes go to a `## Proposed Gold (agent-drafted)` section at the BOTTOM of
the target Gold file (matter or global). Director ratifies by manually
moving entries up. No auto-promote in V1.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("baker.gold_proposer")

PROPOSED_HEADER = "## Proposed Gold (agent-drafted)"


@dataclass(frozen=True)
class ProposedGoldEntry:
    iso_date: str
    topic: str
    proposed_resolution: str
    proposer: str = "cortex-3t"
    cortex_cycle_id: Optional[str] = None
    confidence: float = 0.0  # 0.0–1.0


def propose(
    entry: ProposedGoldEntry,
    *,
    matter: Optional[str] = None,
    vault_root: Optional[Path] = None,
) -> Path:
    """Append a proposed-gold entry. Never modifies ratified entries.

    Per Hybrid C V1, agent-drafted entries are surfaced for Director review
    only — Q3 ratified `surface all, sorted by confidence`. No auto-promote.

    Args:
        entry: ProposedGoldEntry with iso_date, topic, proposed_resolution.
        matter: canonical slug or None for global.
        vault_root: override BAKER_VAULT_PATH (mainly for tests).

    Returns:
        Path of the file written.
    """
    if vault_root is None:
        vault_root = Path(
            os.environ.get("BAKER_VAULT_PATH", str(Path.home() / "baker-vault"))
        )
    target = _resolve_target(matter, vault_root)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not target.exists():
        target.write_text(PROPOSED_HEADER + "\n", encoding="utf-8")
    elif PROPOSED_HEADER not in target.read_text(encoding="utf-8"):
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n\n" + PROPOSED_HEADER + "\n")

    block = _render_proposed(entry)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write("\n" + block + "\n")
    logger.info(
        "gold_proposer.propose: wrote %s (proposer=%s confidence=%.2f)",
        target,
        entry.proposer,
        entry.confidence,
    )
    return target


def _resolve_target(matter: Optional[str], vault_root: Path) -> Path:
    if matter is None:
        return vault_root / "_ops" / "director-gold-global.md"
    from kbl import slug_registry
    if not slug_registry.is_canonical(matter):
        raise ValueError(f"matter slug {matter!r} not canonical")
    return vault_root / "wiki" / "matters" / matter / "proposed-gold.md"


def _render_proposed(entry: ProposedGoldEntry) -> str:
    cycle = (
        f"\n**Cycle:** {entry.cortex_cycle_id}" if entry.cortex_cycle_id else ""
    )
    return (
        f"### {entry.iso_date} — {entry.topic}\n\n"
        f"**Proposer:** {entry.proposer} "
        f"(confidence {entry.confidence:.2f}){cycle}\n\n"
        f"**Proposed resolution:** {entry.proposed_resolution}\n"
    )
