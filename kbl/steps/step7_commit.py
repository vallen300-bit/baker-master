"""Step 7 — vault commit + push under flock mutex (terminal pipeline step).

Consumes ``signal_queue`` rows at ``status='awaiting_commit'`` (written
by Step 6) and writes their ``final_markdown`` to the baker-vault git
clone, appends cross-link stubs from ``kbl_cross_link_queue`` to each
target matter's ``_links.md``, commits with the pipeline identity, and
pushes to GitHub. Closes the KBL-B pipeline — signal ends at
``completed``.

KBL-B anchor: §4.8 (commit/push) + §4.9 (TOAST cleanup).

Deploy contract
---------------

Code is deploy-agnostic. Production runs on Mac Mini (single agent
writer per Inv 9). Dev Mac can run the same code against a local vault
clone with ``BAKER_VAULT_DISABLE_PUSH=true`` to skip the push. Required
env var is ``BAKER_VAULT_PATH``; all others default.

Atomicity
---------

Step 7 is filesystem + git + DB. Ordering to avoid torn state:

1. Mark ``commit_running`` + **internal commit** so concurrent ticks see
   the claim across the caller's rollback boundary.
2. Inside the vault flock:
   a. ``git pull --rebase origin main`` to sync before write.
   b. Write all files atomically via ``tempfile.NamedTemporaryFile``
      + ``os.replace``. Same-filesystem rename is atomic on POSIX.
   c. ``git add`` + ``git commit``.
   d. ``git push``. On non-fast-forward: one ``git pull --rebase`` +
      retry. On second failure: ``git reset --hard ORIG_HEAD`` to
      discard the local commit (keeps remote authoritative) and raise
      ``CommitError``.
3. Release flock.
4. DB finalize: ``status='completed'``, ``committed_at=NOW()``,
   ``commit_sha=...``; ``kbl_cross_link_queue.realized_at=NOW()`` for
   the stubs this call consumed; TOAST cleanup (§4.9) NULLs out
   ``opus_draft_markdown`` + ``final_markdown``. Caller (pipeline_tick)
   owns the final commit.

On filesystem/git failure inside the flock window: Step 7 runs
``git checkout HEAD -- .`` + ``git clean -fd`` to restore the working
tree (undoes any atomic writes that landed before the failure), then
flips ``commit_failed`` with an internal commit and raises
:class:`CommitError`.

CHANDA
------

* **Inv 4** — before writing ``target_vault_path``, Step 7 checks if
  the existing file has ``author: director`` frontmatter; if so, abort
  (``CommitError``). Promoted-Gold files are Director-owned and must
  never be silently overwritten by the pipeline.
* **Inv 6** — terminal. Post-commit state is ``completed``.
* **Inv 9** — this IS the Mac Mini agent writer. Positive test asserts
  all FS writes land under ``{BAKER_VAULT_PATH}/wiki/`` (never outside).
* **Inv 10** — no prompts.
"""
from __future__ import annotations

import logging as _stdlib_logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Tuple

from kbl._flock import acquire_vault_lock
from kbl.exceptions import CommitError, VaultLockTimeoutError
from kbl.logging import emit_log

logger = _stdlib_logging.getLogger(__name__)


# ---------------------------- env vars ----------------------------

# Read at module import. BAKER_VAULT_PATH is validated at commit() entry
# (deferred fail-fast) so tests can import without it set; once commit()
# runs we require a real path.
_VAULT_PATH_ENV = "BAKER_VAULT_PATH"
_LOCK_PATH_ENV = "BAKER_VAULT_LOCK_PATH"
_FLOCK_TIMEOUT_ENV = "BAKER_VAULT_FLOCK_TIMEOUT_SECONDS"
_GIT_NAME_ENV = "BAKER_VAULT_GIT_IDENTITY_NAME"
_GIT_EMAIL_ENV = "BAKER_VAULT_GIT_IDENTITY_EMAIL"
_GIT_REMOTE_ENV = "BAKER_VAULT_GIT_REMOTE"
_DISABLE_PUSH_ENV = "BAKER_VAULT_DISABLE_PUSH"

