"""Read-only baker-vault mirror on Render — the transport Cowork uses.

Populated at FastAPI startup via ``ensure_mirror()`` and refreshed every
``VAULT_SYNC_INTERVAL_SECONDS`` (default 300 s, floor 60 s) by the
``vault_sync_tick`` APScheduler job.

Scope invariants (brief §Key Constraints):

* **Read-only.** ``sync_tick()`` only ``git pull``s; never pushes.
* **Path safety is load-bearing.** Every ``baker_vault_read`` /
  ``baker_vault_list`` call resolves its path with ``realpath`` and
  asserts the result stays inside ``{mirror_root}/_ops/``. A traversal
  regression would give Cowork arbitrary file read on Render's
  container.
* **Extension + size caps.** Only ``.md`` / ``.yml`` / ``.yaml`` /
  ``.txt`` under ``_ops/`` return content. 128 KB file-size cap; oversize
  returns metadata only with ``truncated: true``.

See ``briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md`` for the
full ratified design.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("vault_mirror")

DEFAULT_MIRROR_PATH = "/opt/render/project/src/baker-vault-mirror"
DEFAULT_REMOTE = "https://github.com/vallen300-bit/baker-vault.git"
DEFAULT_SYNC_INTERVAL_SECONDS = 300
SYNC_INTERVAL_FLOOR_SECONDS = 60

# MCP-tool limits. Treat as contract — the tests pin them.
MAX_FILE_BYTES = 128 * 1024
ALLOWED_EXTENSIONS = frozenset([".md", ".yml", ".yaml", ".txt"])
OPS_PREFIX = "_ops/"

# Module-level last-pull timestamp for /health.
_last_pull_at: Optional[datetime] = None
# Serialize git ops — ensure_mirror + sync_tick don't race if scheduler
# fires mid-startup.
_git_lock = threading.Lock()


# --------------------------------------------------------------------------
# Config accessors
# --------------------------------------------------------------------------


def mirror_path() -> Path:
    """Absolute path to the mirror root. Env-overridable for tests."""
    return Path(os.environ.get("VAULT_MIRROR_PATH", DEFAULT_MIRROR_PATH)).resolve()


def _remote_url() -> str:
    return os.environ.get("VAULT_MIRROR_REMOTE", DEFAULT_REMOTE)


def sync_interval_seconds() -> int:
    raw = os.environ.get(
        "VAULT_SYNC_INTERVAL_SECONDS", str(DEFAULT_SYNC_INTERVAL_SECONDS)
    )
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_SYNC_INTERVAL_SECONDS
    if value < SYNC_INTERVAL_FLOOR_SECONDS:
        logger.warning(
            "VAULT_SYNC_INTERVAL_SECONDS=%s below %ss floor; clamping",
            raw,
            SYNC_INTERVAL_FLOOR_SECONDS,
        )
        value = SYNC_INTERVAL_FLOOR_SECONDS
    return value


# --------------------------------------------------------------------------
# Mirror management
# --------------------------------------------------------------------------


def _run_git(args: list[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """Run ``git <args>`` with a 30 s timeout.

    Raises ``subprocess.CalledProcessError`` on non-zero exit so callers
    can decide whether to escalate. Stdout/stderr captured as text.
    """
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _is_git_repo(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        _run_git(["rev-parse", "--git-dir"], cwd=path)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def ensure_mirror() -> None:
    """Startup hook: clone the vault if missing; otherwise pull fast-forward.

    Blocking. Raises ``RuntimeError`` on unrecoverable clone failure —
    startup should fail loud so a missing mirror can't go unnoticed.
    Pull failures are WARN-logged but non-fatal (treat as transient —
    the next ``sync_tick`` retries).
    """
    path = mirror_path()
    with _git_lock:
        if _is_git_repo(path):
            try:
                _run_git(["pull", "--ff-only", "origin", "main"], cwd=path)
                _record_pull()
                logger.info("vault_mirror: pulled main at %s", path)
            except subprocess.CalledProcessError as e:
                logger.warning(
                    "vault_mirror: pull failed (non-fatal on startup): %s",
                    e.stderr or e,
                )
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run_git(["clone", "--depth", "1", _remote_url(), str(path)])
            _record_pull()
            logger.info("vault_mirror: cloned to %s", path)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"vault_mirror: initial clone failed: {e.stderr or e}"
            ) from e


def sync_tick() -> None:
    """APScheduler job body: pull the mirror; swallow failures as WARN.

    Idempotent. Safe to call concurrently with ``ensure_mirror`` — the
    module-level lock serializes git operations.
    """
    path = mirror_path()
    with _git_lock:
        if not _is_git_repo(path):
            # Mirror vanished between startup and this tick — re-clone
            # under the same held lock so startup and tick paths agree.
            logger.warning(
                "vault_mirror: sync_tick — mirror missing at %s, re-cloning",
                path,
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                _run_git(["clone", "--depth", "1", _remote_url(), str(path)])
                _record_pull()
                logger.info("vault_mirror: sync_tick re-clone succeeded")
            except subprocess.CalledProcessError as e:
                logger.warning(
                    "vault_mirror: sync_tick re-clone failed: %s", e.stderr or e
                )
            return
        try:
            _run_git(["pull", "--ff-only", "origin", "main"], cwd=path)
            _record_pull()
        except subprocess.CalledProcessError as e:
            logger.warning("vault_mirror: sync_tick pull failed: %s", e.stderr or e)


def _record_pull() -> None:
    global _last_pull_at
    _last_pull_at = datetime.now(timezone.utc)


def _head_commit_sha() -> Optional[str]:
    path = mirror_path()
    if not _is_git_repo(path):
        return None
    try:
        result = _run_git(["rev-parse", "HEAD"], cwd=path)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def _last_commit_for_path(rel_path: str) -> Optional[str]:
    path = mirror_path()
    if not _is_git_repo(path):
        return None
    try:
        result = _run_git(
            ["log", "-1", "--format=%H", "--", rel_path], cwd=path
        )
        sha = result.stdout.strip()
        return sha or None
    except subprocess.CalledProcessError:
        return None


def mirror_status() -> dict:
    """Return ``{vault_mirror_last_pull, vault_mirror_commit_sha}`` for /health."""
    return {
        "vault_mirror_last_pull": (
            _last_pull_at.isoformat() if _last_pull_at else None
        ),
        "vault_mirror_commit_sha": _head_commit_sha(),
    }


# --------------------------------------------------------------------------
# Path safety + read/list primitives (shared by MCP tools)
# --------------------------------------------------------------------------


class VaultPathError(ValueError):
    """Raised when a caller-supplied path violates the `_ops/` scope."""


def _normalize_and_resolve(rel_path: str) -> Path:
    """Validate + resolve a caller-supplied relative path.

    Invariants on return:
      * result is absolute
      * result lives strictly inside ``{mirror_root}/_ops/``
      * no symlink escapes (``realpath`` folds those)

    Raises ``VaultPathError`` otherwise. Does NOT require the file to
    exist — callers handle that.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise VaultPathError("path must be a non-empty string")

    normalized = rel_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        raise VaultPathError("path must be relative, not absolute")
    if not normalized.startswith(OPS_PREFIX):
        raise VaultPathError(f"path must start with '{OPS_PREFIX}'")

    root = mirror_path()
    ops_root = (root / "_ops").resolve()
    # ``resolve`` on a nonexistent path still folds .. segments.
    resolved = (root / normalized).resolve()

    # ``is_relative_to`` (py3.9+) — strict containment incl. symlink escapes.
    if not (resolved == ops_root or ops_root in resolved.parents):
        raise VaultPathError(
            f"path escapes _ops/ scope: {rel_path!r}"
        )

    return resolved


