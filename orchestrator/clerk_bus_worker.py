"""Server-side bus drain worker for the headless Qwen3 Clerk.

CLERK_QWEN3_BUS_AGENT: Clerk is a Brisen Lab bus agent on the existing
``clerk`` slug, but its primary runtime is the headless Qwen3 workbench rather
than a Terminal picker. This module polls Clerk's bus inbox, runs the existing
``run_clerk_task`` entry point, replies to the sender, and ACKs only after the
reply succeeds.
"""
from __future__ import annotations

import json
import logging
import os
import posixpath
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

import httpx

from config.settings import config

logger = logging.getLogger("baker.clerk_bus_worker")

_CLERK_SLUG = "clerk"
_CLERK_PICKER_PATH_DEFAULT = "/Users/dimitry/bm-clerk"
_CLERK_WORKING_PREFIX = "/Baker-Feed/Clerk-Workbench"
_TERMINAL_STATUSES = {"ready", "pending_approval", "blocked", "timeout", "error", "saved"}
_TASK_STATE_TIMEOUT_S = 3.0
_TASK_STATE_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="clerk-task-state")


class ClerkBusConfigError(RuntimeError):
    """Raised when the worker is enabled without the required runtime config."""


class ClerkSessionStore(Protocol):
    def get_session(self, session_id: str) -> dict[str, Any] | None:
        ...

    def create_session_if_absent(self, session_id: str, task: str, source_meta: dict[str, Any]) -> None:
        ...

    def update_session(self, session_id: str, **fields: Any) -> None:
        ...


@dataclass
class ClerkBusWorkerConfig:
    enabled: bool
    lab_url: str
    terminal_key: str
    forge_key: str
    poll_limit: int = 10
    batch_cap: int = 3
    http_timeout_s: float = 10.0
    event_interval_s: float = 45.0
    picker_path: str = _CLERK_PICKER_PATH_DEFAULT
    dashboard_url: str = "http://localhost:8080"
    reply_draft_chars: int = 2000

    @property
    def missing_required(self) -> list[str]:
        missing: list[str] = []
        if not self.terminal_key:
            missing.append("BRISEN_LAB_TERMINAL_KEY_clerk")
        if not self.forge_key:
            missing.append("FORGE_KEY")
        if not self.lab_url:
            missing.append("BRISEN_LAB_URL")
        return missing


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _usage_update_fields(result: dict[str, Any]) -> dict[str, Any]:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return {}
    fields: dict[str, Any] = {}
    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "context_window_used",
        "context_window_max",
    ):
        if key in usage:
            fields[key] = _int_or_none(usage.get(key))
    if "session_cost_usd" in usage:
        fields["session_cost_usd"] = _float_or_none(usage.get("session_cost_usd"))
    return fields


def _terminal_key_from_env() -> str:
    return (
        os.getenv("BRISEN_LAB_TERMINAL_KEY_clerk")
        or os.getenv("BRISEN_LAB_TERMINAL_KEY_CLERK")
        or ""
    ).strip()


def clerk_bus_worker_config_from_env() -> ClerkBusWorkerConfig:
    lab_url = (
        os.getenv("LAB_URL")
        or os.getenv("BRISEN_LAB_URL")
        or os.getenv("BRISEN_LAB_DAEMON_URL")
        or "https://brisen-lab.onrender.com"
    ).rstrip("/")
    return ClerkBusWorkerConfig(
        enabled=_env_bool("CLERK_BUS_WORKER_ENABLED", False),
        lab_url=lab_url,
        terminal_key=_terminal_key_from_env(),
        forge_key=os.getenv("FORGE_KEY", "").strip(),
        poll_limit=_bounded_int("CLERK_BUS_POLL_LIMIT", 10, 1, 25),
        batch_cap=_bounded_int("CLERK_BUS_BATCH_CAP", 3, 1, 10),
        http_timeout_s=_bounded_float("CLERK_BUS_HTTP_TIMEOUT_S", 10.0, 1.0, 60.0),
        event_interval_s=_bounded_float("CLERK_BUS_EVENT_INTERVAL_S", 45.0, 0.0, 120.0),
        picker_path=os.getenv("CLERK_PICKER_PATH", _CLERK_PICKER_PATH_DEFAULT),
        dashboard_url=(os.getenv("CLERK_DASHBOARD_URL") or config.outputs.dashboard_url).rstrip("/"),
        reply_draft_chars=_bounded_int("CLERK_BUS_REPLY_DRAFT_CHARS", 2000, 0, 10000),
    )