_DEFAULT_FLOCK_TIMEOUT = 60.0
_DEFAULT_GIT_IDENTITY_NAME = "Baker Pipeline"
_DEFAULT_GIT_IDENTITY_EMAIL = "pipeline@brisengroup.com"
_DEFAULT_GIT_REMOTE = "origin"
_GIT_BRANCH = "main"

_STATE_CLAIM = "awaiting_commit"
_STATE_RUNNING = "commit_running"
_STATE_DONE = "completed"
_STATE_FAILED = "commit_failed"


def _env_config() -> "_VaultConfig":
    """Resolve env vars at each commit() call. BAKER_VAULT_PATH is
    required; absent → ``CommitError``."""
    raw_path = os.environ.get(_VAULT_PATH_ENV)
    if not raw_path:
        raise CommitError(
            f"{_VAULT_PATH_ENV} is required for Step 7 but not set"
        )
    vault = Path(raw_path).expanduser().resolve()
    lock_path = os.environ.get(_LOCK_PATH_ENV) or str(vault / ".lock")
    try:
        timeout = float(os.environ.get(_FLOCK_TIMEOUT_ENV) or _DEFAULT_FLOCK_TIMEOUT)
    except ValueError:
        timeout = _DEFAULT_FLOCK_TIMEOUT
    return _VaultConfig(
        vault_path=vault,
        lock_path=lock_path,
        flock_timeout=timeout,
        git_name=os.environ.get(_GIT_NAME_ENV) or _DEFAULT_GIT_IDENTITY_NAME,
        git_email=os.environ.get(_GIT_EMAIL_ENV) or _DEFAULT_GIT_IDENTITY_EMAIL,
        git_remote=os.environ.get(_GIT_REMOTE_ENV) or _DEFAULT_GIT_REMOTE,
        disable_push=(os.environ.get(_DISABLE_PUSH_ENV, "").lower()
                      in ("1", "true", "yes", "on")),
    )


@dataclass(frozen=True)
class _VaultConfig:
    vault_path: Path
    lock_path: str
    flock_timeout: float
    git_name: str
    git_email: str
    git_remote: str
    disable_push: bool


# ---------------------------- data loading ----------------------------


@dataclass(frozen=True)
class _SignalRow:
    signal_id: int
    final_markdown: str
    target_vault_path: str
    primary_matter: Optional[str]
    title: str


@dataclass(frozen=True)
class _Stub:
    target_slug: str
    stub_row: str


def _fetch_signal_row(conn: Any, signal_id: int) -> _SignalRow:
    """Load the Step 6 output for this signal.

    ``primary_matter`` + ``title`` are reconstructed from the YAML
    frontmatter in ``final_markdown`` rather than stored as columns —
    keeps the schema tight (single source of truth)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT final_markdown, target_vault_path "
            "FROM signal_queue WHERE id = %s",
            (signal_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise CommitError(f"signal_queue row not found: id={signal_id}")
    final_markdown, target_vault_path = row[0], row[1]
    if not final_markdown or not target_vault_path:
        raise CommitError(
            f"signal_id={signal_id}: missing final_markdown or "
            f"target_vault_path (Step 6 should have populated both)"
        )
    primary_matter, title = _extract_primary_and_title(final_markdown)
    return _SignalRow(
        signal_id=signal_id,
        final_markdown=final_markdown,
        target_vault_path=target_vault_path,
        primary_matter=primary_matter,
        title=title,
    )


_FRONTMATTER_SPLIT_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_PRIMARY_RE = re.compile(r"^primary_matter:\s*(\S+)\s*$", re.MULTILINE)
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)


def _extract_primary_and_title(markdown: str) -> Tuple[Optional[str], str]:
    m = _FRONTMATTER_SPLIT_RE.match(markdown)
    if not m:
        return None, "(untitled)"
    yaml_block = m.group(1)
    primary_m = _PRIMARY_RE.search(yaml_block)
    primary = None
    if primary_m:
        raw = primary_m.group(1).strip()
        if raw and raw.lower() != "null":
            primary = raw
    title_m = _TITLE_RE.search(yaml_block)
    title = title_m.group(1).strip() if title_m else "(untitled)"
    return primary, title


def _fetch_unrealized_stubs(conn: Any, signal_id: int) -> List[_Stub]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT target_slug, stub_row "
            "FROM kbl_cross_link_queue "
            "WHERE source_signal_id = %s AND realized_at IS NULL "
            "ORDER BY target_slug ASC",
            (signal_id,),
        )
        rows = cur.fetchall()
    return [_Stub(target_slug=r[0], stub_row=r[1]) for r in rows]


# ---------------------------- state writes ----------------------------


def _mark_running(conn: Any, signal_id: int) -> None:
    """Claim the signal — internal commit so concurrent ticks see it
    across the caller's rollback boundary."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE signal_queue SET status = %s WHERE id = %s",
            (_STATE_RUNNING, signal_id),
        )
    conn.commit()