def _ext_allowed(p: Path) -> bool:
    return p.suffix.lower() in ALLOWED_EXTENSIONS


def list_ops_files(prefix: str = OPS_PREFIX) -> list[str]:
    """Return relative paths for files under ``prefix`` with allowed extensions.

    ``prefix`` must start with ``_ops/``. Result paths are relative to
    the mirror root and sorted for deterministic output.
    """
    if not prefix:
        prefix = OPS_PREFIX
    resolved = _normalize_and_resolve(prefix)
    root = mirror_path()

    if not resolved.exists():
        return []

    results: list[str] = []
    if resolved.is_file():
        if _ext_allowed(resolved):
            results.append(str(resolved.relative_to(root)))
        return results

    for candidate in sorted(resolved.rglob("*")):
        if not candidate.is_file():
            continue
        if not _ext_allowed(candidate):
            continue
        # Re-resolve every hit — guards against symlinks inside the tree
        # pointing outside _ops/.
        try:
            resolved_hit = candidate.resolve()
        except OSError:
            continue
        ops_root = (root / "_ops").resolve()
        if not (resolved_hit == ops_root or ops_root in resolved_hit.parents):
            continue
        results.append(str(candidate.relative_to(root)))
    return results


def read_ops_file(rel_path: str) -> dict:
    """Return ``{path, content_utf8, sha256, bytes, last_commit_sha}``.

    Size > ``MAX_FILE_BYTES`` returns metadata only with
    ``truncated: True`` and an empty ``content_utf8``. Missing file
    returns a 404-shaped dict (``error: 'not_found'``) rather than
    raising — callers (MCP dispatch) translate to a user-facing error
    without crashing the server.

    Raises ``VaultPathError`` on any scope / extension violation —
    those are programmer/attack errors, not expected runtime states.
    """
    resolved = _normalize_and_resolve(rel_path)
    if not _ext_allowed(resolved):
        raise VaultPathError(
            f"extension not allowed: {resolved.suffix or '(none)'}"
        )

    root = mirror_path()
    rel_from_root = resolved.relative_to(root)

    if not resolved.exists() or not resolved.is_file():
        return {
            "path": str(rel_from_root),
            "error": "not_found",
        }

    size = resolved.stat().st_size
    last_commit = _last_commit_for_path(str(rel_from_root))

    if size > MAX_FILE_BYTES:
        return {
            "path": str(rel_from_root),
            "bytes": size,
            "truncated": True,
            "content_utf8": "",
            "sha256": None,
            "last_commit_sha": last_commit,
        }

    data = resolved.read_bytes()
    content = data.decode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    return {
        "path": str(rel_from_root),
        "bytes": size,
        "content_utf8": content,
        "sha256": sha,
        "truncated": False,
        "last_commit_sha": last_commit,
    }
