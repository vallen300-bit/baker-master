#!/usr/bin/env python3
"""bus_post.py — AI Head outbound auto-post (richer payload variant).

Usage:
    bus_post.py --to lead --body "..." [--topic ...] [--parent-id N] [--kind dispatch] [--tier B]
    bus_post.py --to AG-203,deputy --body "..."  # IDs / slugs, multiple recipients
    BAKER_ROLE=aid bus_post.py --to lead --body "..."  # AID-Terminal sender

Companion to scripts/bus_post.sh. Use the .sh for one-liner dispatches; the
.py when you need parent_id chains, multi-recipient broadcasts, or multiline
bodies that shell-quote awkwardly.

Director ratified 2026-05-06 OPTION A + policy (ii): op-fetch sender key on demand.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from orchestrator.agent_identity_data import ROLE_TO_SLUG, VALID_BUS_SLUGS  # noqa: E402

DAEMON_URL = os.environ.get("BRISEN_LAB_DAEMON_URL", "https://brisen-lab.onrender.com")

VALID_SLUGS = set(VALID_BUS_SLUGS)


def _resolve_sender() -> str:
    role = os.environ.get("BAKER_ROLE", "")
    if role not in ROLE_TO_SLUG:
        sys.exit(
            f"ERROR: BAKER_ROLE not set or unrecognized: {role!r}. "
            "Valid registry roles: "
            f"{', '.join(sorted(set(ROLE_TO_SLUG.values())))} plus aliases"
        )
    return ROLE_TO_SLUG[role]


def _resolve_recipient(value: str) -> str | None:
    if value in VALID_SLUGS:
        return value
    return ROLE_TO_SLUG.get(value)


def _is_literal_terminal_key(value: str | None) -> bool:
    return bool(value) and not value.startswith("op://")


def _terminal_key_cache_path(sender: str) -> Path:
    return Path.home() / ".brisen-lab" / "keys" / sender


def _read_cached_key(sender: str) -> str:
    try:
        key = _terminal_key_cache_path(sender).read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return key if _is_literal_terminal_key(key) else ""


def _write_cached_key(sender: str, key: str) -> None:
    if not _is_literal_terminal_key(key):
        return
    if not sender or "/" in sender or "\\" in sender:
        return
    try:
        cache_dir = Path.home() / ".brisen-lab" / "keys"
        cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            (Path.home() / ".brisen-lab").chmod(0o700)
            cache_dir.chmod(0o700)
        except OSError:
            pass
        path = _terminal_key_cache_path(sender)
        tmp = cache_dir / f".{sender}.tmp.{os.getpid()}.{uuid.uuid4().hex}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
            f.write("\n")
        tmp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        pass


def _fetch_key(sender: str) -> str:
    env_key = os.environ.get("BRISEN_LAB_TERMINAL_KEY", "").strip()
    if _is_literal_terminal_key(env_key):
        return env_key

    cached = _read_cached_key(sender)
    if cached:
        return cached

    ref = f"op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_{sender}/credential"
    if env_key.startswith("op://"):
        ref = env_key
    try:
        out = subprocess.run(
            ["op", "read", ref],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        sys.exit(f"ERROR: 1Password CLI fetch failed: {e}")
    if out.returncode != 0:
        sys.exit(
            f"ERROR: 1Password fetch returned non-zero for {sender}: "
            f"{out.stderr.strip()}"
        )
    key = out.stdout.strip()
    if not key:
        sys.exit(f"ERROR: 1Password returned empty key for {sender}")
    _write_cached_key(sender, key)
    return key


def _post(recipient: str, payload: dict, key: str) -> dict:
    """POST with bounded retry-with-backoff (AGENT_BUS_IDEMPOTENT_POST_1, lead #8366).

    Retry ONLY on HTTP 503 (bus_busy_retry) or a network/timeout-class failure. The
    payload already carries a single idempotency_key, reused on every attempt, so a
    retry that follows a commit replays the original row instead of duplicating. Any
    other HTTP status (4xx / non-503 5xx) fails loud immediately — retrying cannot fix
    it. After the attempt budget is exhausted the final failure exits non-zero (fail
    loud). Defaults 4 attempts / base 2s (~2/4/8s); both env-overridable
    (BUS_POST_MAX_ATTEMPTS / BUS_POST_BACKOFF_BASE) so tests run with base 0.

    Timeout classes (codex #8373 P1): urlopen wraps a CONNECT failure/timeout in
    urllib.error.URLError, but a READ timeout after the request is sent escapes as a
    bare socket.timeout (Python 3.9) / TimeoutError (3.10+ alias). The read timeout IS
    the core post-commit failure mode this brief targets, so BOTH are caught + retried.
    """
    url = f"{DAEMON_URL}/msg/{recipient}"
    data = json.dumps(payload).encode("utf-8")
    max_attempts = int(os.environ.get("BUS_POST_MAX_ATTEMPTS", "4"))
    backoff_base = float(os.environ.get("BUS_POST_BACKOFF_BASE", "2"))
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"X-Terminal-Key": key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code != 503:
                sys.exit(f"ERROR: POST {url} returned HTTP {e.code}: {body}")
            last_err = f"HTTP 503: {body}"
        except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
            # URLError = connect failure / wrapped connect timeout; socket.timeout /
            # TimeoutError = a READ timeout after the request was sent (codex #8373 P1).
            # All retryable — the same idempotency_key makes a retry a safe replay.
            last_err = f"{type(e).__name__}: {e}"
        if attempt < max_attempts:
            sleep_s = backoff_base * (2 ** (attempt - 1))  # base 2 -> 2, 4, 8
            if sleep_s > 0:
                time.sleep(sleep_s)
    sys.exit(
        f"ERROR: POST {url} failed after {max_attempts} attempt(s): {last_err}"
    )


def _emit_started_best_effort(sender: str, key: str, parent_id, thread_id) -> None:
    """CLIENT_STARTED_EMISSION_1: fire the recipient's first-action `started` signal via
    the shared emitter (scripts/emit_started.py — the SINGLE control point, also used by
    bus_post.sh). It resolves the target (parent primary, thread fallback; topic dropped
    per lead #11216) and best-effort POSTs the authoritative /msg/<id>/started endpoint.

    TOTAL best-effort (lead #11215 / codex #11216): the helper ALWAYS exits 0, AND this
    call is wrapped so a subprocess-spawn failure (e.g. a generic OSError) can NEVER
    propagate and alter bus_post.py's exit status — the outbound post has already
    committed and printed its result."""
    helper = Path(__file__).resolve().parent / "emit_started.py"
    argv = [sys.executable, str(helper), "--daemon", DAEMON_URL,
            "--key", key, "--sender", sender]
    if parent_id is not None:
        argv += ["--parent", str(parent_id)]
    if thread_id is not None:
        argv += ["--thread", str(thread_id)]
    try:
        subprocess.run(argv, timeout=30)
    except Exception as e:  # noqa: BLE001 — TOTAL: never let the emit affect the caller.
        print(f"[bus_post] started-emit spawn failed ({type(e).__name__}: {e}); "
              "post already landed, continuing", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", required=True, help="comma-separated recipient slug(s), alias(es), or AG id(s)")
    ap.add_argument("--body", required=True, help="message body")
    ap.add_argument("--topic", default=None)
    ap.add_argument("--parent-id", type=int, default=None)
    ap.add_argument("--thread-id", default=None)
    ap.add_argument(
        "--kind", default="dispatch",
        choices=["dispatch", "ack", "broadcast", "ratify_required", "ratify_decision"],
    )
    ap.add_argument("--tier", default="B", choices=["B", "A", "director_only"])
    ap.add_argument(
        "--idempotency-key", default=None,
        help="reuse ONE key across a caller-managed multi-invocation retry loop "
             "(else BUS_IDEMPOTENCY_KEY env, else auto-minted per send)",
    )
    args = ap.parse_args()

    # AGENT_BUS_IDEMPOTENT_POST_1 (codex #8373 P2): an explicitly-passed but empty /
    # whitespace-only --idempotency-key is a caller error (e.g. an empty-expanded shell
    # var) — fail loud BEFORE any post, never silently auto-mint over caller intent
    # (parity with bus_post.sh's flag guard + tests/test_bus_post.py empty-flag test).
    if args.idempotency_key is not None and not args.idempotency_key.strip():
        sys.exit("ERROR: --idempotency-key requires a non-empty value")

    recipient_inputs = [r.strip() for r in args.to.split(",") if r.strip()]
    # F2-FU-1: director-recipient is daemon-gated (BRISEN_LAB_DIRECTOR_RECIPIENT_BLOCKED).
    # Single control point — script passes through; daemon enforces.
    recipients: list[str] = []
    bad: list[str] = []
    for recipient_input in recipient_inputs:
        recipient = _resolve_recipient(recipient_input)
        if recipient is None:
            bad.append(recipient_input)
        else:
            recipients.append(recipient)
    if bad:
        sys.exit(f"ERROR: unknown slug, alias, or agent id(s): {bad}. Valid slugs: {sorted(VALID_SLUGS)}")

    sender = _resolve_sender()
    key = _fetch_key(sender)

    # AGENT_BUS_IDEMPOTENT_POST_1: one key per logical send, minted ONCE here and reused
    # on every internal retry attempt. Precedence: --idempotency-key (non-empty, validated
    # above) -> BUS_IDEMPOTENCY_KEY env (empty env treated as unset, matching bus_post.sh)
    # -> fresh uuid. Distinct sends get distinct keys (so they never dedupe together); only
    # a retry of THIS send, or a caller passing the same key, replays the original row.
    idempotency_key = (
        args.idempotency_key
        or os.environ.get("BUS_IDEMPOTENCY_KEY", "").strip()
        or str(uuid.uuid4())
    )

    payload: dict = {
        "kind": args.kind,
        "body": args.body,
        "to": recipients,
        "tier_required": args.tier,
        "idempotency_key": idempotency_key,
    }
    if args.topic is not None:
        payload["topic"] = args.topic
    if args.parent_id is not None:
        payload["parent_id"] = args.parent_id
    if args.thread_id is not None:
        payload["thread_id"] = args.thread_id

    # POST to first recipient with full to=[list] in body. Daemon's
    # POST /msg/{terminal} is single-pathed but accepts multi-recipient body.
    result = _post(recipients[0], payload, key)
    print(json.dumps(result))

    # CLIENT_STARTED_EMISSION_1 (G0 #11118 / lead #11121, first-action): a recipient's
    # FIRST NON-ACK reply to a dispatch marks that dispatch `started`. Fire when this reply
    # threads onto a dispatch (by --parent-id, or by --thread-id when no parent) AND is not
    # an ack (bus_post.py, unlike bus_post.sh, CAN post kind=ack — guard on it). The
    # /msg/<id>/started endpoint is the AUTHORITATIVE gate; this client fire is TOTAL
    # best-effort and its outcome NEVER changes this send's exit status. Kill switch:
    # BAKER_STARTED_EMISSION_DISABLED=1.
    if (
        (args.parent_id is not None or args.thread_id is not None)
        and args.kind != "ack"
        and os.environ.get("BAKER_STARTED_EMISSION_DISABLED", "") != "1"
    ):
        _emit_started_best_effort(sender, key, args.parent_id, args.thread_id)


if __name__ == "__main__":
    main()