def _mark_completed(
    conn: Any,
    signal_id: int,
    commit_sha: str,
    realized_stub_slugs: List[str],
) -> None:
    """Terminal success: ``completed`` + ``committed_at`` + ``commit_sha``,
    realize the stubs, and TOAST-cleanup the heavy columns. Caller
    (pipeline_tick) commits the outer tx after we return."""
    with conn.cursor() as cur:
        # Defensive ADD COLUMN so first-run on a PG that hasn't had a
        # committed_at / commit_sha migration survives. Matches Step 6's
        # finalize_retry_count pattern.
        cur.execute(
            "ALTER TABLE signal_queue "
            "ADD COLUMN IF NOT EXISTS committed_at TIMESTAMPTZ"
        )
        cur.execute(
            "ALTER TABLE signal_queue "
            "ADD COLUMN IF NOT EXISTS commit_sha TEXT"
        )
        cur.execute(
            "UPDATE signal_queue SET "
            "  status = %s, "
            "  committed_at = NOW(), "
            "  commit_sha = %s, "
            "  opus_draft_markdown = NULL, "
            "  final_markdown = NULL "
            "WHERE id = %s AND status = %s",
            (_STATE_DONE, commit_sha, signal_id, _STATE_RUNNING),
        )
        if realized_stub_slugs:
            cur.execute(
                "UPDATE kbl_cross_link_queue "
                "SET realized_at = NOW() "
                "WHERE source_signal_id = %s AND target_slug = ANY(%s) "
                "AND realized_at IS NULL",
                (signal_id, realized_stub_slugs),
            )


def _mark_commit_failed(conn: Any, signal_id: int, reason: str) -> None:
    """Terminal failure: internal commit so state flip survives the
    caller's rollback. ``reason`` goes to ``kbl_log``."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE signal_queue SET status = %s WHERE id = %s",
                (_STATE_FAILED, signal_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    emit_log("WARN", "commit", signal_id, f"commit_failed: {reason}")


# ---------------------------- FS writes ----------------------------


def _assert_path_inside_vault(abs_path: Path, vault_path: Path) -> None:
    """Inv 9 safety net: every write must land under ``{vault}/`` (no
    symlink escapes, no absolute-path injections in frontmatter). We
    compare resolved paths."""
    try:
        abs_path.resolve().relative_to(vault_path.resolve())
    except ValueError:
        raise CommitError(
            f"refused to write outside vault: path={abs_path}, vault={vault_path}"
        )


def _atomic_write(final_path: Path, content: str) -> None:
    """``tempfile.NamedTemporaryFile`` in the same directory → ``os.replace``.
    POSIX atomic same-filesystem rename."""
    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = final_path.parent
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(tmp_dir),
        prefix=f".{final_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as tf:
        tf.write(content)
        tf.flush()
        os.fsync(tf.fileno())
        tmp_name = tf.name
    try:
        os.replace(tmp_name, str(final_path))
    except OSError:
        # Clean up orphan tmp if replace failed.
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


_STUB_MARKER_RE_TMPL = r"<!--\s*stub:signal_id={sid}\s*-->"
_STUB_DATE_RE = re.compile(r"-\s*(\d{4}-\d{2}-\d{2})")


def _parse_stub_signal_id(row: str) -> Optional[str]:
    m = re.search(r"<!--\s*stub:signal_id=(\d+)\s*-->", row)
    return m.group(1) if m else None


def _append_or_replace_stub(
    links_file: Path, stub_row: str
) -> None:
    """Append ``stub_row`` to ``_links.md``, replacing any existing row
    with the same ``<!-- stub:signal_id=... -->`` marker (idempotent
    across Step 6 re-runs per Option C contract).

    Rows are kept sorted by the date token in each stub_row DESC
    (newest first). We assume ``_links.md`` body is a list of stub
    rows, one per line, optionally preceded by a header/prose block.
    If the file exists but has no stub rows, new rows are appended
    at the end.
    """
    source_sid = _parse_stub_signal_id(stub_row)
    if not source_sid:
        raise CommitError(
            f"stub_row is missing signal_id marker: {stub_row!r}"
        )
    marker_re = re.compile(_STUB_MARKER_RE_TMPL.format(sid=re.escape(source_sid)))

    if links_file.exists():
        existing = links_file.read_text(encoding="utf-8")
    else:
        existing = ""

    # Partition: non-stub prefix lines + list of stub rows.
    prefix_lines: List[str] = []
    stub_rows: List[str] = []
    seen_any_stub = False
    for raw_line in existing.splitlines():
        if raw_line.strip().startswith("<!-- stub:signal_id="):
            seen_any_stub = True
            stub_rows.append(raw_line)
        elif not seen_any_stub:
            prefix_lines.append(raw_line)
        else:
            # A non-stub line after stub rows: pin it at the end of the
            # stub block so we don't drop trailing prose. Rare but safe.
            stub_rows.append(raw_line)

    # Replace or insert.
    replaced = False
    new_rows: List[str] = []
    for r in stub_rows:
        if marker_re.search(r):
            new_rows.append(stub_row)
            replaced = True
        else:
            new_rows.append(r)
    if not replaced:
        new_rows.append(stub_row)

    # Sort by date DESC when the row carries a parseable date. Lines
    # that don't parse go to the end (stable).
    def _sort_key(row: str) -> str:
        m = _STUB_DATE_RE.search(row)
        return m.group(1) if m else "0000-00-00"

    stub_rows_sorted = sorted(
        [r for r in new_rows if r.strip().startswith("<!-- stub:signal_id=")],
        key=_sort_key,
        reverse=True,
    )
    tail_rows = [r for r in new_rows if not r.strip().startswith("<!-- stub:signal_id=")]

    output_lines = list(prefix_lines)
    if prefix_lines and stub_rows_sorted:
        # Ensure a blank separator if prefix didn't end with one.
        if prefix_lines[-1].strip():
            output_lines.append("")
    output_lines.extend(stub_rows_sorted)
    output_lines.extend(tail_rows)

    _atomic_write(links_file, "\n".join(output_lines) + "\n")


# ---------------------------- Inv 4 guard ----------------------------


_DIRECTOR_AUTHOR_RE = re.compile(r"^author:\s*director\s*$", re.MULTILINE)


def _inv4_guard_target_path(abs_path: Path) -> None:
    """If ``abs_path`` exists and has ``author: director`` in its
    frontmatter, refuse the write. Protects Director-promoted Gold files
    from pipeline overwrite (CHANDA Inv 4)."""
    if not abs_path.exists():
        return
    try:
        head = abs_path.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        # If we can't read it, err on the side of refusing to touch it.
        raise CommitError(
            f"Inv 4 guard: cannot read existing {abs_path} to verify author"
        )
    fm_match = _FRONTMATTER_SPLIT_RE.match(head)
    yaml_block = fm_match.group(1) if fm_match else head
    if _DIRECTOR_AUTHOR_RE.search(yaml_block):
        raise CommitError(
            f"Inv 4 guard: refusing to overwrite Director-authored file "
            f"at {abs_path}"
        )


# ---------------------------- git ----------------------------


def _run_git(cfg: _VaultConfig, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command inside the vault with the pipeline identity.
    ``check=True`` raises ``CalledProcessError`` on non-zero exit."""
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = cfg.git_name
    env["GIT_AUTHOR_EMAIL"] = cfg.git_email
    env["GIT_COMMITTER_NAME"] = cfg.git_name
    env["GIT_COMMITTER_EMAIL"] = cfg.git_email
    return subprocess.run(
        ["git", *args],
        cwd=str(cfg.vault_path),
        capture_output=True,
        text=True,
        env=env,
        check=check,
    )


def _git_pull_rebase(cfg: _VaultConfig) -> None:
    try:
        _run_git(cfg, "pull", "--rebase", cfg.git_remote, _GIT_BRANCH)
    except subprocess.CalledProcessError as e:
        raise CommitError(
            f"git pull --rebase failed: {e.stderr.strip() or e.stdout.strip()}"
        )


def _git_add_commit(
    cfg: _VaultConfig, paths: List[str], message: str
) -> str:
    """``git add`` each path, then ``git commit``. Returns the new HEAD
    SHA. No-op if there are no staged changes (raises
    :class:`CommitError`)."""
    try:
        _run_git(cfg, "add", "--", *paths)
    except subprocess.CalledProcessError as e:
        raise CommitError(f"git add failed: {e.stderr.strip()}")

    status = _run_git(cfg, "status", "--porcelain")
    if not status.stdout.strip():
        raise CommitError("git status reports no changes to commit")

    try:
        _run_git(cfg, "commit", "-m", message)
    except subprocess.CalledProcessError as e:
        raise CommitError(f"git commit failed: {e.stderr.strip()}")

    rev = _run_git(cfg, "rev-parse", "HEAD")
    return rev.stdout.strip()


def _git_push_with_retry(cfg: _VaultConfig) -> None:
    """``git push``. On non-fast-forward: one ``git pull --rebase`` +
    one push retry. On second failure: raise :class:`CommitError`.
    Caller is responsible for ``git reset --hard ORIG_HEAD`` on failure
    — ``_git_push_with_retry`` does not unwind local state itself."""
    try:
        _run_git(cfg, "push", cfg.git_remote, _GIT_BRANCH)
        return
    except subprocess.CalledProcessError as e:
        first_stderr = (e.stderr or "").strip()
        logger.warning(
            "step7 git push failed on first try (%s); rebasing + retrying",
            first_stderr[:200],
        )

    try:
        _run_git(cfg, "pull", "--rebase", cfg.git_remote, _GIT_BRANCH)
    except subprocess.CalledProcessError as e:
        raise CommitError(
            f"git pull --rebase (retry) failed: {e.stderr.strip()}"
        )
    try:
        _run_git(cfg, "push", cfg.git_remote, _GIT_BRANCH)
    except subprocess.CalledProcessError as e:
        raise CommitError(
            f"git push failed after rebase retry: {e.stderr.strip()}"
        )


def _git_hard_reset_one(cfg: _VaultConfig) -> None:
    """Discard the last local commit + working-tree changes. Used when
    push exhausts retries to leave the local repo in sync with remote."""
    try:
        _run_git(cfg, "reset", "--hard", "ORIG_HEAD")
    except subprocess.CalledProcessError:
        # Last-resort: reset to remote HEAD.
        try:
            _run_git(cfg, "reset", "--hard", f"{cfg.git_remote}/{_GIT_BRANCH}")
        except subprocess.CalledProcessError:
            logger.exception("step7 post-failure reset failed; vault may be dirty")


def _git_checkout_discard(cfg: _VaultConfig) -> None:
    """Restore working tree to HEAD (undoes uncommitted atomic writes)."""
    try:
        _run_git(cfg, "checkout", "HEAD", "--", ".")
    except subprocess.CalledProcessError:
        pass
    try:
        _run_git(cfg, "clean", "-fd")
    except subprocess.CalledProcessError:
        pass


# ---------------------------- commit() ----------------------------


def commit(signal_id: int, conn: Any) -> None:
    """Vault-commit one signal. Advances ``awaiting_commit`` →
    ``completed`` on success, ``commit_failed`` on any hard failure.
    Caller-owns-commit: the terminal state flip and the realized-at
    UPDATE are visible only after pipeline_tick commits the outer tx,
    EXCEPT the ``commit_running`` claim and ``commit_failed`` terminal
    which both commit internally (mirrors Steps 1/4/5/6 pattern)."""
    cfg = _env_config()
    row = _fetch_signal_row(conn, signal_id)
    stubs = _fetch_unrealized_stubs(conn, signal_id)

    # Claim + internal commit.
    _mark_running(conn, signal_id)

    # Build absolute paths + Inv 9 containment check.
    main_abs = (cfg.vault_path / row.target_vault_path).resolve()
    _assert_path_inside_vault(main_abs, cfg.vault_path)
    _inv4_guard_target_path(main_abs)

    stub_abs_paths: List[Path] = []
    for s in stubs:
        p = (cfg.vault_path / "wiki" / s.target_slug / "_links.md").resolve()
        _assert_path_inside_vault(p, cfg.vault_path)
        stub_abs_paths.append(p)

    try:
        with acquire_vault_lock(cfg.lock_path, cfg.flock_timeout):
            _git_pull_rebase(cfg)

            try:
                _atomic_write(main_abs, row.final_markdown)
                for stub, stub_path in zip(stubs, stub_abs_paths):
                    _append_or_replace_stub(stub_path, stub.stub_row)
            except Exception as e:
                # Any write failure → undo all writes via git then fail.
                _git_checkout_discard(cfg)
                raise CommitError(f"vault write failed: {e}") from e

            # Build the git-add path list: main + every touched _links.md.
            rel_main = str(main_abs.relative_to(cfg.vault_path))
            rel_paths = [rel_main] + [
                str(p.relative_to(cfg.vault_path)) for p in stub_abs_paths
            ]

            short_id = _short_sig_id(signal_id)
            matter = row.primary_matter or "_inbox"
            message = f"Silver: {matter} — {row.title} (sig:{short_id})"

            try:
                commit_sha = _git_add_commit(cfg, rel_paths, message)
            except CommitError:
                _git_checkout_discard(cfg)
                raise

            if cfg.disable_push:
                logger.info(
                    "step7 mock-mode: BAKER_VAULT_DISABLE_PUSH=true, "
                    "skipping git push (signal_id=%s, sha=%s)",
                    signal_id,
                    commit_sha,
                )
            else:
                try:
                    _git_push_with_retry(cfg)
                except CommitError:
                    _git_hard_reset_one(cfg)
                    raise

        # Flock released. DB finalize — caller-owns-commit after return.
        realized_slugs = [s.target_slug for s in stubs]
        _mark_completed(conn, signal_id, commit_sha, realized_slugs)

    except VaultLockTimeoutError as e:
        _mark_commit_failed(conn, signal_id, str(e))
        raise
    except CommitError as e:
        _mark_commit_failed(conn, signal_id, str(e))
        raise
    except Exception as e:
        _mark_commit_failed(conn, signal_id, f"unexpected: {e}")
        raise CommitError(f"unexpected Step 7 failure: {e}") from e


def _short_sig_id(signal_id: int) -> str:
    """Compact signal identifier for commit-message suffix. Avoids
    pinning commit messages to a format that breaks if BIGINT ids grow
    very large."""
    return str(signal_id)
