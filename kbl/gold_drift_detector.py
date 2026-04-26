"""GOLD_COMMENT_WORKFLOW_1 — drift detector for Gold writes.

Two surfaces:
  1. validate_entry(entry, target) — pre-write check called by gold_writer.append.
  2. audit_all(vault_root) — full-corpus scan called by gold_audit_sentinel weekly.

DriftIssue codes:
  SCHEMA            — malformed entry / missing required field / bad date format
  DV_ONLY           — ratified entry missing "DV." initials
  SLUG_UNKNOWN      — matter slug not in slugs.yml
  MATERIAL_CONFLICT — same topic_key as a prior entry in target file
  ORPHAN_PROPOSAL   — proposed-gold entry > 30d unratified

Pure module — no DB writes. Caller (gold_writer / audit job) handles persistence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
H2_LINE_RE = re.compile(r"^##\s+(.*)$")
H3_LINE_RE = re.compile(r"^###\s+(.*)$")
PROPOSED_HEADER_RE = re.compile(r"^##\s+Proposed Gold\b", re.IGNORECASE)
DV_INITIALS_RE = re.compile(r"\bDV\.\s*$", re.MULTILINE)
ORPHAN_PROPOSAL_DAYS = 30


@dataclass(frozen=True)
class DriftIssue:
    code: str
    message: str
    file_path: Optional[str] = None


def _topic_key(title: str) -> str:
    """Lowercase noun-phrase key. V1 deterministic; V2 will use LLM extraction."""
    title = re.sub(r"^\s*\d{4}-\d{2}-\d{2}\s*[—-]?\s*", "", title)
    return " ".join(title.lower().split())


def validate_entry(entry, target: Path) -> list[DriftIssue]:
    """Pre-write validation called by gold_writer.append before file write.

    Args:
        entry: GoldEntry-shaped object with iso_date, topic, ratification_quote,
            background, resolution, authority_chain, carry_forward, matter.
        target: Path of the file the entry will be appended to.

    Returns:
        List of DriftIssue (empty list = clean).
    """
    issues: list[DriftIssue] = []

    iso_date = getattr(entry, "iso_date", "") or ""
    if not ISO_DATE_RE.match(iso_date):
        issues.append(
            DriftIssue("SCHEMA", f"iso_date must be YYYY-MM-DD (got {iso_date!r})")
        )

    for f in ("topic", "ratification_quote", "resolution", "authority_chain"):
        if not getattr(entry, f, ""):
            issues.append(DriftIssue("SCHEMA", f"missing required field: {f}"))

    # DV_ONLY at validate_entry is belt-and-braces only: gold_writer's
    # renderer auto-appends "DV." when missing, so the file written is
    # always DV-tagged. We DO NOT flag a quote lacking DV. here — that
    # would block legitimate writer.append() calls. The audit_all path
    # catches manual file writes that bypass the renderer.

    matter = getattr(entry, "matter", None)
    if matter:
        from kbl import slug_registry
        if not slug_registry.is_canonical(matter):
            issues.append(
                DriftIssue("SLUG_UNKNOWN", f"matter slug {matter!r} not in slugs.yml")
            )

    topic = getattr(entry, "topic", "") or ""
    if topic and target.exists():
        new_key = _topic_key(topic)
        for existing_topic in _h2_topics(target.read_text(encoding="utf-8")):
            if _topic_key(existing_topic) == new_key:
                issues.append(
                    DriftIssue(
                        "MATERIAL_CONFLICT",
                        f"topic_key {new_key!r} matches prior entry: {existing_topic[:120]}",
                        str(target),
                    )
                )
                break

    return issues


def audit_all(vault_root: Path) -> list[DriftIssue]:
    """Full-corpus audit called by gold_audit_sentinel weekly.

    Scans `_ops/director-gold-global.md` + every `wiki/matters/*/gold.md` and
    `wiki/matters/*/proposed-gold.md`. Returns aggregated DriftIssue list.
    """
    issues: list[DriftIssue] = []

    global_file = vault_root / "_ops" / "director-gold-global.md"
    if global_file.exists():
        issues.extend(_audit_ratified_file(global_file))

    matters_dir = vault_root / "wiki" / "matters"
    if matters_dir.is_dir():
        for matter_dir in sorted(matters_dir.iterdir()):
            if not matter_dir.is_dir():
                continue
            gold_file = matter_dir / "gold.md"
            if gold_file.exists():
                issues.extend(_audit_ratified_file(gold_file))
            proposed = matter_dir / "proposed-gold.md"
            if proposed.exists():
                issues.extend(_audit_proposed_file(proposed))

    return issues


def _has_dv_initials(text: str) -> bool:
    return bool(DV_INITIALS_RE.search(text))


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter so H2 scan only sees body."""
    if content.startswith("---\n"):
        end = content.find("\n---\n", 4)
        if end > 0:
            return content[end + 5 :]
    return content


