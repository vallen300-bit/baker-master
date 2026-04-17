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

from kbl.config import cfg, cfg_bool
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
    """Single-transaction drain: claim via FOR UPDATE SKIP LOCKED, apply
    filesystem, commit+push, mark PG rows done — then ONE commit releases
    the row locks. Ad-hoc concurrent drainers block on the same rows (B2.S1).

    Push failure rolls back filesystem AND the PG transaction (so rows
    stay pending for next drain — no status drift possible).
    """
    if cfg_bool("gold_promote_disabled", False):
        emit_log("WARN", "gold_drain", None, "Gold promotion disabled via kill-switch")
        return

    with get_conn() as conn:
        try:
            # 1. Claim rows under FOR UPDATE SKIP LOCKED. Locks stay held
            #    until the final conn.commit() below — this is the
            #    concurrent-drain race guard (B2.S1).
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

            if not claimed:
                # Release the (empty) lock cleanly.
                conn.commit()
                return

            # 2. Apply filesystem changes (no PG updates yet). Row locks
            #    are still held — no other drainer can see these rows.
            applied: list[tuple[int, str, str | None, str]] = []
            promoted_paths: list[str] = []  # S3: specific-path `git add`
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
                        f"Push failed after retries: {e}. "
                        "Rolling back filesystem + PG tx, rows stay pending.",
                    )
                    subprocess.run(
                        ["git", "-C", str(VAULT), "checkout", "HEAD", "--"] + promoted_paths,
                        check=False,
                    )
                    # PG ROLLBACK also releases the row locks — rows go
                    # back to processed_at IS NULL and next drain retries.
                    conn.rollback()
                    return

            # 4. Push succeeded (or nothing to push): mark PG rows done.
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
                    # R2.NEW-S3: errors → PG ERROR (visibility);
                    # successes → local file only (R1.S2 "WARN+ to PG" invariant
                    # keeps kbl_log from flooding with routine promotions).
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
            # Single commit closes the transaction + releases row locks.
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def promote_one(path: str) -> str:
    """Flip author→director on a single file. Returns 'ok'|'noop'|'error:...'.

    B2.N2: refuses headerless files. Gold promotion is meant for existing
    wiki pages already under the author: pipeline → author: director flow.
    Fabricating frontmatter on an arbitrary Markdown file (e.g., a note
    the Director pasted into the vault without running it through the
    pipeline) is almost never what was intended.
    """
    target = VAULT / path
    if not target.exists():
        return "error:file_not_found"

    # Headerless-file guard BEFORE reading frontmatter: keep the check
    # cheap and explicit so `_parse_frontmatter`'s tolerant-to-missing
    # semantics aren't disturbed (other callers may rely on it).
    content = target.read_text()
    if not content.startswith("---\n") or content.find("\n---\n", 4) == -1:
        return "error:no_frontmatter"

    try:
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

    B2.S4: `git add` / `git commit` subprocess failures are converted to
    `GitPushFailed` so drain_queue catches a single exception type +
    rolls back filesystem and PG atomically. Without this, an add/commit
    failure would bubble past drain_queue's try/except and leave
    filesystem-modified + PG-rows-pending state drift possible on
    a future refactor that separates filesystem-write from commit.
    """
    try:
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
    except subprocess.CalledProcessError as e:
        raise GitPushFailed(f"git add/commit failed: {e}") from e

    # B2.N3: vault branch configurable so a future default-branch rename
    # on baker-vault doesn't silently break pushes.
    vault_branch = cfg("gold_promote_vault_branch", "main")

    last_error: Exception | None = None
    for delay in [0] + PUSH_RETRY_DELAYS:
        if delay > 0:
            time.sleep(delay)
        try:
            subprocess.run(
                ["git", "-C", str(VAULT), "push", "origin", vault_branch],
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
