"""Read-only baker-vault mirror on Render — the transport Cowork uses.

Populated at FastAPI startup via ``ensure_mirror()`` and refreshed every
``VAULT_SYNC_INTERVAL_SECONDS`` (default 300 s, floor 60 s) by the
``vault_sync_tick`` APScheduler job.

Scope invariants (brief §Key Constraints):

* **Read-only.** ``sync_tick()`` only ``git pull``s; never pushes.
* **Path safety is load-bearing.** Every ``baker_vault_read`` /
  ``baker_vault_list`` call resolves its path with ``realpath`` and
  asserts the result stays inside one of ``ALLOWED_PREFIXES`` subtrees
  (``_ops/`` or ``wiki/``). A traversal regression would give Cowork
  arbitrary file read on Render's container.
* **Extension + size caps.** Only ``.md`` / ``.yml`` / ``.yaml`` /
  ``.txt`` under an allowed prefix return content. 128 KB file-size
  cap; oversize returns metadata only with ``truncated: true``.

See ``briefs/BRIEF_SOT_OBSIDIAN_1_PHASE_D_VAULT_READ.md`` for the
original ratified design and
``briefs/BRIEF_BAKER_VAULT_READ_WIKI_SCOPE_1.md`` for the
2026-04-30 ``wiki/`` scope extension.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
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
ALLOWED_EXTENSIONS = frozenset([".md", ".yml", ".yaml", ".txt", ".html", ".htm"])

# Allowed read-scope prefixes. Originally ``_ops/`` only
# (SOT_OBSIDIAN_1_PHASE_D); extended 2026-04-30 with ``wiki/`` for
# Desk-skill dossier reads (BAKER_VAULT_READ_WIKI_SCOPE_1). Any new
# prefix MUST keep realpath + symlink + extension + size invariants.
ALLOWED_PREFIXES = frozenset(["_ops/", "wiki/"])

# Back-compat alias — some imports may still reference ``OPS_PREFIX``.
# Keep as a pointer to the canonical _ops prefix. Drop in a follow-up
# brief once all imports migrate.
OPS_PREFIX = "_ops/"

# Module-level last-pull timestamp for /health.
_last_pull_at: Optional[datetime] = None
# Serialize git ops — ensure_mirror + sync_tick don't race if the
# per-process sync thread fires mid-startup.
_git_lock = threading.Lock()

# Per-process sync thread state. The thread refreshes the local FS mirror
# every ``sync_interval_seconds`` so each Render replica stays current
# independent of the singleton scheduler lock. Previously the refresh
# was an APScheduler job inside ``triggers.embedded_scheduler`` —
# singleton-locked, which meant only the lock-holding replica pulled and
# every other replica served stale ``baker_vault_read`` results.
_sync_thread: Optional[threading.Thread] = None
_sync_thread_stop = threading.Event()
_sync_thread_lock = threading.Lock()


# --------------------------------------------------------------------------
# Config accessors
# --------------------------------------------------------------------------


def mirror_path() -> Path:
    """Absolute path to the mirror root. Env-overridable for tests."""
    return Path(os.environ.get("VAULT_MIRROR_PATH", DEFAULT_MIRROR_PATH)).resolve()


_TOKEN_URL_RE = re.compile(r"https://x-access-token:[^@\s]+@")


def _redact(text) -> str:
    """Strip tokenized URLs from text before logging.

    Git subprocess errors often echo the URL they tried to reach; that
    URL carries our ``GITHUB_TOKEN`` when private-repo auth is used.
    B3 review S1b: never write the token to Render's log stream.
    """
    if text is None:
        return ""
    return _TOKEN_URL_RE.sub("https://x-access-token:REDACTED@", str(text))


def _remote_url() -> str:
    """Resolve the clone URL. Override env wins, then token, then plain default.

    ``VAULT_MIRROR_REMOTE`` is the test/ops override (local path or a
    pre-authed URL). When absent and ``GITHUB_TOKEN`` is set — which is
    true on Render for baker-master via the auto-deploy wiring — rewrite
    to the ``x-access-token`` form so a private-repo clone authenticates.
    Falls back to the plain default only for local dev against a public
    mirror. B3 review S1b (2026-04-20).

    The tokenized URL is NEVER logged; callers log the host only.
    """
    override = os.environ.get("VAULT_MIRROR_REMOTE")
    if override:
        return override
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return (
            f"https://x-access-token:{token}"
            f"@github.com/vallen300-bit/baker-vault.git"
        )
    return DEFAULT_REMOTE


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
                    _redact(e.stderr or e),
                )
            return

        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run_git(["clone", "--depth", "1", _remote_url(), str(path)])
            _record_pull()
            logger.info("vault_mirror: cloned to %s", path)
        except subprocess.CalledProcessError as e:
            logger.error(
                "vault_mirror: initial clone failed (non-fatal — degraded mode, "
                "sync_tick will retry once auth restored): %s",
                _redact(e.stderr or e),
            )


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
                    "vault_mirror: sync_tick re-clone failed: %s", _redact(e.stderr or e)
                )
            return
        try:
            _run_git(["pull", "--ff-only", "origin", "main"], cwd=path)
            _record_pull()
        except subprocess.CalledProcessError as e:
            logger.warning("vault_mirror: sync_tick pull failed: %s", _redact(e.stderr or e))


def _record_pull() -> None:
    global _last_pull_at
    _last_pull_at = datetime.now(timezone.utc)


def _sync_loop(interval_seconds: int, stop_event: threading.Event) -> None:
    """Daemon-thread body: sleep, then ``sync_tick``, repeat until stop.

    Uses ``stop_event.wait`` for the sleep so ``stop_sync_thread`` can cut a
    pending tick promptly during tests / shutdown. The Event is passed in
    explicitly (per-thread) rather than read from the module global so a
    successor thread spawned after ``stop_sync_thread`` sees its own,
    isolated signal — no cross-instance leakage. Exceptions inside
    ``sync_tick`` are already swallowed-as-WARN by that function;
    defensive ``try`` here guards against unexpected raises (git binary
    missing, etc.) so the loop never dies silently. Uses
    ``logger.exception`` (not ``warning``) so the traceback is captured —
    silent-warn was the failure mode architect M1 / 2nd-pass L1 flagged on
    PR #193 and is the prime suspect for why the non-lock replica's
    ``vault_sync_thread_alive`` came back False in prod telemetry.
    """
    while True:
        if stop_event.wait(timeout=interval_seconds):
            return
        try:
            sync_tick()
        except Exception:
            logger.exception("vault_mirror: sync_loop tick raised")


def start_sync_thread(interval_seconds: Optional[int] = None) -> threading.Thread:
    """Start the per-process daemon thread that periodically pulls the mirror.

    Idempotent — a second call returns the existing live thread. Spawned
    once per process at FastAPI startup. Runs on EVERY Render replica
    (independent of the singleton scheduler lock) so each replica's
    local FS mirror stays current.

    Returns the live thread for testability.
    """
    global _sync_thread, _sync_thread_stop
    with _sync_thread_lock:
        if _sync_thread is not None and _sync_thread.is_alive():
            return _sync_thread
        interval = (
            interval_seconds if interval_seconds is not None else sync_interval_seconds()
        )
        # Fresh stop event per spawn — eliminates cross-instance signal
        # leakage between a stopping thread and its successor. Architect
        # M1 / 2nd-pass L1 (PR #195 follow-up).
        _sync_thread_stop = threading.Event()
        _sync_thread = threading.Thread(
            target=_sync_loop,
            args=(interval, _sync_thread_stop),
            name="vault_mirror_sync",
            daemon=True,
        )
        _sync_thread.start()
        logger.info(
            "vault_mirror: per-process sync thread started (every %ss)", interval
        )
        return _sync_thread


def stop_sync_thread(timeout: float = 5.0) -> None:
    """Signal the sync thread to exit and join. Used by tests + shutdown.

    Atomic-swap: snapshot + detach inside lock, signal + join the local
    handle outside lock so concurrent ``start_sync_thread`` is not
    blocked by the up-to-``timeout``-second join wait. Per-thread stop
    Event (each ``start_sync_thread`` allocates a fresh one) prevents
    signal-state leakage between a stopping thread and its successor.
    Architect M1 / 2nd-pass L1 (PR #195 follow-up).
    """
    global _sync_thread
    with _sync_thread_lock:
        stop_event = _sync_thread_stop
        thread = _sync_thread
        _sync_thread = None  # detach inside lock — concurrent start sees None
    stop_event.set()  # signal outside lock — wakes _sync_loop's wait()
    if thread is not None and thread.is_alive():
        thread.join(timeout=timeout)  # join outside lock — no concurrent-start block


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
    """Return ``{vault_mirror_last_pull, vault_mirror_commit_sha, vault_sync_thread_alive}`` for /health.

    ``vault_sync_thread_alive`` (added VAULT_MIRROR_NON_LOCK_REPLICA_HOTFIX_1
    2026-05-12): per-replica liveness signal. PR #193 moved the refresh into a
    per-process daemon thread; production telemetry showed the non-lock replica
    silently lacked the thread (spawn or first tick failing, exception swallowed
    by the defensive guard in ``_sync_loop``). Surfacing the bool on every
    /health hit lets operators distinguish "thread None" (spawn never happened)
    from "thread !alive" (loop died) from "thread alive but stale last_pull"
    (loop ticking but git failing).
    """
    # Local snapshot — eliminates TOCTOU between the is-not-None check
    # and the is_alive() call. Concurrent ``stop_sync_thread`` can null
    # ``_sync_thread`` between the two; without snapshot the second
    # access raises AttributeError, swallowed by /health's outer
    # try/except and surfacing as a one-poll false-negative. No lock
    # needed — CPython attribute reads are GIL-atomic and ``mirror_status``
    # is hot on the /health path; lock contention with thread-lifecycle
    # ops would serialize health behind start/stop. Architect M1 /
    # 2nd-pass L2 (PR #195 follow-up).
    thread = _sync_thread
    return {
        "vault_mirror_last_pull": (
            _last_pull_at.isoformat() if _last_pull_at else None
        ),
        "vault_mirror_commit_sha": _head_commit_sha(),
        "vault_sync_thread_alive": (
            thread is not None and thread.is_alive()
        ),
    }


# --------------------------------------------------------------------------
# Path safety + read/list primitives (shared by MCP tools)
# --------------------------------------------------------------------------


class VaultPathError(ValueError):
    """Raised when a caller-supplied path violates the allowed-prefix scope."""


def _normalize_and_resolve(rel_path: str) -> Path:
    """Validate + resolve a caller-supplied relative path.

    Invariants on return:
      * result is absolute
      * result lives strictly inside one of the ``ALLOWED_PREFIXES``
        subtrees (``_ops/`` or ``wiki/``)
      * no symlink escapes (``realpath`` folds those)

    Raises ``VaultPathError`` otherwise. Does NOT require the file to
    exist — callers handle that.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise VaultPathError("path must be a non-empty string")

    normalized = rel_path.replace("\\", "/").strip()
    if normalized.startswith("/"):
        raise VaultPathError("path must be relative, not absolute")

    matched_prefix: Optional[str] = None
    for prefix in ALLOWED_PREFIXES:
        if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
            matched_prefix = prefix
            break
    if matched_prefix is None:
        raise VaultPathError(
            f"path must start with one of {sorted(ALLOWED_PREFIXES)}; "
            f"got: {rel_path!r}"
        )

    root = mirror_path()
    prefix_root = (root / matched_prefix.rstrip("/")).resolve()
    # ``resolve`` on a nonexistent path still folds .. segments.
    resolved = (root / normalized).resolve()

    # ``is_relative_to`` (py3.9+) — strict containment incl. symlink escapes.
    if not (resolved == prefix_root or prefix_root in resolved.parents):
        raise VaultPathError(
            f"path escapes {matched_prefix} scope: {rel_path!r}"
        )

    return resolved


def _ext_allowed(p: Path) -> bool:
    return p.suffix.lower() in ALLOWED_EXTENSIONS


def _matched_prefix_root(resolved: Path) -> Optional[Path]:
    """Return the resolved prefix-root that contains ``resolved``, or None.

    Used by ``list_vault_files`` to re-verify each glob hit stays inside
    the same allowed-prefix subtree the caller asked for. Symlinks that
    escape get filtered here, after ``realpath`` folds the target.
    """
    root = mirror_path()
    for prefix in ALLOWED_PREFIXES:
        prefix_root = (root / prefix.rstrip("/")).resolve()
        if resolved == prefix_root or prefix_root in resolved.parents:
            return prefix_root
    return None


def list_vault_files(prefix: str = OPS_PREFIX) -> list[str]:
    """Return relative paths for files under ``prefix`` with allowed extensions.

    ``prefix`` must start with one of ``ALLOWED_PREFIXES`` (``_ops/`` or
    ``wiki/``). Result paths are relative to the mirror root and sorted
    for deterministic output.
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
        # pointing outside any allowed prefix.
        try:
            resolved_hit = candidate.resolve()
        except OSError:
            continue
        if _matched_prefix_root(resolved_hit) is None:
            continue
        results.append(str(candidate.relative_to(root)))
    return results


# Back-compat alias — pre-BAKER_VAULT_READ_WIKI_SCOPE_1 name. Drop in
# a follow-up cleanup brief once all consumers migrate.
list_ops_files = list_vault_files


def read_vault_file(rel_path: str) -> dict:
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


# Back-compat alias — pre-BAKER_VAULT_READ_WIKI_SCOPE_1 name. Drop in
# a follow-up cleanup brief once all consumers migrate.
read_ops_file = read_vault_file
