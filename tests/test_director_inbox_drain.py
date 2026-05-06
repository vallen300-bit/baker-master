"""Stage 2 — App-side Director-inbox drain unit tests
(BRISEN_LAB_APP_AUTOPOLL_INBOX_1).

Tests `_drain_director_inbox()` end-to-end via subprocess invocation of the
hook with stub HTTP daemon + fake `op` CLI on PATH. Stub serves canned
GET /msg/director, GET /msg/{role}, GET /event/{id}/full, POST /msg/{id}/ack
responses.

10-test list:
  1 — autopoll disabled (env=false) → no drain even if role+key set
  2 — non-director-facing role (b1) → no drain regardless of autopoll flag
  3 — Director key missing (env unset, op CLI absent) → fail-open silent
  4 — Director key via env var → drains
  5 — Director key via op CLI fallback (env unset, op present) → drains
  6 — ratify_required pinned at top of summary
  7 — full body fetched via /event/{id}/full (not preview-capped)
  8 — ack POSTed for each consumed message
  9 — last_seen marker file separate from self-inbox marker
 10 — daemon 503 on GET /msg/director → fail-open silent
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".claude" / "hooks" / "user-prompt-submit-confirm.py"


# ---------- stub HTTP daemon (path-aware) ----------

class _DrainStubHandler(BaseHTTPRequestHandler):
    # Fixture-controlled state
    _captured: list = []
    _director_msg_status = 200
    _director_rows: list = []
    _self_rows: list = []  # rows for /msg/{worker_slug}
    _full_bodies: dict = {}  # {msg_id: body_str}
    _ack_status = 200

    def _send_json(self, status: int, body: dict | list):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode("utf-8"))

    def do_GET(self):  # noqa: N802
        self._captured.append({"method": "GET", "path": self.path})
        # Path patterns: /msg/director, /msg/<role>, /event/<id>/full
        path = self.path.split("?")[0]
        if path == "/msg/director":
            if self._director_msg_status != 200:
                self.send_response(self._director_msg_status)
                self.end_headers()
                return
            self._send_json(200, {"messages": self._director_rows})
            return
        if path.startswith("/msg/"):
            # Self-inbox drain target — return empty by default
            self._send_json(200, {"messages": self._self_rows})
            return
        if path.startswith("/event/") and path.endswith("/full"):
            try:
                mid = int(path.split("/")[2])
            except (IndexError, ValueError):
                self._send_json(404, {"detail": "not_found"})
                return
            body = self._full_bodies.get(mid)
            if body is None:
                self._send_json(404, {"detail": "not_found"})
                return
            self._send_json(200, {"id": mid, "body": body})
            return
        self._send_json(404, {"detail": "not_found"})

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else ""
        self._captured.append({
            "method": "POST", "path": self.path, "body": body,
        })
        # /msg/<id>/ack is the only POST path the hook hits during drain
        if "/ack" in self.path:
            self.send_response(self._ack_status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        # Other POST paths (auth/register-session-pubkey, auth/human-confirmation)
        # — the hook only calls these for ratify-bearing roles when V2_ENABLED.
        # Tests run with role=lead (a ratify-bearing role) so the auth chain
        # would fire if BRISEN_LAB_TERMINAL_KEY were set. We deliberately
        # leave it unset → terminal_key="" → auth chain returns None silently.
        self.send_response(404)
        self.end_headers()

    def log_message(self, *_):
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def stub_daemon():
    """Start per-test stub HTTP daemon. Yields (url, captured_list)."""
    port = _free_port()
    captured: list = []
    _DrainStubHandler._captured = captured
    _DrainStubHandler._director_msg_status = 200
    _DrainStubHandler._director_rows = []
    _DrainStubHandler._self_rows = []
    _DrainStubHandler._full_bodies = {}
    _DrainStubHandler._ack_status = 200
    server = HTTPServer(("127.0.0.1", port), _DrainStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield (f"http://127.0.0.1:{port}", captured)
    finally:
        server.shutdown()
        server.server_close()


# ---------- fake `op` CLI shim (returns director key only) ----------

@pytest.fixture
def fake_op_dir(tmp_path):
    """Fake `op` returns 'op-fake-director-key' for the director ref, else
    exits non-zero (mirrors real op CLI behavior on missing item)."""
    op = tmp_path / "op"
    op.write_text(
        "#!/usr/bin/env bash\n"
        "if [ \"$1\" = read ] && echo \"$2\" | grep -q 'BRISEN_LAB_TERMINAL_KEY_director'; then\n"
        "    echo op-fake-director-key\n"
        "    exit 0\n"
        "fi\n"
        "echo 'item not found' >&2\n"
        "exit 1\n"
    )
    op.chmod(0o755)
    return tmp_path


# ---------- env / runner helpers ----------

def _base_env(extras: dict, *, fake_op: Path | None = None,
              tmpdir: Path | None = None) -> dict:
    """Hook subprocess env. V2 enabled. PATH optionally PATH-shimmed for op."""
    env = os.environ.copy()
    # Strip any pre-set values that could interfere
    for k in ("BAKER_ROLE", "BRISEN_LAB_APP_AUTOPOLL_ENABLED",
              "BRISEN_LAB_TERMINAL_KEY_director", "BRISEN_LAB_TERMINAL_KEY",
              "BRISEN_LAB_TERMINAL_KEY_lead"):
        env.pop(k, None)
    env["BRISEN_LAB_V2_ENABLED"] = "true"
    if fake_op is not None:
        env["PATH"] = f"{fake_op}:{env.get('PATH', '')}"
    else:
        # Strip any pre-existing 1Password CLI from PATH so tests asserting
        # "op CLI absent" actually exercise the missing-binary path. We do
        # this by pointing PATH at a /tmp dir that has no `op`.
        # Caller may override via fake_op_dir for the env-set case.
        pass
    if tmpdir is not None:
        env["TMPDIR"] = str(tmpdir)
    env.update(extras)
    return env


def _run_hook(env: dict, *, stdin_payload: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke hook subprocess with empty stdin (so auth chain skips:
    prompt is empty → role check still passes but _build_signed_payload's
    prompt is "" → harmless)."""
    if stdin_payload is None:
        stdin_payload = {"prompt": ""}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(stdin_payload),
        env=env, capture_output=True, text=True, timeout=20,
    )


