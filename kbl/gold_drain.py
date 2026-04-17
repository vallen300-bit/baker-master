"""Drain gold_promote_queue on each pipeline tick (D2).

Flow: WhatsApp /gold → WAHA/Render INSERT → Mac Mini drains → frontmatter
flip (author: director) → commit with Director identity → push.

R1.B4 transaction invariant: PG rows are marked done ONLY after the git
push succeeds. A push failure checks out the affected files so the next
drain retries the same work — no half-done state on disk.
"""

from __future__ import annotations

import logging as _stdlib_logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kbl.config import cfg_bool
from kbl.db import get_conn
from kbl.logging import emit_log

# R1.N4: vault path configurable via env var (was hardcoded in draft).
VAULT = Path(os.getenv("KBL_VAULT_PATH", str(Path.home() / "baker-vault")))
DIRECTOR_EMAIL = "dvallen@brisengroup.com"
DIRECTOR_NAME = "Dimitry Vallen"
PUSH_RETRY_DELAYS = [2, 10, 30]  # seconds between retries on push fail

_local_logger = _stdlib_logging.getLogger("kbl")


class GitPushFailed(Exception):
    pass


def drain_queue() -> None:
    """Claim → apply filesystem → commit+push (with retry) → mark PG done.

    Push failure rolls back filesystem; rows stay pending for next drain.
    """
    if cfg_bool("gold_promote_disabled", False):
        emit_log("WARN", "gold_drain", None, "Gold promotion disabled via kill-switch")
        return

    with get_conn() as conn:
        # 1. Claim rows (SKIP LOCKED — defensive; Mac Mini is sole consumer)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, path, wa_msg_id FROM gold_promote_queue
                    WHERE processed_at IS NULL
                    ORDER BY requested_at ASC
                    LIMIT 10
                    FOR UPDATE SKIP LOCKED
                    """
                )
                claimed = cur.fetchall()
                conn.commit()  # release the row locks
        except Exception:
            conn.rollback()
            raise

        if not claimed:
            return

        # 2. Apply filesystem changes (no PG updates yet).
        applied: list[tuple[int, str, str | None, str]] = []
        promoted_paths: list[str] = []  # S3: track for specific-path `git add`
        for row_id, path, wa_msg_id in claimed:
            result = promote_one(path)
            applied.append((row_id, path, wa_msg_id, result))
            if result == "ok":
                promoted_paths.append(path)

        # 3. Commit + push atomically (with retry). Rollback on failure.
        if promoted_paths:
            try:
                _commit_and_push(promoted_paths, applied)
            except GitPushFailed as e:
                emit_log(
                    "CRITICAL",
                    "gold_drain",
                    None,
                    f"Push failed after retries: {e}. Rolling back filesystem, PG rows stay pending.",
                )
                subprocess.run(
                    ["git", "-C", str(VAULT), "checkout", "HEAD", "--"] + promoted_paths,
                    check=False,
                )
                return  # do NOT mark PG rows done — next drain retries

        # 4. Push succeeded (or nothing to push): mark PG rows done.
        try:
            with conn.cursor() as cur:
                for row_id, path, wa_msg_id, result in applied:
                    cur.execute(
                        """
                        UPDATE gold_promote_queue
                        SET processed_at = NOW(), result = %s
                        WHERE id = %s
                        """,
                        (result, row_id),
                    )
                    # R2.NEW-S3: errors → PG (ERROR level for visibility);
                    # successes → local file only so kbl_log doesn't flood
                    # with routine Gold promotions over time (R1.S2 invariant:
                    # only WARN+ to PG).
                    if result.startswith("error"):
                        emit_log(
                            "ERROR",
                            "gold_drain",
                            None,
                            f"Promoted {path}: {result}",
                            metadata={"wa_msg_id": wa_msg_id, "queue_id": row_id},
                        )
                    else:
                        _local_logger.info(
                            "[gold_drain] Promoted %s: %s (queue_id=%s, wa_msg_id=%s)",
                            path,
                            result,
                            row_id,
                            wa_msg_id,
                        )
                conn.commit()
        except Exception:
            conn.rollback()
            raise


def promote_one(path: str) -> str:
    """Flip author→director on a single file. Returns 'ok'|'noop'|'error:...'."""
    target = VAULT / path
    if not target.exists():
        return "error:file_not_found"
    try:
        content = target.read_text()
        fm, body = _parse_frontmatter(content)
    except Exception as e:
        return f"error:parse:{e}"

    if fm.get("author") == "director":
        return "noop"  # already Gold — idempotent second hit

    fm["author"] = "director"
    fm["author_verified_at"] = datetime.now(timezone.utc).isoformat()
    target.write_text(_format_frontmatter(fm) + body)
    return "ok"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content
    fm_str = content[4:end]
    body = content[end + 5 :]
    return yaml.safe_load(fm_str) or {}, body


def _format_frontmatter(fm: dict) -> str:
    return f"---\n{yaml.safe_dump(fm, sort_keys=False)}---\n"


def _commit_and_push(promoted_paths: list[str], applied: list[tuple]) -> None:
    """S3: git add specific paths (never -A — would sweep unrelated dirt).
    S4: commit message includes path + queue_id + wa_msg_id for audit.
    B4: push up to 4 attempts (0s, 2s, 10s, 30s) before raising GitPushFailed.
    """
    for path in promoted_paths:
        subprocess.run(["git", "-C", str(VAULT), "add", path], check=True)

    msg_lines = ["gold: Director promotion", ""]
    for row_id, path, wa_msg_id, result in applied:
        if result == "ok":
            msg_lines.append(f"- {path} (queue_id={row_id}, wa_msg_id={wa_msg_id})")
    msg = "\n".join(msg_lines)

    subprocess.run(
        [
            "git",
            "-C",
            str(VAULT),
            "-c",
            f"user.name={DIRECTOR_NAME}",
            "-c",
            f"user.email={DIRECTOR_EMAIL}",
            "commit",
            "-m",
            msg,
        ],
        check=True,
    )

    last_error: Exception | None = None
    for delay in [0] + PUSH_RETRY_DELAYS:
        if delay > 0:
            time.sleep(delay)
        try:
            subprocess.run(
                ["git", "-C", str(VAULT), "push", "origin", "main"],
                check=True,
                capture_output=True,
                text=True,
            )
            return
        except subprocess.CalledProcessError as e:
            last_error = e
            stderr_snippet = (e.stderr or "")[:200]
            emit_log(
                "WARN",
                "gold_drain",
                None,
                f"Push failed (attempt after {delay}s delay): {stderr_snippet}",
            )
            continue

    # All retries exhausted — rollback the local commit too, then raise.
    subprocess.run(
        ["git", "-C", str(VAULT), "reset", "--hard", "HEAD~1"],
        check=False,
    )
    raise GitPushFailed(str(last_error))


# R1.B3: `python3 -m kbl.gold_drain` entry point.
if __name__ == "__main__":
    drain_queue()
    sys.exit(0)
