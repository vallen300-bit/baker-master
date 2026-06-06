#!/usr/bin/env python3
"""Terminal client for Baker's Qwen3 Clerk workbench."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_BASE_URL = "https://baker-master.onrender.com"
RUNNING_STATUSES = {"running"}


class ClerkQwenError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _load_json(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return {"raw": raw.decode("utf-8", errors="replace")}


def _onepassword_api_key() -> str:
    try:
        proc = subprocess.run(
            ["op", "read", "op://Baker API Keys/BAKER_API_KEY/credential"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def resolve_api_key(cli_value: str | None) -> str:
    value = (cli_value or "").strip()
    if value:
        return value
    value = (os.getenv("BAKER_API_KEY") or "").strip()
    if value:
        return value
    value = _onepassword_api_key()
    if value:
        return value
    raise ClerkQwenError(
        "Baker API key missing. Pass --api-key, set BAKER_API_KEY, or add the "
        "1Password item 'BAKER_API_KEY' in vault 'Baker API Keys'."
    )


def edit_url(base_url: str, session_id: str) -> str:
    base = base_url.rstrip("/")
    quoted = urllib.parse.quote(session_id, safe="")
    return f"{base}/clerk/edit/{quoted}"


class ClerkQwenClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def run(self, task: str) -> dict[str, Any]:
        return self._request("POST", "/api/clerk/run", {"task": task})

    def status(self, session_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/clerk/session/{urllib.parse.quote(session_id, safe='')}")

    def list_sessions(self, limit: int) -> dict[str, Any]:
        return self._request("GET", f"/api/clerk/sessions?limit={limit}")

    def _request(self, method: str, path: str, payload: Any | None = None) -> dict[str, Any]:
        url = self.base_url + path
        headers = {
            "Accept": "application/json",
            "X-Baker-Key": self.api_key,
        }
        data = None
        if payload is not None:
            data = _json_bytes(payload)
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                parsed = _load_json(resp.read())
                if not isinstance(parsed, dict):
                    raise ClerkQwenError(f"unexpected JSON response from {path}: {type(parsed).__name__}")
                return parsed
        except urllib.error.HTTPError as e:
            parsed = _load_json(e.read())
            raise ClerkQwenError(_error_message(parsed, f"HTTP {e.code} from {path}"), e.code, parsed) from None
        except urllib.error.URLError as e:
            raise ClerkQwenError(f"request failed for {path}: {e.reason}") from None


def _error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            return str(detail.get("reason") or detail.get("status") or fallback)
        return str(payload.get("error") or payload.get("status") or fallback)
    return fallback


def _session_reason(session: dict[str, Any]) -> str:
    result = session.get("result")
    if isinstance(result, dict):
        for key in ("reason", "error", "message"):
            if result.get(key):
                return str(result[key])
    for key in ("error", "reason"):
        if session.get(key):
            return str(session[key])
    return ""


def _print_session(session: dict[str, Any], base_url: str) -> None:
    session_id = str(session.get("session_id") or "")
    status = str(session.get("status") or "unknown")
    print(f"Session: {session_id or '(missing)'}")
    print(f"Status: {status}")
    if session_id:
        print(f"Edit URL: {edit_url(base_url, session_id)}")
    if session.get("draft_path"):
        print(f"Draft path: {session['draft_path']}")
    reason = _session_reason(session)
    if reason:
        print(f"Reason: {reason}")
    if status == "pending_approval":
        print("")
        print("PENDING APPROVAL: Director approval is required before Clerk can continue.")
        print(f"Session for approval: {session_id or '(missing)'}")
        if session_id:
            print(f"Approval review URL: {edit_url(base_url, session_id)}")
        print("How to approve: route this session_id and requested action to lead/Director approval.")


def _print_sessions(sessions: list[dict[str, Any]], base_url: str) -> None:
    if not sessions:
        print("No Clerk sessions.")
        return
    for item in sessions:
        session_id = str(item.get("session_id") or "")
        status = str(item.get("status") or "")
        created = str(item.get("created_at") or "")
        task = str(item.get("task") or "")
        print(f"{created:25} {status:16} {session_id:38} {task}")
        if session_id:
            print(f"  {edit_url(base_url, session_id)}")


def _wait_for_terminal(
    client: ClerkQwenClient,
    session_id: str,
    timeout_s: float,
    interval_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    last = client.status(session_id)
    while str(last.get("status") or "") in RUNNING_STATUSES and time.monotonic() < deadline:
        time.sleep(max(0.0, interval_s))
        last = client.status(session_id)
    return last


def cmd_run(args: argparse.Namespace) -> int:
    client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
    task = " ".join(args.task).strip()
    session = client.run(task)
    if args.wait and session.get("session_id"):
        session = _wait_for_terminal(client, str(session["session_id"]), args.timeout_s, args.interval_s)
    if args.json:
        print(json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_session(session, args.base_url)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
    session = client.status(args.session_id)
    if args.json:
        print(json.dumps(session, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_session(session, args.base_url)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
    payload = client.list_sessions(args.limit)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_sessions(payload.get("sessions") or [], args.base_url)
    return 0


def cmd_url(args: argparse.Namespace) -> int:
    print(edit_url(args.base_url, args.session_id))
    return 0


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--base-url",
        default=os.getenv("BAKER_BASE_URL") or os.getenv("BAKER_URL") or DEFAULT_BASE_URL,
        help=f"Baker dashboard base URL (default: {DEFAULT_BASE_URL})",
    )
    common.add_argument("--api-key", help="Baker API key; falls back to BAKER_API_KEY then 1Password")
    common.add_argument("--json", action="store_true", help="Print machine-readable JSON where applicable")

    parser = argparse.ArgumentParser(description="Qwen3 Clerk terminal client")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", parents=[common], help="Start a Clerk task")
    run.add_argument("task", nargs="+", help="Task text")
    run.add_argument("--wait", action="store_true", help="Poll until the session leaves running state")
    run.add_argument("--timeout-s", type=float, default=180.0, help="Maximum wait time for --wait")
    run.add_argument("--interval-s", type=float, default=2.0, help="Polling interval for --wait")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", parents=[common], help="Fetch one Clerk session")
    status.add_argument("session_id")
    status.set_defaults(func=cmd_status)

    list_cmd = sub.add_parser("list", parents=[common], help="List recent Clerk sessions")
    list_cmd.add_argument("--limit", type=int, default=10)
    list_cmd.set_defaults(func=cmd_list)

    url = sub.add_parser("url", parents=[common], help="Print the edit URL for a session")
    url.add_argument("session_id")
    url.set_defaults(func=cmd_url)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ClerkQwenError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