def clerk_bus_poll_interval_seconds() -> int:
    return _bounded_int("CLERK_BUS_POLL_INTERVAL_S", 60, 15, 300)


class DirectClerkSessionStore:
    """Short-lived direct Postgres access to the existing clerk_sessions table."""

    def _connect(self):
        if not config.postgres.host_direct:
            raise ClerkBusConfigError(
                "POSTGRES_HOST_DIRECT is required for clerk bus worker direct DB access"
            )
        import psycopg2

        return psycopg2.connect(connect_timeout=5, **config.postgres.direct_dsn_params)

    @staticmethod
    def _json_param(value: Any):
        import psycopg2.extras

        return psycopg2.extras.Json(value or {})

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        import psycopg2.extras

        conn = self._connect()
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT session_id, task, status, result_json, draft_content,
                           draft_path, source_meta, error, prompt_tokens,
                           completion_tokens, total_tokens, context_window_used,
                           context_window_max, session_cost_usd, created_at,
                           updated_at
                    FROM clerk_sessions
                    WHERE session_id = %s
                    LIMIT 1
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        finally:
            conn.close()

    def create_session_if_absent(self, session_id: str, task: str, source_meta: dict[str, Any]) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO clerk_sessions (session_id, task, status, source_meta)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (session_id) DO NOTHING
                    """,
                    (session_id, task, "running", self._json_param(source_meta)),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_session(self, session_id: str, **fields: Any) -> None:
        if not fields:
            return
        allowed = {
            "status",
            "result_json",
            "draft_content",
            "draft_path",
            "source_meta",
            "error",
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "context_window_used",
            "context_window_max",
            "session_cost_usd",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"unsupported clerk session fields: {sorted(unknown)}")

        sets: list[str] = []
        params: list[Any] = []
        for key, value in fields.items():
            sets.append(f"{key} = %s")
            if key in {"result_json", "source_meta"}:
                params.append(self._json_param(value))
            else:
                params.append(value)
        sets.append("updated_at = NOW()")
        params.append(session_id)

        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE clerk_sessions SET {', '.join(sets)} WHERE session_id = %s",
                    tuple(params),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


class ForgeJobTelemetry:
    """Job-scoped Brisen Lab card telemetry for the headless Clerk worker."""

    def __init__(self, cfg: ClerkBusWorkerConfig, http_client: httpx.Client):
        self.cfg = cfg
        self.http = http_client

    def register_session(self, session_id: str) -> None:
        payload = {
            "session_uuid": session_id,
            "terminal_alias": _CLERK_SLUG,
            "project_path": self.cfg.picker_path,
        }
        self._post("/api/register", payload)

    def event(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        body = {
            "session_uuid": session_id,
            "terminal_alias": _CLERK_SLUG,
            "event_type": event_type,
            "payload": payload,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        self._post("/api/event", body)

    def task_state(self, session_id: str, state: str) -> None:
        payload = {
            "terminal_alias": _CLERK_SLUG,
            "state": state,
            "session_uuid": session_id,
            "project_path": self.cfg.picker_path,
        }
        _TASK_STATE_EXECUTOR.submit(self._post_task_state, payload)

    def _post(self, path: str, payload: dict[str, Any]) -> None:
        self._post_with_client(self.http, path, payload, self.cfg.http_timeout_s)

    def _post_task_state(self, payload: dict[str, Any]) -> None:
        if isinstance(self.http, httpx.Client):
            with httpx.Client(timeout=_TASK_STATE_TIMEOUT_S) as http_client:
                self._post_with_client(
                    http_client,
                    "/api/agent-task-state",
                    payload,
                    _TASK_STATE_TIMEOUT_S,
                )
        else:
            self._post_with_client(
                self.http,
                "/api/agent-task-state",
                payload,
                _TASK_STATE_TIMEOUT_S,
            )

    def _post_with_client(
        self,
        http_client: Any,
        path: str,
        payload: dict[str, Any],
        timeout_s: float,
    ) -> None:
        try:
            resp = http_client.post(
                f"{self.cfg.lab_url}{path}",
                headers={"X-Forge-Key": self.cfg.forge_key, "Content-Type": "application/json"},
                json=payload,
                timeout=timeout_s,
            )
            resp.raise_for_status()
        except Exception as e:
            logger.warning(
                "clerk forge telemetry failed",
                extra={"path": path, "error_class": type(e).__name__},
            )


class ActiveForgeJob(AbstractContextManager):
    def __init__(
        self,
        telemetry: ForgeJobTelemetry,
        *,
        session_id: str,
        message_id: int,
        from_terminal: str,
        topic: str,
        interval_s: float,
    ):
        self.telemetry = telemetry
        self.session_id = session_id
        self.message_id = message_id
        self.from_terminal = from_terminal
        self.topic = topic
        self.interval_s = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self):
        payload = self._payload()
        self.telemetry.register_session(self.session_id)
        self.telemetry.event(self.session_id, "clerk_bus_job_started", payload)
        self.telemetry.task_state(self.session_id, "working")
        if self.interval_s > 0:
            self._thread = threading.Thread(target=self._active_loop, name=f"clerk-bus-{self.message_id}", daemon=True)
            self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        payload = self._payload()
        payload["result"] = "error" if exc_type else "done"
        self.telemetry.event(self.session_id, "clerk_bus_job_finished", payload)
        return False

    def _active_loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self.telemetry.event(self.session_id, "clerk_bus_job_active", self._payload())
            self.telemetry.task_state(self.session_id, "working")

    def _payload(self) -> dict[str, Any]:
        return {
            "bus_message_id": self.message_id,
            "from_terminal": self.from_terminal,
            "topic": self.topic,
        }


class ClerkBusWorker:
    def __init__(
        self,
        *,
        cfg: ClerkBusWorkerConfig | None = None,
        http_client: httpx.Client | None = None,
        store: ClerkSessionStore | None = None,
        run_clerk_task_fn: Callable[[str], dict[str, Any]] | None = None,
    ):
        self.cfg = cfg or clerk_bus_worker_config_from_env()
        self.http = http_client or httpx.Client(timeout=self.cfg.http_timeout_s)
        self.store = store or DirectClerkSessionStore()
        self.run_clerk_task = run_clerk_task_fn or _default_run_clerk_task
        self.telemetry = ForgeJobTelemetry(self.cfg, self.http)

    def poll_once(self) -> dict[str, Any]:
        if not self.cfg.enabled:
            return {"status": "disabled", "processed": 0, "acked": 0, "errors": 0}

        missing = self.cfg.missing_required
        if missing:
            logger.warning("clerk bus worker skipped; missing config: %s", ",".join(missing))
            return {"status": "skipped_config", "missing": missing, "processed": 0, "acked": 0, "errors": 0}

        try:
            messages = self._fetch_inbox()
        except Exception as e:
            logger.warning("clerk inbox fetch failed: %s", type(e).__name__)
            return {"status": "fetch_failed", "processed": 0, "acked": 0, "errors": 1}

        stats = {"status": "ok", "fetched": len(messages), "processed": 0, "acked": 0, "errors": 0}
        pending = [m for m in messages if not m.get("acknowledged_at")]
        for msg in pending[: self.cfg.batch_cap]:
            try:
                result = self.process_message(msg)
                stats["processed"] += 1
                if result.get("acked"):
                    stats["acked"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.exception("clerk bus message failed id=%s error=%s", msg.get("id"), type(e).__name__)
        return stats

    def _fetch_inbox(self) -> list[dict[str, Any]]:
        resp = self.http.get(
            f"{self.cfg.lab_url}/msg/{_CLERK_SLUG}",
            params={"limit": self.cfg.poll_limit},
            headers={"X-Terminal-Key": self.cfg.terminal_key},
            timeout=self.cfg.http_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            data = data.get("messages", [])
        if not isinstance(data, list):
            return []
        return [m for m in data if isinstance(m, dict)]

    def process_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        message_id = int(msg["id"])
        session_id = f"bus-{message_id}"
        sender = str(msg.get("from_terminal") or msg.get("sender") or "").strip()
        topic = str(msg.get("topic") or "dispatch/clerk").strip()

        if sender == _CLERK_SLUG:
            self._ack_message(message_id)
            return {"status": "skipped_self", "acked": True}
        if not sender:
            return {"status": "skipped_invalid", "acked": False}

        row = self.store.get_session(session_id) or {}
        existing_result = _coerce_dict(row.get("result_json"))

        if existing_result.get("bus_reply_message_id"):
            self._ack_message(message_id)
            return {"status": "already_replied", "acked": True}

        try:
            status = str(row.get("status") or "")
            if status in _TERMINAL_STATUSES and existing_result:
                result = existing_result
                draft_content = str(row.get("draft_content") or "")
                draft_path = row.get("draft_path")
                error = row.get("error")
            else:
                self.telemetry.task_state(session_id, "received")
                task = self._fetch_full_body(message_id)
                if not task:
                    logger.warning("clerk bus message skipped; full body unavailable id=%s", message_id)
                    return {"status": "skipped_invalid", "acked": False}
                self.store.create_session_if_absent(
                    session_id,
                    task,
                    {
                        "source": "bus",
                        "bus_message_id": message_id,
                        "from_terminal": sender,
                        "topic": topic,
                    },
                )
                with ActiveForgeJob(
                    self.telemetry,
                    session_id=session_id,
                    message_id=message_id,
                    from_terminal=sender,
                    topic=topic,
                    interval_s=self.cfg.event_interval_s,
                ):
                    result = self._run_task(task)
                status = str(result.get("status") or "error")
                draft_content, draft_path = _extract_draft(result)
                error = str(result.get("reason") or result.get("error") or "") or None
                usage_fields = _usage_update_fields(result)
                self.store.update_session(
                    session_id,
                    status=status,
                    result_json=result,
                    draft_content=draft_content,
                    draft_path=draft_path,
                    error=error,
                    **usage_fields,
                )

            reply_body = self._format_reply(
                message_id=message_id,
                session_id=session_id,
                result=result,
                draft_content=draft_content,
                draft_path=str(draft_path or ""),
                error=str(error or ""),
            )
            reply = self._post_reply(sender=sender, topic=topic, body=reply_body, parent_id=message_id)
            reply_message_id = reply.get("message_id") or reply.get("id") or "posted_without_id"
            result_with_reply = dict(result)
            result_with_reply["bus_reply_message_id"] = reply_message_id
            if reply.get("thread_id"):
                result_with_reply["bus_reply_thread_id"] = reply["thread_id"]
            try:
                self.store.update_session(session_id, result_json=result_with_reply)
            except Exception as e:
                # ACK is the durable bus-level dedup. After a successful reply POST,
                # marker persistence is best-effort; otherwise a transient DB write
                # failure can leave the inbound unacked and cause duplicate replies.
                # Residual at-least-once window: the ACK POST itself can still fail.
                logger.warning("clerk reply marker persist failed: %s", type(e).__name__)
            self._ack_message(message_id)
            return {"status": status, "acked": True, "reply_message_id": reply_message_id}
        finally:
            self.telemetry.task_state(session_id, "idle")

    def _fetch_full_body(self, message_id: int) -> str:
        try:
            resp = self.http.get(
                f"{self.cfg.lab_url}/event/{message_id}/full",
                headers={"X-Terminal-Key": self.cfg.terminal_key},
                timeout=self.cfg.http_timeout_s,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("clerk full body fetch failed id=%s error=%s", message_id, type(e).__name__)
            return ""
        if not isinstance(data, dict):
            logger.warning("clerk full body fetch returned non-dict id=%s", message_id)
            return ""
        body = data.get("body")
        return body.strip() if isinstance(body, str) else ""

    def _run_task(self, task: str) -> dict[str, Any]:
        try:
            result = self.run_clerk_task(task)
            if isinstance(result, dict):
                return result
            return {"status": "error", "error": "run_clerk_task returned non-dict result"}
        except BaseException as e:
            logger.warning("clerk bus run failed: %s", type(e).__name__)
            return {"status": "error", "error": "clerk bus run failed", "error_type": type(e).__name__}

    def _post_reply(self, *, sender: str, topic: str, body: str, parent_id: int) -> dict[str, Any]:
        payload = {
            "kind": "dispatch",
            "body": body,
            "to": [sender],
            "tier_required": "B",
            "topic": topic,
            "parent_id": parent_id,
        }
        resp = self.http.post(
            f"{self.cfg.lab_url}/msg/{sender}",
            headers={"X-Terminal-Key": self.cfg.terminal_key, "Content-Type": "application/json"},
            json=payload,
            timeout=self.cfg.http_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _ack_message(self, message_id: int) -> None:
        resp = self.http.post(
            f"{self.cfg.lab_url}/msg/{message_id}/ack",
            headers={"X-Terminal-Key": self.cfg.terminal_key},
            timeout=self.cfg.http_timeout_s,
        )
        resp.raise_for_status()

    def _format_reply(
        self,
        *,
        message_id: int,
        session_id: str,
        result: dict[str, Any],
        draft_content: str,
        draft_path: str,
        error: str,
    ) -> str:
        status = str(result.get("status") or "error")
        lines = [
            f"Clerk bus result for #{message_id}",
            f"Status: {status}",
            f"Session: {session_id}",
        ]
        edit_url = self._edit_url(session_id)
        if edit_url:
            lines.append(f"Edit: {edit_url}")
        if draft_path:
            lines.append(f"Draft path: {draft_path}")
        if status in {"pending_approval", "blocked"}:
            lines.append("Needs approval/blocker: " + str(result.get("reason") or error or status))
        elif status in {"timeout", "error"}:
            lines.append("Error: " + str(result.get("reason") or result.get("error") or error or status))
        elif result.get("answer"):
            lines.append("Answer: " + _single_line(str(result["answer"]), 1200))
        if draft_content and self.cfg.reply_draft_chars:
            lines.append("")
            lines.append("Draft preview:")
            lines.append(_truncate(draft_content, self.cfg.reply_draft_chars))
        return "\n".join(lines)

    def _edit_url(self, session_id: str) -> str:
        base = (self.cfg.dashboard_url or "").rstrip("/")
        if not base:
            return ""
        return f"{base}/clerk/edit/{session_id}"


def _default_run_clerk_task(task: str) -> dict[str, Any]:
    from orchestrator.clerk_runtime import run_clerk_task

    return run_clerk_task(task)


def _normalize_dropbox_path(path: str) -> str:
    raw = (path or "").strip()
    if not raw.startswith("/"):
        return ""
    normalized = posixpath.normpath(raw)
    if normalized == "." or not normalized.startswith("/"):
        return ""
    return normalized


def _extract_draft(result: dict[str, Any]) -> tuple[str, str | None]:
    content = ""
    path: str | None = None
    for call in result.get("tool_calls") or []:
        if not isinstance(call, dict) or call.get("name") != "file_save":
            continue
        args = call.get("input") or {}
        if not isinstance(args, dict):
            continue
        if isinstance(args.get("content"), str):
            content = args["content"]
        raw_path = args.get("dropbox_path")
        if isinstance(raw_path, str) and raw_path.strip():
            path = _normalize_dropbox_path(raw_path)
        elif isinstance(args.get("filename"), str):
            filename = Path(args["filename"]).name or "clerk-output.md"
            path = f"{_CLERK_WORKING_PREFIX}/{filename}"
    if not path:
        answer = str(result.get("answer") or "")
        match = re.search(r"Ready:\s*(/[^\s]+)", answer)
        if match:
            path = _normalize_dropbox_path(match.group(1))
    if not content:
        content = str(result.get("answer") or result.get("reason") or result.get("error") or "")
    return content, path or None


def _coerce_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 24)] + "\n[truncated by Clerk bus]"


def _single_line(text: str, limit: int) -> str:
    return _truncate(" ".join(text.split()), limit)


def poll_clerk_bus() -> dict[str, Any]:
    cfg = clerk_bus_worker_config_from_env()
    with httpx.Client(timeout=cfg.http_timeout_s) as http_client:
        return ClerkBusWorker(cfg=cfg, http_client=http_client).poll_once()
