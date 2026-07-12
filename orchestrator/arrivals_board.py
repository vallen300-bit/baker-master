"""ARRIVALS_BOARD_LIVE_1 — flight board state store + ARRIVALS board render.

Pilot-written lifecycle state (D-23 slice 1) + Director ARRIVALS surface (D-29).
Render path is read-only; the only write is ``upsert_board_state()`` from the
authed endpoint. Status vocabulary is Director-ratified 2026-07-08 — do not
extend without a ratified change.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import psycopg2.extras

from kbl.db import get_conn

logger = logging.getLogger(__name__)

STATUSES = [
    "CHECK-IN",
    "ON TIME",
    "HOLDING",
    "DELAYED",
    "FINAL APPROACH",
    "LANDED",
    "DIVERTED",
]

# Statuses the machine may display instead of the pilot's value when the
# arrives date has passed. A pilot can never hide a slip.
_OVERLAY_EXEMPT = {"LANDED", "DIVERTED", "DELAYED"}
_TRIGGER_SOURCE = "arrivals_board"
_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "outputs"
    / "templates"
    / "arrivals_board_template.html"
)
_PROJECT_RE = re.compile(r"^[A-Z0-9][A-Z0-9-]{0,63}$")
_ZH = ZoneInfo("Europe/Zurich")
_MONTHS = (
    "JAN",
    "FEB",
    "MAR",
    "APR",
    "MAY",
    "JUN",
    "JUL",
    "AUG",
    "SEP",
    "OCT",
    "NOV",
    "DEC",
)


def _json_param(payload: dict[str, Any]) -> psycopg2.extras.Json:
    return psycopg2.extras.Json(payload, dumps=lambda v: json.dumps(v, default=str))


def _project_code(raw: str) -> str:
    code = str(raw or "").strip().upper()
    if not _PROJECT_RE.fullmatch(code):
        raise ValueError("project_code must be 1-64 chars of A-Z, 0-9, or '-'")
    return code


def _optional_text(value: Any, *, max_len: int = 512) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > max_len:
        raise ValueError(f"text field exceeds {max_len} characters")
    return text


def _optional_cockpit_url(value: Any) -> Optional[str]:
    url = _optional_text(value, max_len=512)
    if url is None:
        return None
    if (
        not url.startswith("/")
        or url.startswith("//")
        or "\\" in url
        or any(ord(c) < 32 for c in url)
    ):
        raise ValueError("cockpit_url must be a same-origin path starting with '/'")
    return url


def _parse_date_value(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _parse_datetime_value(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime.combine(value, time.min)
    else:
        raw = str(value)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().upper()
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    return status


def upsert_board_state(project_code: str, fields: dict[str, Any], updated_by: str) -> dict[str, Any]:
    """Validated, audited upsert of one flight's board row."""
    if not isinstance(fields, dict):
        raise ValueError("payload must be an object")
    code = _project_code(project_code)
    status = _normalize_status(fields.get("status"))
    arrives_on = _parse_date_value(fields.get("arrives_on"))
    by = _optional_text(updated_by, max_len=128) or "unknown"
    params = {
        "arrives_label": _optional_text(fields.get("arrives_label"), max_len=128),
        "airline": _optional_text(fields.get("airline"), max_len=128),
        "destination": _optional_text(fields.get("destination"), max_len=128),
        "cockpit_url": _optional_cockpit_url(fields.get("cockpit_url")),
        "page_version": _optional_text(fields.get("page_version"), max_len=128),
    }
    with get_conn() as conn:
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO flight_board_state
                        (project_code, status, arrives_on, arrives_label, airline,
                         destination, cockpit_url, page_version, updated_by, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                    ON CONFLICT (project_code) DO UPDATE SET
                        status = EXCLUDED.status,
                        arrives_on = EXCLUDED.arrives_on,
                        arrives_label = COALESCE(EXCLUDED.arrives_label, flight_board_state.arrives_label),
                        airline = COALESCE(EXCLUDED.airline, flight_board_state.airline),
                        destination = COALESCE(EXCLUDED.destination, flight_board_state.destination),
                        cockpit_url = COALESCE(EXCLUDED.cockpit_url, flight_board_state.cockpit_url),
                        page_version = COALESCE(EXCLUDED.page_version, flight_board_state.page_version),
                        updated_by = EXCLUDED.updated_by,
                        updated_at = now()
                    RETURNING project_code, status, arrives_on, arrives_label, airline,
                              destination, cockpit_url, page_version, updated_by, updated_at
                    """,
                    (
                        code,
                        status,
                        arrives_on,
                        params["arrives_label"],
                        params["airline"],
                        params["destination"],
                        params["cockpit_url"],
                        params["page_version"],
                        by,
                    ),
                )
                row = dict(cur.fetchone())
                cur.execute(
                    """
                    INSERT INTO baker_actions
                        (action_type, target_task_id, payload, trigger_source, success)
                    VALUES (%s, %s, %s, %s, TRUE)
                    """,
                    (
                        "flight_board.upsert",
                        code,
                        _json_param({"state": row, "updated_by": by}),
                        _TRIGGER_SOURCE,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return row


def list_board_rows() -> list[dict[str, Any]]:
    """All active flights: registry LEFT JOIN board state. Read-only, bounded."""
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    """
                    SELECT r.project_number, r.desk_owner, r.matter_slug,
                           s.status, s.arrives_on, s.arrives_label, s.airline,
                           s.destination, s.cockpit_url, s.page_version,
                           s.updated_by, s.updated_at
                      FROM project_registry r
                      LEFT JOIN flight_board_state s ON s.project_code = r.project_number
                     WHERE r.status = 'active'
                     ORDER BY s.arrives_on ASC NULLS LAST, r.project_number
                     LIMIT 200
                    """
                )
                return [dict(x) for x in cur.fetchall()]
    except Exception:
        logger.warning("list_board_rows failed", exc_info=True)
        return []


def effective_status(row: dict[str, Any], today: Optional[date] = None) -> str:
    """Past arrives date forces DELAYED unless the flight already landed/diverted."""
    status = str(row.get("status") or "CHECK-IN").strip().upper()
    if status not in STATUSES:
        status = "CHECK-IN"
    today = today or datetime.now(timezone.utc).date()
    arrives = _parse_date_value(row.get("arrives_on"))
    if arrives and status not in _OVERLAY_EXEMPT and arrives < today:
        return "DELAYED"
    return status


def _has_state(row: dict[str, Any]) -> bool:
    return bool(row.get("status") or row.get("updated_at"))


def _display_text(value: Any, fallback: str = "—") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text.upper() if text else fallback


def _format_arrives(value: Any) -> str:
    d = _parse_date_value(value)
    if d is None:
        return "—"
    return f"{d.day} {_MONTHS[d.month - 1]}"


def _format_updated(value: Any) -> str:
    dt = _parse_datetime_value(value)
    if dt is None:
        return "—"
    local = dt.astimezone(_ZH)
    return f"{local.day} {_MONTHS[local.month - 1]} {local:%H:%M}"


def _flap(text: Any, cls: str = "", extra_class: str = "") -> str:
    class_attr = f" {html.escape(extra_class, quote=True)}" if extra_class else ""
    cls_attr = f' data-cls="{html.escape(cls, quote=True)}"' if cls else ""
    return (
        f'<div class="flap{class_attr}" data-flap="'
        f'{html.escape(str(text), quote=True)}"{cls_attr}></div>'
    )


def _onclick(url: str) -> str:
    return html.escape(f"location.href={json.dumps(url)}", quote=True)


def _default_cockpit_url(row: dict[str, Any]) -> str:
    try:
        project = _project_code(str(row.get("project_number") or ""))
    except ValueError:
        return "/cockpit"
    return f"/cockpit/{project}"


def _safe_cockpit_url(row: dict[str, Any]) -> str:
    fallback = _default_cockpit_url(row)
    try:
        return _optional_cockpit_url(row.get("cockpit_url")) or fallback
    except ValueError:
        logger.warning(
            "Ignoring invalid arrivals cockpit_url for project_code=%s",
            row.get("project_number"),
        )
        return fallback


def _is_old_landed(row: dict[str, Any], now: datetime) -> bool:
    if str(row.get("status") or "").strip().upper() != "LANDED":
        return False
    updated = _parse_datetime_value(row.get("updated_at"))
    if updated is None:
        return False
    return updated < now - timedelta(days=7)


def _row_html(row: dict[str, Any], today: date) -> str:
    has_state = _has_state(row)
    project = _display_text(row.get("project_number"))
    matter = _display_text(row.get("matter_slug"))
    desk = _display_text(row.get("desk_owner"))
    status = effective_status(row, today=today)
    status_cls = (
        "grn"
        if status == "ON TIME"
        else "red"
        if status == "DELAYED"
        else "inv"
        if status == "FINAL APPROACH"
        else ""
    )
    status_extra = "blinkgrp" if status == "FINAL APPROACH" else ""
    airline = _display_text(row.get("airline"), fallback=matter)
    destination = _display_text(row.get("destination"))
    flight_no = project if has_state else "PENDING"
    row_class = "live" if has_state else "pending"
    url = _safe_cockpit_url(row)
    click = f' onclick="{_onclick(url)}"' if url != "/cockpit" else ""
    return (
        f'      <tr class="{row_class}"{click}>\n'
        # arrives / desk / updated = tech-meta columns -> smaller 'meta' tiles so
        # they don't compete with flight name, destination and status.
        f"        <td>{_flap(_format_arrives(row.get('arrives_on')), 'meta')}</td>\n"
        f"        <td>{_flap(flight_no)}</td>\n"
        f"        <td>{_flap(airline, 'wht' if has_state else '')}</td>\n"
        f"        <td>{_flap(destination, 'wht' if has_state else '')}</td>\n"
        f"        <td>{_flap(desk, 'meta')}</td>\n"
        f"        <td>{_flap(status, status_cls, status_extra)}</td>\n"
        f"        <td>{_flap(_format_updated(row.get('updated_at')), 'meta')}</td>\n"
        "      </tr>"
    )


def _stamp(now: datetime) -> str:
    local = now.astimezone(_ZH)
    return f"BOARD V6 · AS OF {local.day} {_MONTHS[local.month - 1]} {local.year}"


def render_board_html(rows: list[dict[str, Any]], now: Optional[datetime] = None) -> str:
    """Render the Director-ratified v6 board with dynamic rows."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(_ZH).date()
    live_rows = [r for r in rows if not _is_old_landed(r, now)]
    rows_html = "\n\n".join(_row_html(r, today) for r in live_rows)
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.replace("__ROWS__", rows_html).replace("__STAMP__", _stamp(now))


def json_rows(rows: list[dict[str, Any]], now: Optional[datetime] = None) -> list[dict[str, Any]]:
    """JSON-safe rows with the same machine overlay used by the HTML board."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(_ZH).date()
    out: list[dict[str, Any]] = []
    for row in rows:
        if _is_old_landed(row, now):
            continue
        item = dict(row)
        item["effective_status"] = effective_status(row, today=today)
        out.append(item)
    return out
