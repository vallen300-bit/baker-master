"""Dispatcher ClickUp-to-bus relay.

Default-off service bridge:
- reads Dispatcher ClickUp tasks,
- sends due/blocked/stale items to the task owner on the bus,
- records the ClickUp task <-> bus thread mapping,
- copies bus replies back into ClickUp comments.

No terminal agent, no LLM call, no Director recipient.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from orchestrator.dispatcher import (
    RESERVED_RECIPIENTS,
    DispatcherPacket,
    format_packet_for_bus,
    parse_schedule_packet,
    resolve_owner_slug,
)

logger = logging.getLogger("sentinel.dispatcher")

_ENABLED_ENV = "DISPATCHER_ENABLED"
_LIST_ID_ENV = "DISPATCHER_CLICKUP_LIST_ID"
_BUS_URL_ENV = "DISPATCHER_BUS_URL"
_KEY_ENV = "BRISEN_LAB_TERMINAL_KEY_DISPATCHER"
_MAX_POSTS_ENV = "DISPATCHER_MAX_BUS_POSTS_PER_TICK"
_STALE_HOURS_ENV = "DISPATCHER_STALE_HOURS"
_DEFAULT_BUS_URL = "https://brisen-lab.onrender.com"
_DEFAULT_MAX_POSTS = 10
_DEFAULT_STALE_HOURS = 24

VALID_REASONS = frozenset({"due", "blocked", "unblocked", "stale", "needs_clarification"})


def dispatcher_enabled() -> bool:
    raw = os.environ.get(_ENABLED_ENV, "false")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def dispatcher_max_posts_per_tick() -> int:
    try:
        value = int(os.environ.get(_MAX_POSTS_ENV, str(_DEFAULT_MAX_POSTS)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX_POSTS
    return max(0, min(value, 50))


def dispatcher_stale_hours() -> int:
    try:
        value = int(os.environ.get(_STALE_HOURS_ENV, str(_DEFAULT_STALE_HOURS)))
    except (TypeError, ValueError):
        return _DEFAULT_STALE_HOURS
    return max(1, min(value, 24 * 14))


def make_condition_hash(packet: DispatcherPacket) -> str:
    raw = json.dumps(
        {
            "due_at": packet.due_at.isoformat(),
            "required_action": packet.required_action,
            "condition_precedent": packet.condition_precedent,
            "blocked_by": packet.blocked_by,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def make_dedup_key(
    clickup_task_id: str,
    recipient_slug: str,
    reason_code: str,
    condition_hash: str,
) -> str:
    base = f"{clickup_task_id}:{recipient_slug}:{reason_code}:{condition_hash}"
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]
    return f"dispatcher:{base}:{digest}"


def _json_param(payload: dict[str, Any]) -> Any:
    try:
        import psycopg2.extras

        return psycopg2.extras.Json(payload)
    except Exception:
        return json.dumps(payload)


def _extract_field(text: str, field: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(field)}\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(text or "")
    return match.group(1).strip() if match else ""


def _task_text(task: dict[str, Any]) -> str:
    return str(task.get("description") or task.get("text_content") or "")


def _task_tags(task: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for tag in task.get("tags") or []:
        if isinstance(tag, dict):
            name = tag.get("name")
        else:
            name = tag
        if name:
            out.add(str(name).strip().lower())
    return out


def _is_dispatcher_task(task: dict[str, Any]) -> bool:
    text = _task_text(task).lstrip()
    return "dispatcher" in _task_tags(task) or text.upper().startswith("DISPATCHER PACKET")


def _parse_clickup_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status_text(task: dict[str, Any]) -> str:
    status = task.get("status")
    if isinstance(status, dict):
        return str(status.get("status") or "").strip().lower()
    return str(status or "").strip().lower()


def dispatch_reason_for_task(task: dict[str, Any], *, now: Optional[datetime] = None) -> Optional[str]:
    current = now or datetime.now(timezone.utc)
    status = _status_text(task)
    due = _parse_clickup_datetime(task.get("due_date"))
    updated = _parse_clickup_datetime(task.get("date_updated"))
    if "blocked" in status:
        return "blocked"
    if status in {"ready", "unblocked"}:
        return "unblocked"
    if due and due <= current:
        return "due"
    if updated and (current - updated).total_seconds() >= dispatcher_stale_hours() * 3600:
        return "stale"
    return None


def _bus_key() -> str:
    return os.environ.get(_KEY_ENV, "").strip()


def _request_json(
    method: str,
    url: str,
    *,
    key: str,
    payload: Optional[dict[str, Any]] = None,
    timeout: int = 15,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"X-Terminal-Key": key}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        return {"ok": False, "error": f"http_{e.code}", "body": body}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _bus_message_id(result: dict[str, Any]) -> Optional[int]:
    for key in ("id", "message_id", "event_id"):
        value = result.get(key)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    event = result.get("event")
    if isinstance(event, dict) and event.get("id") is not None:
        try:
            return int(event["id"])
        except (TypeError, ValueError):
            return None
    message = result.get("message")
    if isinstance(message, dict) and message.get("id") is not None:
        try:
            return int(message["id"])
        except (TypeError, ValueError):
            return None
    return None


def post_bus_message(recipient_slug: str, body: str, *, topic: str) -> dict[str, Any]:
    recipient = resolve_owner_slug(recipient_slug)
    if not recipient or recipient in RESERVED_RECIPIENTS:
        return {"ok": False, "error": "invalid_recipient"}
    key = _bus_key()
    if not key:
        return {"ok": False, "error": "dispatcher_key_missing"}
    base = os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")
    payload = {
        "kind": "dispatch",
        "body": body,
        "to": [recipient],
        "tier_required": "B",
        "topic": topic,
    }
    result = _request_json("POST", f"{base}/msg/{recipient}", key=key, payload=payload)
    if result.get("error"):
        return result
    result["ok"] = True
    return result


def read_dispatcher_inbox(limit: int = 50) -> list[dict[str, Any]]:
    key = _bus_key()
    if not key:
        return []
    base = os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")
    result = _request_json("GET", f"{base}/msg/dispatcher?unread=true&limit={int(limit)}", key=key)
    if isinstance(result, list):
        return result
    return list(result.get("messages") or result.get("events") or [])


def read_bus_event(event_id: int) -> dict[str, Any]:
    key = _bus_key()
    if not key:
        return {}
    base = os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")
    result = _request_json("GET", f"{base}/event/{int(event_id)}/full", key=key)
    return result if isinstance(result, dict) else {}


def ack_bus_event(event_id: int) -> bool:
    key = _bus_key()
    if not key:
        return False
    base = os.environ.get(_BUS_URL_ENV, _DEFAULT_BUS_URL).rstrip("/")
    result = _request_json("POST", f"{base}/msg/{int(event_id)}/ack", key=key)
    return not result.get("error")


def reserve_dispatch(
    conn: Any,
    *,
    clickup_task_id: str,
    owner_slug: str,
    recipient_slug: str,
    reason_code: str,
    condition_hash: str,
    dedup_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, bus_message_id
            FROM dispatcher_bus_threads
            WHERE dedup_key = %s
            LIMIT 1
            """,
            (dedup_key,),
        )
        existing = cur.fetchone()
        if existing:
            status = existing[1]
            bus_message_id = existing[2]
            if status == "failed" and bus_message_id is None:
                cur.execute(
                    """
                    UPDATE dispatcher_bus_threads
                    SET status = 'open',
                        payload = payload || %s,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (_json_param({"retry_at": datetime.now(timezone.utc).isoformat()}), existing[0]),
                )
                row = cur.fetchone()
                return {"reserved": True, "id": row[0], "retry": True}
            return {
                "reserved": False,
                "id": existing[0],
                "status": status,
                "bus_message_id": bus_message_id,
            }
        cur.execute(
            """
            INSERT INTO dispatcher_bus_threads
                (clickup_task_id, owner_slug, recipient_slug, reason_code,
                 condition_hash, payload, dedup_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (dedup_key) DO NOTHING
            RETURNING id
            """,
            (
                clickup_task_id,
                owner_slug,
                recipient_slug,
                reason_code,
                condition_hash,
                _json_param(payload),
                dedup_key,
            ),
        )
        row = cur.fetchone()
    return {"reserved": True, "id": row[0]} if row else {"reserved": False, "id": None}


def complete_dispatch(
    conn: Any,
    *,
    dispatch_id: int,
    bus_message_id: Optional[int],
    bus_thread_id: Optional[str] = None,
    payload: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dispatcher_bus_threads
            SET status = 'waiting_reply',
                bus_message_id = %s,
                bus_thread_id = %s,
                last_sent_at = NOW(),
                payload = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (bus_message_id, bus_thread_id, _json_param(payload), dispatch_id),
        )


def mark_dispatch_failed(
    conn: Any,
    *,
    dispatch_id: int,
    payload: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dispatcher_bus_threads
            SET status = 'failed',
                bus_message_id = NULL,
                payload = payload || %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (_json_param(payload), dispatch_id),
        )


def mark_waiting_room_error(
    conn: Any,
    *,
    dispatch_id: int,
    error: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dispatcher_bus_threads
            SET payload = payload || %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (_json_param({"waiting_room_error": error[:500]}), dispatch_id),
        )


def record_reply(conn: Any, *, clickup_task_id: str, payload: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE dispatcher_bus_threads
            SET status = 'replied',
                last_reply_at = NOW(),
                payload = payload || %s,
                updated_at = NOW()
            WHERE clickup_task_id = %s
              AND status IN ('open', 'waiting_reply')
            """,
            (_json_param(payload), clickup_task_id),
        )


def resolve_reply_clickup_task_id(
    conn: Any,
    *,
    event: dict[str, Any],
    body: str,
) -> Optional[str]:
    parent_id = event.get("parent_id")
    thread_id = event.get("thread_id")
    event_id = event.get("id")
    with conn.cursor() as cur:
        if parent_id is not None:
            cur.execute(
                """
                SELECT clickup_task_id
                FROM dispatcher_bus_threads
                WHERE bus_message_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (parent_id,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        if thread_id:
            cur.execute(
                """
                SELECT clickup_task_id
                FROM dispatcher_bus_threads
                WHERE bus_thread_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (thread_id,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        if event_id is not None:
            cur.execute(
                """
                SELECT clickup_task_id
                FROM dispatcher_bus_threads
                WHERE bus_message_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (event_id,),
            )
            row = cur.fetchone()
            if row:
                return row[0]
    return None


def _post_waiting_room(
    conn: Any,
    *,
    packet: DispatcherPacket,
    clickup_task_id: str,
    reason_code: str,
    payload: dict[str, Any],
) -> Optional[str]:
    if packet.flight_type != "chartered":
        return None
    try:
        from orchestrator.waiting_room import upsert_item

        upsert_item(
            conn,
            flight_type=packet.flight_type,
            item_type="clickup_task",
            item_ref=clickup_task_id,
            owner_slug=packet.owner_slug,
            reason_code=f"dispatcher_{reason_code}",
            ready_after=packet.due_at,
            payload=payload,
        )
    except Exception as e:
        logger.warning("dispatcher waiting-room update failed: %s", e)
        return str(e)
    return None


def _clickup_task_id(task: dict[str, Any]) -> str:
    return str(task.get("id") or task.get("task_id") or "").strip()


def _send_clarification(
    *,
    task: dict[str, Any],
    errors: list[str],
    source_slug: str,
) -> dict[str, Any]:
    recipient = resolve_owner_slug(source_slug) or "lead"
    if recipient in RESERVED_RECIPIENTS:
        recipient = "lead"
    task_id = _clickup_task_id(task) or "unknown"
    body = (
        f"TO: {recipient}\n"
        "FROM: dispatcher\n"
        f"RE: Dispatcher packet needs clarification\n\n"
        f"ClickUp task: {task_id}\n"
        f"Errors: {', '.join(errors)}\n"
        "Required action: correct the DISPATCHER PACKET fields."
    )
    return post_bus_message(recipient, body, topic="dispatcher/needs-clarification")


def dispatch_task(task: dict[str, Any], conn: Any, *, now: Optional[datetime] = None) -> dict[str, Any]:
    task_id = _clickup_task_id(task)
    if not task_id:
        return {"skipped": True, "reason": "missing_task_id"}
    reason = dispatch_reason_for_task(task, now=now)
    if reason is None:
        return {"skipped": True, "reason": "not_due"}
    parsed = parse_schedule_packet(_task_text(task))
    if not parsed.ok or not parsed.packet:
        source_slug = _extract_field(_task_text(task), "source")
        condition_hash = hashlib.sha256(
            json.dumps(parsed.errors, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        recipient = resolve_owner_slug(source_slug) or "lead"
        if recipient in RESERVED_RECIPIENTS:
            recipient = "lead"
        dedup_key = make_dedup_key(task_id, recipient, "needs_clarification", condition_hash)
        reserved = reserve_dispatch(
            conn,
            clickup_task_id=task_id,
            owner_slug=recipient,
            recipient_slug=recipient,
            reason_code="needs_clarification",
            condition_hash=condition_hash,
            dedup_key=dedup_key,
            payload={"clickup_task_id": task_id, "errors": parsed.errors},
        )
        if not reserved.get("reserved"):
            return {"skipped": True, "reason": "duplicate_clarification", "id": reserved.get("id")}
        result = _send_clarification(task=task, errors=parsed.errors, source_slug=source_slug)
        if result.get("ok"):
            complete_dispatch(
                conn,
                dispatch_id=int(reserved["id"]),
                bus_message_id=_bus_message_id(result),
                bus_thread_id=result.get("thread_id"),
                payload={"clickup_task_id": task_id, "errors": parsed.errors},
            )
        else:
            mark_dispatch_failed(
                conn,
                dispatch_id=int(reserved["id"]),
                payload={"bus_error": result.get("error", "unknown"), "errors": parsed.errors},
            )
        return {"ok": bool(result.get("ok")), "reason": "needs_clarification"}

    packet = parsed.packet
    condition_hash = make_condition_hash(packet)
    dedup_key = make_dedup_key(task_id, packet.owner_slug, reason, condition_hash)
    payload = {
        "clickup_task_id": task_id,
        "reason_code": reason,
        "condition_hash": condition_hash,
        "title": packet.title,
    }
    reserved = reserve_dispatch(
        conn,
        clickup_task_id=task_id,
        owner_slug=packet.owner_slug,
        recipient_slug=packet.owner_slug,
        reason_code=reason,
        condition_hash=condition_hash,
        dedup_key=dedup_key,
        payload=payload,
    )
    if not reserved.get("reserved"):
        return {"skipped": True, "reason": "duplicate", "id": reserved.get("id")}

    body = format_packet_for_bus(packet, status=reason, clickup_task_id=task_id)
    result = post_bus_message(packet.owner_slug, body, topic=f"dispatcher/{reason}")
    if not result.get("ok"):
        mark_dispatch_failed(
            conn,
            dispatch_id=int(reserved["id"]),
            payload={**payload, "bus_error": result.get("error", "unknown")},
        )
        return {"ok": False, "reason": "bus_failed", "error": result.get("error")}

    message_id = _bus_message_id(result)
    complete_payload = {
        **payload,
        "bus_message_id": message_id,
        "bus_thread_id": result.get("thread_id"),
    }
    complete_dispatch(
        conn,
        dispatch_id=int(reserved["id"]),
        bus_message_id=message_id,
        bus_thread_id=result.get("thread_id"),
        payload=complete_payload,
    )
    waiting_error = _post_waiting_room(
        conn,
        packet=packet,
        clickup_task_id=task_id,
        reason_code=reason,
        payload=complete_payload,
    )
    if waiting_error:
        mark_waiting_room_error(conn, dispatch_id=int(reserved["id"]), error=waiting_error)
    return {"ok": True, "id": reserved["id"], "bus_message_id": message_id}


def _extract_clickup_task_id(text: str) -> Optional[str]:
    match = re.search(r"ClickUp task:\s*([A-Za-z0-9_-]+)", text or "", re.IGNORECASE)
    return match.group(1) if match else None


def dispatch_done_gate(
    client: Any, task_id: Optional[str], *, expected_list_id: str
) -> dict[str, Any]:
    """Deterministic done-gate for a Dispatcher ClickUp write (DISPATCHER_HARNESS_RETROFIT_1 B4).

    A dispatch write to ``task_id`` is DONE/ALLOWED only when the target is a REAL
    ClickUp task at the declared BAKER-space list — "posted" alone is NOT done. The
    gate re-fetches the task by ID (``client.get_task_detail``) and confirms, in order:
      * the task exists and its returned ID matches (fabricated/absent id -> FAIL, AC4),
      * it sits at the declared dispatcher list ``DISPATCHER_CLICKUP_LIST_ID``
        (wrong list -> FAIL, AC4 "confirmed at the declared list"),
      * its space is the BAKER space ``901510186446`` (non-BAKER -> FAIL, B2/AC3 cage).

    Called CONFIRM-THEN-WRITE (before the comment write) so a fabricated or out-of-cage
    target is REJECTED before any write happens — "posted" can never precede "confirmed".
    Pure code: no model call, no self-judgment. Fault-tolerant: a re-fetch error is a
    gate FAIL, never a crash. Returns ``{"ok": bool, "reason": str}``.
    """
    from clickup_client import _BAKER_SPACE_ID

    if not task_id:
        return {"ok": False, "reason": "no_task_id"}
    if not expected_list_id:
        return {"ok": False, "reason": "no_declared_list"}
    try:
        detail = client.get_task_detail(task_id)
    except Exception as e:  # a re-fetch failure is a gate FAIL, not a crash
        return {"ok": False, "reason": f"refetch_error:{e}"}
    if not isinstance(detail, dict) or not detail.get("id"):
        return {"ok": False, "reason": "task_absent"}
    got_id = str(detail.get("id"))
    if got_id != str(task_id):
        return {"ok": False, "reason": f"id_mismatch:{got_id}"}
    list_id = str((detail.get("list") or {}).get("id") or "")
    if list_id != str(expected_list_id):
        return {"ok": False, "reason": f"wrong_list:{list_id or 'unknown'}"}
    space_id = str((detail.get("space") or {}).get("id") or "")
    if not space_id:
        # FAIL-CLOSED (codex #6437 F1): a real ClickUp task ALWAYS carries its space.
        # A missing/unknown space is NOT a confirmed cage — reject rather than write.
        # The prior `if space_id and ...` guard let unknown-space fall through to
        # confirmed, and _check_write_allowed does not cage space either, so nothing
        # downstream caught it.
        return {"ok": False, "reason": "unknown_space"}
    if space_id != _BAKER_SPACE_ID:
        return {"ok": False, "reason": f"non_baker_space:{space_id}"}
    return {"ok": True, "reason": "confirmed"}


def process_replies(client: Any, store: Any) -> dict[str, Any]:
    messages = read_dispatcher_inbox()
    if not messages:
        return {"ok": True, "processed": 0}
    conn = store._get_conn()
    if not conn:
        return {"skipped": True, "reason": "database_unavailable"}
    processed = 0
    try:
        for msg in messages:
            msg_id = msg.get("id")
            if msg.get("acknowledged_at") or msg_id is None:
                continue
            event = read_bus_event(int(msg_id))
            body = str(event.get("body") or msg.get("body") or "")
            task_id = resolve_reply_clickup_task_id(conn, event={**msg, **event}, body=body)
            if not task_id:
                logger.warning("dispatcher reply missing ClickUp task id: %s", msg_id)
                continue
            # DISPATCHER_HARNESS_RETROFIT_1 (B4 done-gate + B2 cage): confirm the reply
            # target is a REAL task at the declared BAKER-space list BEFORE writing.
            # "Posted" is not done; a fabricated or out-of-cage target is REJECTED and
            # no comment is written (deterministic, no model call).
            gate = dispatch_done_gate(
                client, task_id, expected_list_id=os.environ.get(_LIST_ID_ENV, "").strip()
            )
            if not gate["ok"]:
                logger.warning(
                    "dispatcher done-gate REJECTED reply for task %s: %s",
                    task_id, gate["reason"],
                )
                continue
            comment = (
                f"Dispatcher bus reply from {event.get('from_terminal') or msg.get('from_terminal') or 'unknown'}\n\n"
                f"{body[:3000]}"
            )
            posted = client.post_comment(task_id, comment)
            if not posted:
                logger.warning("dispatcher failed to write ClickUp reply comment for %s", task_id)
                continue
            if conn:
                try:
                    record_reply(
                        conn,
                        clickup_task_id=task_id,
                        payload={"last_reply_event_id": msg_id, "last_reply_body": body[:1000]},
                    )
                    conn.commit()
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logger.warning("dispatcher reply DB update failed: %s", e)
            if ack_bus_event(int(msg_id)):
                processed += 1
    finally:
        store._put_conn(conn)
    return {"ok": True, "processed": processed}


def dispatch_due_tasks(client: Any, store: Any, *, now: Optional[datetime] = None) -> dict[str, Any]:
    if os.environ.get("BAKER_CLICKUP_READONLY", "").lower() == "true":
        return {"skipped": True, "reason": "clickup_readonly"}
    list_id = os.environ.get(_LIST_ID_ENV, "").strip()
    if not list_id:
        return {"skipped": True, "reason": f"{_LIST_ID_ENV} missing"}
    cap = dispatcher_max_posts_per_tick()
    if cap <= 0:
        return {"skipped": True, "reason": f"{_MAX_POSTS_ENV}=0"}
    conn = store._get_conn()
    if not conn:
        return {"skipped": True, "reason": "database_unavailable"}
    sent = 0
    skipped = 0
    try:
        tasks = client.get_tasks(list_id)
        for task in tasks:
            if sent >= cap:
                break
            if not _is_dispatcher_task(task):
                continue
            try:
                result = dispatch_task(task, conn, now=now)
                conn.commit()
            except Exception as e:
                try:
                    conn.rollback()
                except Exception:
                    pass
                logger.warning("dispatcher task failed: %s", e)
                skipped += 1
                continue
            if result.get("ok"):
                sent += 1
            else:
                skipped += 1
        return {"ok": True, "sent": sent, "skipped": skipped}
    finally:
        store._put_conn(conn)


def run_tick() -> dict[str, Any]:
    if not dispatcher_enabled():
        return {"skipped": True, "reason": f"{_ENABLED_ENV} off"}
    try:
        from clickup_client import ClickUpClient
        from memory.store_back import SentinelStoreBack

        client = ClickUpClient._get_global_instance()
        store = SentinelStoreBack._get_global_instance()
        client.reset_cycle_counter()
        outbound = dispatch_due_tasks(client, store)
        replies = process_replies(client, store)
        return {"ok": True, "outbound": outbound, "replies": replies}
    except Exception as e:
        logger.exception("dispatcher tick failed")
        return {"ok": False, "error": str(e)}