def _hook_context(stdout: str) -> str:
    """Hook emits a single JSON line with hookSpecificOutput.additionalContext.
    Returns the additionalContext text (empty string if none emitted)."""
    if not stdout.strip():
        return ""
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return ""
    return (
        envelope.get("hookSpecificOutput", {}).get("additionalContext", "")
        or ""
    )


def _get_paths(captured: list) -> list:
    """Return GET paths with any ?query stripped."""
    return [
        c["path"].split("?", 1)[0]
        for c in captured if c.get("method") == "GET"
    ]


# ---------- canned fixtures ----------

DIRECTOR_ROW_RATIFY = {
    "id": 101,
    "kind": "ratify_required",
    "from_terminal": "lead",
    "topic": "ratify/decision/test",
    "body_preview": "preview text capped",
    "created_at": "2026-05-06T12:00:00Z",
}
DIRECTOR_ROW_DISPATCH = {
    "id": 102,
    "kind": "dispatch",
    "from_terminal": "b2",
    "topic": "dispatch/director/test",
    "body_preview": "dispatch preview",
    "created_at": "2026-05-06T12:01:00Z",
}


# ---------- tests ----------

def test_01_autopoll_disabled_no_drain(stub_daemon, fake_op_dir, tmp_path):
    """1 — autopoll disabled (env=false) → no drain even with role+key set."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "false",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    ctx = _hook_context(r.stdout)
    assert "Director" not in ctx, ctx
    # No GET /msg/director request issued
    assert "/msg/director" not in _get_paths(captured), captured


def test_02_non_director_facing_role_no_drain(stub_daemon, fake_op_dir, tmp_path):
    """2 — non-director-facing role (b1) → no drain regardless of autopoll flag."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    env = _base_env(
        {"BAKER_ROLE": "b1",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    assert "/msg/director" not in _get_paths(captured), captured


def test_03_director_key_missing_fail_open_silent(stub_daemon, tmp_path):
    """3 — Director key missing (env unset, op CLI absent) → fail-open silent."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_URL": url,
         "PATH": "/nonexistent-bin"},  # no op CLI on PATH
        tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    assert "/msg/director" not in _get_paths(captured), captured


def test_04_director_key_via_env_drains(stub_daemon, fake_op_dir, tmp_path):
    """4 — Director key via env var → drains and surfaces context."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    _DrainStubHandler._full_bodies = {102: "dispatch full body content"}
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    ctx = _hook_context(r.stdout)
    assert "Director inbox" in ctx, ctx
    assert "/msg/director" in _get_paths(captured), captured


def test_05_director_key_via_op_fallback_drains(stub_daemon, fake_op_dir, tmp_path):
    """5 — Director key via op CLI fallback (env unset, op present) → drains."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    _DrainStubHandler._full_bodies = {102: "via op cli"}
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         # BRISEN_LAB_TERMINAL_KEY_director NOT set → op CLI fallback
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    ctx = _hook_context(r.stdout)
    assert "Director inbox" in ctx, ctx
    assert "/msg/director" in _get_paths(captured), captured


def test_06_ratify_required_pinned_at_top(stub_daemon, fake_op_dir, tmp_path):
    """6 — ratify_required pinned at top of summary; chronological below."""
    url, _ = stub_daemon
    # Order in raw rows: dispatch BEFORE ratify_required. Pin must reorder.
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH, DIRECTOR_ROW_RATIFY]
    _DrainStubHandler._full_bodies = {
        101: "ratify body",
        102: "dispatch body",
    }
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    ctx = _hook_context(r.stdout)
    # Both sections present
    assert "Director-Q (ratify_required)" in ctx, ctx
    assert "Director inbox (chronological)" in ctx, ctx
    # ratify section appears BEFORE chronological section
    assert ctx.index("Director-Q (ratify_required)") < ctx.index(
        "Director inbox (chronological)"), ctx


def test_07_full_body_via_event_full_endpoint(stub_daemon, fake_op_dir, tmp_path):
    """7 — body sourced from /event/{id}/full, not preview-capped."""
    url, captured = stub_daemon
    long_body = "X" * 500  # well over the 140-char self-inbox cap
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    _DrainStubHandler._full_bodies = {102: long_body}
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    ctx = _hook_context(r.stdout)
    # full body present (not the row's preview)
    assert long_body in ctx, ctx[:200]
    assert "/event/102/full" in _get_paths(captured), captured


def test_08_ack_posted_for_each_message(stub_daemon, fake_op_dir, tmp_path):
    """8 — POST /msg/{id}/ack fired for every consumed message."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH, DIRECTOR_ROW_RATIFY]
    _DrainStubHandler._full_bodies = {101: "r", 102: "d"}
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    _run_hook(env)
    posts = [c for c in captured if c.get("method") == "POST"]
    ack_paths = sorted(c["path"] for c in posts if "/ack" in c["path"])
    assert ack_paths == ["/msg/101/ack", "/msg/102/ack"], ack_paths


def test_09_marker_files_isolated(stub_daemon, fake_op_dir, tmp_path):
    """9 — Director-inbox marker is a separate file from self-inbox marker.

    Run hook with both inboxes returning rows; assert both marker files
    exist on disk after, and they are distinct paths.
    """
    url, _ = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    _DrainStubHandler._self_rows = [
        # Existing _drain_inbox() reads from /msg/lead via the worker's
        # own terminal key. Provide a self-inbox row for the lead path.
        {"id": 201, "kind": "dispatch", "from_terminal": "b2",
         "topic": "dispatch/lead/x", "body_preview": "self-row",
         "created_at": "2026-05-06T11:55:00Z"},
    ]
    _DrainStubHandler._full_bodies = {102: "director full"}
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         # Self-inbox drain needs a key for role=lead
         "BRISEN_LAB_TERMINAL_KEY_lead": "lead-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    _run_hook(env)
    self_marker = tmp_path / "baker-brisen-lab-lastseen-lead.txt"
    dir_marker = tmp_path / "baker-brisen-lab-lastseen-director-via-lead.txt"
    assert self_marker.exists(), list(tmp_path.iterdir())
    assert dir_marker.exists(), list(tmp_path.iterdir())
    assert self_marker != dir_marker


def test_10_daemon_503_fail_open_silent(stub_daemon, fake_op_dir, tmp_path):
    """10 — daemon 503 on GET /msg/director → fail-open silent (no traceback,
    no Director-* text in additionalContext)."""
    url, _ = stub_daemon
    _DrainStubHandler._director_msg_status = 503
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         "BRISEN_LAB_TERMINAL_KEY_director": "dir-env-key",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    ctx = _hook_context(r.stdout)
    assert "Director" not in ctx, ctx
    assert "Traceback" not in r.stderr, r.stderr


def test_11_director_key_op_ref_in_env_resolves(stub_daemon, fake_op_dir, tmp_path):
    """11 — env BRISEN_LAB_TERMINAL_KEY_director set to literal `op://...` ref
    (Cowork-App settings.local.json behavior — does NOT auto-resolve op refs)
    is resolved via op CLI at hook runtime → drain succeeds.

    Pins the AH1-App diagnosis 2026-05-06 fix (`_resolve_terminal_key` helper).
    Pre-fix behavior: hook sent the 63-char op-ref as X-Terminal-Key → daemon
    401 bad_terminal_key → silent no-drain. Post-fix: ref is resolved before
    use; daemon receives literal key and serves the inbox."""
    url, captured = stub_daemon
    _DrainStubHandler._director_rows = [DIRECTOR_ROW_DISPATCH]
    _DrainStubHandler._full_bodies = {102: "drained via op-ref resolution"}
    env = _base_env(
        {"BAKER_ROLE": "lead",
         "BRISEN_LAB_APP_AUTOPOLL_ENABLED": "true",
         # Literal op-ref — Cowork-App env behavior:
         "BRISEN_LAB_TERMINAL_KEY_director":
             "op://Baker API Keys/BRISEN_LAB_TERMINAL_KEY_director/credential",
         "BRISEN_LAB_URL": url},
        fake_op=fake_op_dir, tmpdir=tmp_path,
    )
    r = _run_hook(env)
    assert r.returncode == 0
    ctx = _hook_context(r.stdout)
    assert "Director inbox" in ctx, ctx
    assert "drained via op-ref resolution" in ctx, ctx
    # Must have hit /msg/director with the resolved key (fake_op returns
    # 'op-fake-director-key'); pre-fix this would not have appeared.
    assert "/msg/director" in _get_paths(captured), captured