def _h2_topics(content: str) -> Iterable[str]:
    """Yield H2 titles from a markdown file (skipping any '## Proposed Gold' section)."""
    body = _strip_frontmatter(content)
    in_proposed = False
    for line in body.splitlines():
        if PROPOSED_HEADER_RE.match(line):
            in_proposed = True
            continue
        if in_proposed:
            continue
        m = H2_LINE_RE.match(line)
        if m:
            yield m.group(1).strip()


def _audit_ratified_file(path: Path) -> list[DriftIssue]:
    """Scan one ratified Gold file for SCHEMA / DV_ONLY / MATERIAL_CONFLICT issues.

    Splits the body into per-H2 entries and checks each.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [DriftIssue("SCHEMA", f"could not read {path}: {e}", str(path))]

    body = _strip_frontmatter(text)
    issues: list[DriftIssue] = []
    seen_topic_keys: dict[str, str] = {}

    entries = _split_entries(body)
    for header, block in entries:
        if PROPOSED_HEADER_RE.match("## " + header):
            break
        # Only audit H2s that look like ratified entries (YYYY-MM-DD prefix).
        # Structural headers like "## Gold" or "## Candidates" in scaffold files
        # are skipped — they are document structure, not entries.
        date_match = re.match(r"^\s*(\d{4}-\d{2}-\d{2})\s*[—-]", header)
        if not date_match:
            continue
        if not _has_dv_initials(block):
            issues.append(
                DriftIssue(
                    "DV_ONLY",
                    f"ratified entry missing DV. initials: {header[:80]}",
                    str(path),
                )
            )
        key = _topic_key(header)
        if key and key in seen_topic_keys:
            issues.append(
                DriftIssue(
                    "MATERIAL_CONFLICT",
                    f"duplicate topic_key {key!r}: {header[:80]} (prior: {seen_topic_keys[key][:80]})",
                    str(path),
                )
            )
        else:
            seen_topic_keys[key] = header

    return issues


def _audit_proposed_file(path: Path) -> list[DriftIssue]:
    """Scan proposed-gold.md for ORPHAN_PROPOSAL (>30d unratified)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        return [DriftIssue("SCHEMA", f"could not read {path}: {e}", str(path))]

    issues: list[DriftIssue] = []
    now = datetime.now(timezone.utc).date()
    body = _strip_frontmatter(text)

    for line in body.splitlines():
        m = H3_LINE_RE.match(line)
        if not m:
            continue
        header = m.group(1).strip()
        date_match = re.match(r"^\s*(\d{4}-\d{2}-\d{2})\b", header)
        if not date_match:
            continue
        try:
            entry_date = datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
        except ValueError:
            continue
        age_days = (now - entry_date).days
        if age_days > ORPHAN_PROPOSAL_DAYS:
            issues.append(
                DriftIssue(
                    "ORPHAN_PROPOSAL",
                    f"proposed entry unratified for {age_days}d: {header[:80]}",
                    str(path),
                )
            )

    return issues


def _split_entries(body: str) -> list[tuple[str, str]]:
    """Split body into [(header_text, block_with_header), ...] keyed on H2."""
    out: list[tuple[str, str]] = []
    current_header: Optional[str] = None
    current_lines: list[str] = []
    for line in body.splitlines():
        m = H2_LINE_RE.match(line)
        if m:
            if current_header is not None:
                out.append((current_header, "\n".join(current_lines)))
            current_header = m.group(1).strip()
            current_lines = [line]
        else:
            if current_header is not None:
                current_lines.append(line)
    if current_header is not None:
        out.append((current_header, "\n".join(current_lines)))
    return out
