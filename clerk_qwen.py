#!/usr/bin/env python3
"""Terminal client for Baker's Qwen3 Clerk workbench."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from typing import Any

DEFAULT_BASE_URL = "https://baker-master.onrender.com"
RUNNING_STATUSES = {"running"}
DRAFT_PREVIEW_CHARS = 600
CHAT_INTRO = 'Clerk Qwen3 (Brisen doc clerk) - type a task; "help" for reach/limits; exit to quit.'
CHAT_HELP_LINES = (
    "Reach: Gmail, Outlook/Graph, WhatsApp, Slack, transcripts, calendar, Dropbox/documents, sent mail, RSS/Substack, Baker search, internal bus.",
    "Limits: no money, no external sends, no production changes; risky acts return drafts or pending_approval.",
    "Usage: type a task. 'open' views the last result in your browser, 'show' prints it inline; add '<id>' for a specific session. Empty line, Ctrl-D, exit, or quit ends the session.",
)
NO_SESSION_MSG = "No session yet — run a Clerk task first, then use open."
OPEN_HINT = "  (type open to view in browser)"
# Session-id shapes: server sessions are UUIDs (dashboard.py uses str(uuid4()));
# bus sessions are "bus-<message_id>" (clerk_bus_worker.py). Used to decide
# whether `open <token>` is a local open-session command or a natural-language
# task like "open latest Peter email" that must pass through to Clerk.
_SESSION_ID_RE = re.compile(
    r"^(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}|bus-\d+)$"
)


def _is_session_id(token: str) -> bool:
    return bool(_SESSION_ID_RE.match(token.strip()))
CONTEXT_BAR_CELLS = 10
CONTEXT_BAR_FULL = "▓"
CONTEXT_BAR_EMPTY = "░"
CLERK_STATUS_LINE = '  ⏵⏵ read-only clerk · action-guardrails on · "help" for reach'


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
            ["op", "read", "op://Baker API Keys/API Baker/credential"],
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
        "1Password item 'API Baker' in vault 'Baker API Keys'."
    )


def edit_url(base_url: str, session_id: str) -> str:
    base = base_url.rstrip("/")
    quoted = urllib.parse.quote(session_id, safe="")
    return f"{base}/clerk/edit/{quoted}"


def _open_in_browser(url: str) -> bool:
    """Open url in the local default browser. Cross-platform via webbrowser,
    with a macOS `open` fallback. Returns True if a launcher was invoked."""
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    if sys.platform == "darwin":
        try:
            subprocess.run(["open", url], check=False, timeout=5)
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False
    return False


def _open_session(base_url: str, session_id: str) -> None:
    url = edit_url(base_url, session_id)
    if _open_in_browser(url):
        print(f"Opening {url}")
    else:
        print(f"Could not launch a browser. Edit URL: {url}")


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


def _result_payload(session: dict[str, Any]) -> dict[str, Any]:
    result = session.get("result")
    return result if isinstance(result, dict) else {}


def _first_text(payload: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _trim_preview(text: str, limit: int = DRAFT_PREVIEW_CHARS) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "..."


def _print_chat_result(session: dict[str, Any]) -> None:
    status = str(session.get("status") or "unknown")
    result = _result_payload(session)
    answer = _first_text(result, ("answer", "summary", "result", "message", "text", "output", "draft_preview"))
    if not answer and isinstance(result.get("path"), str) and result["path"].strip():
        answer = f"Ready: {result['path'].strip()}"
    reason = _session_reason(session)
    draft_content = session.get("draft_content")
    draft_path = session.get("draft_path")

    if (result.get("escalated") is True or status == "escalated") and reason:
        print(f"Escalated: {reason}")
        if answer:
            print(answer)
    elif status == "blocked" and reason:
        print(f"Blocked: {reason}")
    elif status == "pending_approval" and reason:
        print(f"Pending approval: {reason}")
    elif status == "error" and reason:
        print(f"Error: {reason}")
    elif answer:
        print(answer)
    elif reason:
        print(f"Reason: {reason}")
    else:
        print(f"Clerk finished with status: {status}")

    if isinstance(draft_content, str) and draft_content.strip():
        preview = _trim_preview(draft_content)
        if preview and preview != answer:
            print("")
            print("Draft preview:")
            print(preview)
    if draft_path:
        print(f"Ready path: {draft_path}")


def _print_chat_trailer(session: dict[str, Any], base_url: str) -> None:
    session_id = str(session.get("session_id") or "")
    status = str(session.get("status") or "unknown")
    print(f"Session: {session_id or '(missing)'}")
    print(f"Status: {status}")
    if session_id:
        print(f"Edit URL: {edit_url(base_url, session_id)}")


def _show_session(client: ClerkQwenClient, session_id: str, base_url: str) -> None:
    """Fetch a session and print its result content inline in the terminal
    (answer + draft preview + ready-path), no browser. May raise ClerkQwenError."""
    session = client.status(session_id)
    _print_chat_result(session)
    _print_chat_trailer(session, base_url)


def _print_turn_footer(session: dict[str, Any]) -> None:
    footer = _telemetry_footer(session)
    print("-" * max(len(line) for line in footer.splitlines()))
    print(footer)


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


def _run_task_and_wait(
    client: ClerkQwenClient,
    task: str,
    timeout_s: float,
    interval_s: float,
) -> dict[str, Any]:
    session = client.run(task)
    if session.get("session_id"):
        return _wait_for_terminal(client, str(session["session_id"]), timeout_s, interval_s)
    return session


def _number_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_text(value: Any) -> str:
    num = _number_or_none(value)
    if num is None:
        return "n/a"
    return str(int(num))


def _cost_text(value: Any) -> str:
    num = _number_or_none(value)
    if num is None:
        return "n/a"
    return f"{num:.6f}".rstrip("0").rstrip(".")


def _model_label(model: Any) -> str:
    raw = str(model or "").strip()
    normalized = raw.lower().strip()
    aliases = {
        "qwen/qwen3-coder-plus": "Qwen3 Plus",
        "qwen3-coder-plus": "Qwen3 Plus",
        "qwen/qwen3-coder": "Qwen3 Coder",
        "qwen3-coder": "Qwen3 Coder",
        "qwen/qwen3-coder-flash": "Qwen3 Flash",
        "qwen3-coder-flash": "Qwen3 Flash",
    }
    if normalized in aliases:
        return aliases[normalized]
    if not raw:
        return "Qwen3 Coder"
    tidied = raw.rsplit("/", 1)[-1].replace("_", "-").replace("-", " ")
    return " ".join(part.capitalize() for part in tidied.split()) or "Qwen3 Coder"


def _session_model(session: dict[str, Any], usage: dict[str, Any]) -> str:
    for source in (
        session.get("model"),
        session.get("clerk_model"),
        usage.get("model"),
        usage.get("clerk_model"),
        os.getenv("CLERK_QWEN_MODEL"),
    ):
        if isinstance(source, str) and source.strip():
            return source.strip()
    return "qwen3-coder"


def _context_pct(used: Any, max_ctx: Any) -> int | None:
    used_num = _number_or_none(used)
    max_num = _number_or_none(max_ctx)
    if used_num is None or max_num is None or max_num <= 0:
        return None
    pct = int((used_num / max_num) * 100 + 0.5)
    return max(0, min(100, pct))


def _context_bar(pct: int | None) -> str:
    if pct is None:
        filled = 0
    else:
        filled = int((pct / 10) + 0.5)
        filled = max(0, min(CONTEXT_BAR_CELLS, filled))
    return CONTEXT_BAR_FULL * filled + CONTEXT_BAR_EMPTY * (CONTEXT_BAR_CELLS - filled)


def _telemetry_line(session: dict[str, Any]) -> str:
    """One compact line: 'Model │ ▓▓░░ 23% │ $0.0042'. Shared by the inline
    fallback footer and the prompt_toolkit bottom bar."""
    usage = session.get("usage") if isinstance(session.get("usage"), dict) else {}
    used = session.get("context_window_used", usage.get("context_window_used"))
    max_ctx = session.get("context_window_max", usage.get("context_window_max"))
    cost = session.get("session_cost_usd", usage.get("session_cost_usd"))

    pct = _context_pct(used, max_ctx)
    pct_text = f"{pct}%" if pct is not None else "--%"
    return f"{_model_label(_session_model(session, usage))} │ {_context_bar(pct)} {pct_text} │ ${_cost_text(cost)}"


def _telemetry_footer(session: dict[str, Any]) -> str:
    # Inline fallback footer (non-TTY / no prompt_toolkit): telemetry + reach hint.
    return f"{_telemetry_line(session)}\n{CLERK_STATUS_LINE}"


# CLERK_REPL_FOOTER_BOTTOMBAR_1: Director wants a Claude-Code-style layout — the
# telemetry footer pinned at the very BOTTOM (below the input cursor), dim/compact,
# with the answer above the cursor. prompt_toolkit's bottom_toolbar gives exactly a
# persistent bar pinned below the input line. The reach hint is folded into the bar.
# Honesty: a terminal cannot render a literally smaller FONT (that's the Terminal
# profile's); dim/muted styling is the ceiling, which is what the bar uses.
_BOTTOM_BAR_HINT = "⏵⏵ read-only · guardrails on · 'help' for reach · 'open'/'show' last result"


def _bottom_toolbar_text(session: dict[str, Any] | None) -> str:
    """Single compact line for the prompt_toolkit bottom bar: telemetry (or a
    neutral placeholder before the first turn) + the folded reach hint."""
    telemetry = _telemetry_line(session) if session else _telemetry_line({})
    return f" {telemetry}  ·  {_BOTTOM_BAR_HINT} "


def _make_chat_prompt_session(state: dict[str, Any]) -> Any | None:
    """Return a prompt_toolkit PromptSession whose bottom bar renders the latest
    turn's telemetry, or None when prompt_toolkit is unavailable or stdio is not a
    TTY (piped / non-interactive) — in which case cmd_chat falls back to input()
    plus the inline footer, preserving the prior behavior exactly."""
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return None
    except (ValueError, OSError):
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.styles import Style
    except Exception:
        return None
    # Dim/muted + flat (noreverse) so the bar reads "smaller", not a loud reverse block.
    style = Style.from_dict({"bottom-toolbar": "fg:#999999 bg:#1c1c1c noreverse"})
    try:
        return PromptSession(
            style=style,
            bottom_toolbar=lambda: _bottom_toolbar_text(state.get("session")),
        )
    except Exception:
        return None


def cmd_run(args: argparse.Namespace) -> int:
    client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
    task = " ".join(args.task).strip()
    if args.wait:
        session = _run_task_and_wait(client, task, args.timeout_s, args.interval_s)
    else:
        session = client.run(task)
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


def cmd_open(args: argparse.Namespace) -> int:
    session_id = (args.session_id or "").strip()
    if not session_id:
        client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
        sessions = client.list_sessions(1).get("sessions") or []
        session_id = str(sessions[0].get("session_id") or "") if sessions else ""
        if not session_id:
            print(NO_SESSION_MSG)
            return 0
    _open_session(args.base_url, session_id)
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
    session_id = (args.session_id or "").strip()
    if not session_id:
        sessions = client.list_sessions(1).get("sessions") or []
        session_id = str(sessions[0].get("session_id") or "") if sessions else ""
        if not session_id:
            print(NO_SESSION_MSG)
            return 0
    if args.json:
        print(json.dumps(client.status(session_id), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _show_session(client, session_id, args.base_url)
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    client = ClerkQwenClient(args.base_url, resolve_api_key(args.api_key))
    print(CHAT_INTRO)
    last_session_id = ""
    # CLERK_REPL_FOOTER_BOTTOMBAR_1: in a TTY with prompt_toolkit, the telemetry
    # lives in a pinned dim bottom bar (state["session"] feeds it); otherwise we
    # fall back to input() + the inline footer below. `state` is the live handle
    # the bottom-bar callable reads each render.
    state: dict[str, Any] = {"session": None}
    pt_session = _make_chat_prompt_session(state)
    bottom_bar_mode = pt_session is not None
    while True:
        try:
            if bottom_bar_mode:
                task = pt_session.prompt("clerk> ").strip()
            else:
                task = input("clerk> ").strip()
        except EOFError:
            print("")
            return 0
        except KeyboardInterrupt:
            print("")
            return 0
        if task.lower() == "help":
            for line in CHAT_HELP_LINES:
                print(line)
            continue
        if task.lower() == "open":
            if not last_session_id:
                print(NO_SESSION_MSG)
            else:
                _open_session(args.base_url, last_session_id)
            continue
        if task.lower().startswith("open ") and _is_session_id(task.split(maxsplit=1)[1]):
            # "open <session-id>" — local open. Natural tasks like
            # "open latest Peter email" fall through to Clerk below.
            _open_session(args.base_url, task.split(maxsplit=1)[1].strip())
            continue
        if task.lower() == "show":
            if not last_session_id:
                print(NO_SESSION_MSG)
            else:
                try:
                    _show_session(client, last_session_id, args.base_url)
                except ClerkQwenError as e:
                    print(f"ERROR: {e}")
            continue
        if task.lower().startswith("show ") and _is_session_id(task.split(maxsplit=1)[1]):
            # "show <session-id>" — local inline print. Natural tasks like
            # "show me the nvidia docs" fall through to Clerk below.
            try:
                _show_session(client, task.split(maxsplit=1)[1].strip(), args.base_url)
            except ClerkQwenError as e:
                print(f"ERROR: {e}")
            continue
        if not task or task.lower() in {"exit", "quit"}:
            return 0
        try:
            session = _run_task_and_wait(client, task, args.timeout_s, args.interval_s)
            # Per-turn order: answer -> trailer -> (open-hint above the cursor) ->
            # blank -> next 'clerk>' prompt. In bottom-bar mode the telemetry is NOT
            # printed inline (it's pinned in the dim bottom bar); in fallback mode the
            # inline footer prints below the trailer, preserving prior behavior.
            _print_chat_result(session)
            _print_chat_trailer(session, args.base_url)
            if bottom_bar_mode:
                state["session"] = session
                if session.get("session_id"):
                    last_session_id = str(session["session_id"])
                    print(OPEN_HINT)
                print("")
            else:
                _print_turn_footer(session)
                if session.get("session_id"):
                    last_session_id = str(session["session_id"])
                    print(OPEN_HINT)
        except ClerkQwenError as e:
            print(f"ERROR: {e}")
        except KeyboardInterrupt:
            print("")
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

    chat = sub.add_parser("chat", parents=[common], help="Open an interactive Clerk prompt")
    chat.add_argument("--timeout-s", type=float, default=180.0, help="Maximum wait time for each task")
    chat.add_argument("--interval-s", type=float, default=2.0, help="Polling interval for each task")
    chat.set_defaults(func=cmd_chat)

    status = sub.add_parser("status", parents=[common], help="Fetch one Clerk session")
    status.add_argument("session_id")
    status.set_defaults(func=cmd_status)

    list_cmd = sub.add_parser("list", parents=[common], help="List recent Clerk sessions")
    list_cmd.add_argument("--limit", type=int, default=10)
    list_cmd.set_defaults(func=cmd_list)

    url = sub.add_parser("url", parents=[common], help="Print the edit URL for a session")
    url.add_argument("session_id")
    url.set_defaults(func=cmd_url)

    open_cmd = sub.add_parser("open", parents=[common], help="Open a session's edit URL in your browser")
    open_cmd.add_argument(
        "session_id",
        nargs="?",
        help="Session id to open; defaults to the most recent session",
    )
    open_cmd.set_defaults(func=cmd_open)

    show_cmd = sub.add_parser("show", parents=[common], help="Print a session's result inline in the terminal")
    show_cmd.add_argument(
        "session_id",
        nargs="?",
        help="Session id to show; defaults to the most recent session",
    )
    show_cmd.set_defaults(func=cmd_show)
    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["chat"]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ClerkQwenError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
