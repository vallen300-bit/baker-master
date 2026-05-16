"""Curated wiki reader — additive read-path for per-matter PM capabilities.

Adds the curated knowledge layer (`<baker-vault>/wiki/matters/<slug>/curated/*.md`)
to the AO-PM (and future per-matter-PM) capability context. The DB state_json
update path is slower than Director's curated-wiki edits, so capabilities that
read only state_json give stale answers on cycle facts (Q2-2026 capital-call
tranche receipts surfaced this on 2026-05-16).

This module is read-only and stateless. Slug input is sanitized against:
  1. Regex `^[a-z0-9-]+$` — blocks path traversal characters.
  2. Allow-list — `slug_registry.normalize(slug) is not None`, i.e. the slug
     must be a known canonical or alias in `slugs.yml`. (Curated wiki dirs may
     use alias names, e.g. `wiki/matters/oskolkov/` for canonical `ao`, so we
     allow aliases through but reject anything outside the registry.)
  3. Path resolution — final resolved path must be under
     `<BAKER_VAULT_PATH>/wiki/matters/` (string-prefix on resolved paths;
     defends against symlink escape).

Brief: BRIEF_AO_PM_READ_CURATED_WIKI_1 (2026-05-16, AH2).
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Default per-file char cap (~2K tokens at 4 chars/token); enough to capture
# the Bottom Line + first 1-2 sections of a curated file, which is where dated
# cycle facts live.
DEFAULT_CHAR_CAP = 8000

# Default curated files to surface in PM context. Brief acceptance:
#   - 00_overview.md (Bottom Line / cycle posture)
#   - 02_money.md (drawdown status / dated receipts)
DEFAULT_FILES = ("00_overview.md", "02_money.md")

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class CuratedWikiError(ValueError):
    """Raised when a slug fails validation or path resolution escapes vault."""


@dataclass(frozen=True)
class CuratedFile:
    path: str            # relative path under baker-vault (for citation labels)
    body: str            # raw markdown content, char-capped
    last_curated_at: Optional[str]  # frontmatter `last_curated_at` if present
    truncated: bool      # True if body was capped below original length


def _validate_slug(slug: str) -> None:
    """Two-gate slug validation: regex + registry allow-list."""
    if not isinstance(slug, str) or not slug:
        raise CuratedWikiError(f"slug must be a non-empty string (got {slug!r})")
    if not _SLUG_PATTERN.match(slug):
        raise CuratedWikiError(
            f"slug {slug!r} contains disallowed characters; "
            f"must match {_SLUG_PATTERN.pattern}"
        )
    try:
        from kbl import slug_registry
    except ImportError as e:
        raise CuratedWikiError(f"slug_registry unavailable: {e}") from e
    if slug_registry.normalize(slug) is None:
        raise CuratedWikiError(
            f"slug {slug!r} is not a known canonical slug or alias in slugs.yml"
        )


def _resolve_vault_root() -> Path:
    vault = os.environ.get("BAKER_VAULT_PATH")
    if not vault:
        raise CuratedWikiError(
            "BAKER_VAULT_PATH env var not set — required to resolve curated wiki paths"
        )
    return Path(vault).expanduser().resolve()


def _parse_last_curated_at(body: str) -> Optional[str]:
    """Lift `last_curated_at:` from YAML frontmatter if present.

    Curated files use a 4-line+ frontmatter block delimited by `---` on its
    own line. Minimal parse — no PyYAML dep needed here; we only need one
    string field, and matching is line-based to keep the parser cheap and
    failure-tolerant on malformed frontmatter.
    """
    if not body.startswith("---"):
        return None
    lines = body.splitlines()
    if len(lines) < 2:
        return None
    # 30-line cap: real curated files have ≤10-line frontmatter; cap defends
    # against a pathological body that has no closing `---` (e.g. partially
    # written file) without scanning the whole body.
    for i in range(1, min(len(lines), 30)):
        if lines[i].strip() == "---":
            break
        if ":" in lines[i]:
            key, _, value = lines[i].partition(":")
            if key.strip() == "last_curated_at":
                return value.strip().strip('"').strip("'") or None
    return None


def read_curated(
    slug: str,
    files: Optional[tuple] = None,
    char_cap: int = DEFAULT_CHAR_CAP,
) -> list[CuratedFile]:
    """Return curated files for `slug`, char-capped, in the requested order.

    Args:
        slug: matter slug (e.g. "capital-call", "oskolkov"). Must pass the
              two-gate validation in `_validate_slug`.
        files: tuple of filenames under `curated/` to read. Each filename
               must match `^[A-Za-z0-9_.-]+\\.md$` (no path separators).
               Defaults to DEFAULT_FILES.
        char_cap: max chars per file; longer bodies are truncated with a
                  trailing marker. Pass 0 to disable capping.

    Returns:
        List of `CuratedFile` for files that exist + read cleanly. Missing
        files are skipped (graceful no-op per brief). Empty list if nothing
        readable — caller must treat as "no curated context" not as error.

    Raises:
        CuratedWikiError on slug validation failure or vault env unset.
    """
    _validate_slug(slug)

    requested = files or DEFAULT_FILES
    # Require leading alphanumeric to block dot-only names like '.md' / '..md'.
    safe_filename = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.md$")
    for fname in requested:
        if not safe_filename.match(fname):
            raise CuratedWikiError(f"unsafe curated filename {fname!r}")

    vault_root = _resolve_vault_root()
    matters_root = vault_root / "wiki" / "matters"
    matter_dir = (matters_root / slug / "curated").resolve()

    # String-prefix containment check on resolved paths defeats symlink escape
    # without relying on Path.is_relative_to (added 3.9 but cleaner to be
    # explicit + portable).
    matters_root_resolved = matters_root.resolve()
    if not str(matter_dir).startswith(str(matters_root_resolved) + os.sep) \
            and matter_dir != matters_root_resolved:
        raise CuratedWikiError(
            f"resolved curated dir {matter_dir} escapes {matters_root_resolved}"
        )

    if not matter_dir.is_dir():
        logger.info("curated_wiki: dir not present for slug=%s (%s)", slug, matter_dir)
        return []

    out: list[CuratedFile] = []
    for fname in requested:
        # File-level symlink containment: matter_dir containment is verified
        # above, but a symlink INSIDE curated/ can still point outside the
        # vault. is_file()/read_text() follow symlinks, so resolve + re-check
        # before any filesystem access on the path.
        fpath = (matter_dir / fname).resolve()
        if not str(fpath).startswith(str(matters_root_resolved) + os.sep):
            logger.warning(
                "curated_wiki: file %s escapes vault, skipping", fpath
            )
            continue
        if not fpath.is_file():
            continue
        try:
            body = fpath.read_text(encoding="utf-8")
        except OSError as e:
            logger.warning("curated_wiki: read failed %s: %s", fpath, e)
            continue
        truncated = False
        if char_cap and len(body) > char_cap:
            body = body[:char_cap] + "\n\n[...truncated; full file in vault...]"
            truncated = True
        rel = f"wiki/matters/{slug}/curated/{fname}"
        out.append(
            CuratedFile(
                path=rel,
                body=body,
                last_curated_at=_parse_last_curated_at(body),
                truncated=truncated,
            )
        )
    return out


def format_for_prompt(
    slug: str,
    files: Optional[tuple] = None,
    char_cap: int = DEFAULT_CHAR_CAP,
) -> str:
    """Convenience wrapper: read curated files and format as prompt block.

    Returns an empty string if nothing is readable, so callers can
    `if block: prompt += block` without a conditional read.
    """
    try:
        files_data = read_curated(slug, files=files, char_cap=char_cap)
    except CuratedWikiError as e:
        logger.warning("curated_wiki: skip slug=%s reason=%s", slug, e)
        return ""
    if not files_data:
        return ""
    parts = []
    for f in files_data:
        header = f"[CURATED WIKI: {f.path}"
        if f.last_curated_at:
            header += f" | last_curated_at: {f.last_curated_at}"
        header += "]"
        parts.append(f"{header}\n{f.body}")
    return "\n\n---\n\n".join(parts)
