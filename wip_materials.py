"""Read-only WIP-materials browser backing the cockpit "Work in progress" panel.

Serves HTML / Markdown artifacts from the vault mirror's
``wiki/_wip/<topic>/`` subtree (BRISEN_LAB_WIP_MATERIALS_PANEL_1). v1 is
read-only: files arrive via vault git, never written/edited/deleted here.

Path safety is load-bearing. Rather than reimplement traversal defence, this
module REUSES ``vault_mirror._normalize_and_resolve`` — the already-reviewed
guard that folds ``..``, rejects absolute paths, resolves symlinks via
``realpath``, and confines the result to the ``wiki/`` allowed-prefix subtree —
then layers two STRICTER checks on top:

  1. WIP_ROOT containment — the resolved real path must live inside
     ``<mirror>/wiki/_wip`` specifically, not merely inside ``wiki/``. This
     blocks ``wiki/_ops``-style hops that ``_normalize_and_resolve`` would
     otherwise permit.
  2. A tighter extension allowlist — only ``.html`` / ``.md`` are servable
     here (vault_mirror's allowlist is broader: ``.yml`` / ``.txt`` etc).

WIP_ROOT is derived from ``vault_mirror.mirror_path()`` — never hardcode
``~/baker-vault`` (brief §Key Constraints).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import vault_mirror

logger = logging.getLogger("wip_materials")

# Relative prefix inside the vault mirror. Subfolder = topic.
WIP_REL_PREFIX = "wiki/_wip"

# v1 serve-allowlist — INTENTIONALLY tighter than
# ``vault_mirror.ALLOWED_EXTENSIONS`` (which also allows .yml/.yaml/.txt).
WIP_ALLOWED_EXTENSIONS = frozenset([".html", ".md"])

# Bounded listing (brief: cap 200) so a runaway topic folder can't blow the
# response or the page render.
MAX_FILES = 200


def wip_root() -> Path:
    """Absolute, realpath-resolved WIP root inside the live vault mirror."""
    return (vault_mirror.mirror_path() / WIP_REL_PREFIX).resolve()


def _is_safe_segment(seg: str) -> bool:
    """True for a single safe path segment (topic folder or file name).

    Rejects anything that could enable traversal or hidden-file access:
    path separators, ``.``/``..``, embedded ``..``, NUL, and leading-dot
    dotfiles. Defence-in-depth ahead of the reused vault-mirror resolver —
    spaces and other printable chars are allowed (real vault filenames have
    them; they cannot escape the subtree).
    """
    if not isinstance(seg, str) or not seg:
        return False
    if seg in (".", ".."):
        return False
    if seg.startswith("."):
        return False
    if "/" in seg or "\\" in seg or "\x00" in seg:
        return False
    if ".." in seg:
        return False
    return True


def _contained(resolved: Path, root: Path) -> bool:
    """True iff ``resolved`` is ``root`` itself or strictly inside it."""
    return resolved == root or root in resolved.parents


def list_topics() -> list[str]:
    """Immediate subfolders of WIP_ROOT, sorted. ``[]`` on error / missing.

    Fault-tolerant: any FS error returns an empty list rather than raising,
    so the cockpit degrades to "no materials yet" instead of 500-ing.
    """
    try:
        root = wip_root()
        if not root.exists() or not root.is_dir():
            return []
        topics = [
            p.name
            for p in root.iterdir()
            if p.is_dir() and _is_safe_segment(p.name)
        ]
        return sorted(topics)
    except OSError:
        logger.warning("wip_materials: list_topics failed", exc_info=True)
        return []


def list_files(topic: str) -> list[dict]:
    """``.html`` / ``.md`` files in ``WIP_ROOT/<topic>/``, sorted by name.

    Each item is ``{"name": str, "modified": iso8601|None}``. Bounded to
    ``MAX_FILES``. ``[]`` on unsafe topic / missing folder / any FS error.
    """
    if not _is_safe_segment(topic):
        return []
    try:
        root = wip_root()
        topic_dir = (root / topic).resolve()
        # Re-assert containment after resolve() in case the topic folder is a
        # symlink pointing outside WIP_ROOT.
        if not _contained(topic_dir, root) or not topic_dir.is_dir():
            return []
        files: list[dict] = []
        for p in sorted(topic_dir.iterdir()):
            if not p.is_file():
                continue
            if not _is_safe_segment(p.name):  # skip dotfiles / odd names
                continue
            if p.suffix.lower() not in WIP_ALLOWED_EXTENSIONS:
                continue
            try:
                mtime = p.stat().st_mtime
                modified = datetime.fromtimestamp(
                    mtime, timezone.utc
                ).isoformat()
            except OSError:
                modified = None
            files.append({"name": p.name, "modified": modified})
            if len(files) >= MAX_FILES:
                break
        return files
    except OSError:
        logger.warning(
            "wip_materials: list_files failed for topic=%r", topic, exc_info=True
        )
        return []


def safe_path(topic: str, name: str) -> Optional[Path]:
    """Resolve ``WIP_ROOT/<topic>/<name>`` with full traversal + ext guard.

    Returns the resolved real ``Path`` ONLY when it is an existing file,
    strictly inside ``WIP_ROOT``, with an allowed (``.html``/``.md``)
    extension. Returns ``None`` on ANY violation — the caller serves a 404.

    Layers three independent checks, any one of which is sufficient:
      * bare-segment validation (no separators / ``..`` / dotfiles),
      * the reused ``vault_mirror._normalize_and_resolve`` (``wiki/`` prefix,
        symlink-fold, absolute/``..`` rejection),
      * WIP_ROOT containment + extension allowlist.
    """
    if not _is_safe_segment(topic) or not _is_safe_segment(name):
        return None
    if Path(name).suffix.lower() not in WIP_ALLOWED_EXTENSIONS:
        return None

    rel = f"{WIP_REL_PREFIX}/{topic}/{name}"
    try:
        resolved = vault_mirror._normalize_and_resolve(rel)
    except vault_mirror.VaultPathError:
        return None
    except Exception:  # defensive — never leak an FS/resolve error to caller
        logger.warning("wip_materials: safe_path resolve failed", exc_info=True)
        return None

    root = wip_root()
    if not _contained(resolved, root):
        return None
    if resolved.suffix.lower() not in WIP_ALLOWED_EXTENSIONS:
        return None
    try:
        if not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved
