"""POSIX flock helper for Step 7 vault mutex.

Step 7 commits to a shared git-backed vault; concurrent writers would
produce merge conflicts and racy pushes. ``acquire_vault_lock`` gives
callers an exclusive, non-blocking flock on a dedicated lock file with a
timeout. On timeout the helper raises :class:`VaultLockTimeoutError`
(subclass of :class:`CommitError`).

Mac + Linux only (``fcntl``). Windows deliberately unsupported — Step 7
runs on Mac Mini in production, tests run on Mac/Linux dev machines.
"""
from __future__ import annotations

import fcntl
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from kbl.exceptions import VaultLockTimeoutError

_POLL_INTERVAL_SECONDS = 0.1


@contextmanager
def acquire_vault_lock(
    lock_path: str, timeout_seconds: float
) -> Iterator[None]:
    """Exclusive flock on ``lock_path`` with a deadline.

    Polls every 100ms until the lock is acquired or the deadline passes.
    On deadline: raises :class:`VaultLockTimeoutError`. On normal exit:
    the lock is released (even if the caller raises inside the ``with``).

    The lock file itself is created if missing (parent dirs too) and
    left on disk after release — reusing a single file avoids races
    between unlink + create in a concurrent flock world.
    """
    lock_p = Path(lock_path)
    lock_p.parent.mkdir(parents=True, exist_ok=True)

    # ``os.open`` with O_CREAT so first-run doesn't race with a second
    # process also creating the lock file.
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise VaultLockTimeoutError(
                        f"vault flock timed out after {timeout_seconds}s: "
                        f"{lock_path}"
                    )
                time.sleep(_POLL_INTERVAL_SECONDS)

        try:
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                # Releasing can fail after a process crash in rare cases;
                # the fd close below will drop the kernel lock regardless.
                pass
    finally:
        os.close(fd)
