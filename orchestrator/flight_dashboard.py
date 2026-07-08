"""BB_AUK_001_DASHBOARD_V1 — read-only CEO flight dashboard (v4 CEO content model).

D-24: every active flight needs a Director-visible dashboard. This is the CEO VIEW
(mockup-v4, ratified layout) — distinct from the engine-room / ops snapshot served by
`flight_snapshot.py` at `/flights/{code}`. This view lives at `/flight/{code}`.

Two source classes (content-contract-v2):
  * Machine (live query): §4 live-ticket status counts — design rule 5, ledger is the
    source for ticket counts, NEVER hand-typed. On query failure the strip renders a
    visible "ledger unavailable" state — never fabricated zeros.
  * Desk (static snapshot): decide-now, money strip, ball-in-court, top-risks,
    what-changed, communications gists — read from a committed per-flight snapshot
    JSON (orchestrator/flight_dashboards/<CODE>.json). v1 has NO live desk-write store.

Hard contract (dispatch #5330 / D-23): READ-ONLY. Zero writes to airport_tickets, zero
flight-state mutation. Every DB read wrapped so a dead ledger can't crash the page.
Honest empties (rule 6): a section with no data renders "none this week", never invents.
Staleness (rule 4): a desk card older than 48h → amber, 96h → red.
"""
from __future__ import annotations

import html
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg2.extras

from kbl.db import get_conn

logger = logging.getLogger(__name__)

# Where committed per-flight desk snapshots live (read-only static store, v1).
_SNAPSHOT_DIR = Path(__file__).resolve().parent / "flight_dashboards"

# Bounded read (repo hard rule: never an unbounded query). The aggregate returns at
# most (#statuses × #urgency values) rows — a small cap is ample.
_COUNT_CAP = 200

# Staleness thresholds (hours) — design rule 4.
_STALE_AMBER_H = 48
_STALE_RED_H = 96

# Honest footer — describes the CONTRACT, does not assert per-row conformance (G0 fix 2:
# v4 falsely claimed "every row has owner + date + receipt" while most rows had none).
FOOTER_TEXT = (
    "CEO VIEW · FLIGHT_DASHBOARD_PACKET v2 · rows carry owner, date and receipt where "
    "recorded; desk cards turn amber at 48h stale, red at 96h; §4 ticket counts are "
    "machine-queried from the ledger; empty sections say so honestly; ops detail lives "
    "in the engine room."
)


def _esc(value: Any) -> str:
    """HTML-escape any value to a string (XSS-safe render of desk-authored content)."""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# §4 machine section — live ticket counts (rule 5: ledger-sourced, never typed)
# --------------------------------------------------------------------------

def _aggregate_counts(rows: list[dict]) -> dict:
    """Pure aggregation of GROUP BY (status, urgency_hint) rows into the four §4
    headline counts. DB-free so the machine-counting logic is unit-testable.

    Each input row: {"status": str, "urgency_hint": str|None, "n": int}.
    """
    checked_in = awaiting = rejected = urgent = total = 0
    for r in rows:
        status = (r.get("status") or "").lower()
        urgency = (r.get("urgency_hint") or "").lower()
        n = int(r.get("n") or 0)
        total += n
        if status == "checked_in":
            checked_in += n
        elif status in ("candidate", "sent"):
            awaiting += n
        elif status == "rejected":
            rejected += n
        # "urgent" is an urgency dimension across live (non-terminal) tickets.
        if urgency in ("urgent", "high") and status not in ("rejected", "closed", "failed"):
            urgent += n
    return {
        "checked_in": checked_in,
        "urgent": urgent,
        "awaiting": awaiting,
        "rejected": rejected,
        "total": total,
    }


def _clean_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    try:
        return [str(v).strip() for v in values if str(v or "").strip()]
    except TypeError:
        return []


def count_flight_tickets(
    suspected_flight: Optional[str],
    *,
    legacy_suspected_flights: Optional[list[str]] = None,
    legacy_matter_slugs: Optional[list[str]] = None,
) -> dict:
    """Machine §4 read: aggregate airport_tickets counts for one flight.

    Returns {"available": True, checked_in, urgent, awaiting, rejected, total} on a clean
    read (even when the result is all-zero), or {"available": False} on ANY failure —
    the caller renders "ledger unavailable" rather than fabricating zeros (fault-tolerant
    read; rule 5). This function NEVER issues INSERT/UPDATE/DELETE.
    """
    primary_flights = _clean_list(suspected_flight)
    legacy_flights = _clean_list(legacy_suspected_flights)
    legacy_matters = _clean_list(legacy_matter_slugs)
    if not primary_flights and not (legacy_flights and legacy_matters):
        return {"available": True, "checked_in": 0, "urgent": 0, "awaiting": 0,
                "rejected": 0, "total": 0}
    sql = (
        "SELECT status, urgency_hint, COUNT(*) AS n "
        "FROM airport_tickets "
        "WHERE suspected_flight = ANY(%s) "
        "   OR (suspected_flight = ANY(%s) AND suspected_matter_slug = ANY(%s)) "
        "GROUP BY status, urgency_hint LIMIT %s"
    )
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    sql,
                    (
                        primary_flights or ["__baker_no_primary_flight__"],
                        legacy_flights or ["__baker_no_legacy_flight__"],
                        legacy_matters or ["__baker_no_legacy_matter__"],
                        _COUNT_CAP,
                    ),
                )
                rows = [dict(r) for r in cur.fetchall()]
        agg = _aggregate_counts(rows)
        agg["available"] = True
        return agg
    except Exception as e:  # fault-tolerant: signal unavailable, never fabricate zeros
        logger.warning(
            "count_flight_tickets read failed for %s/%s: %s",
            primary_flights,
            legacy_flights,
            e,
        )
        return {"available": False}


# --------------------------------------------------------------------------
# AO_FLIGHT_RELATIONSHIP_1 — honest machine comms-gap element (Fix 1)
# The cockpit AO tab promised "days since last direct contact" and lied: it
# defaulted GREEN on a silent double query failure (wrong WA chat key +
# non-existent sent_at column). This element replaces it with verified wiring
# and the fail-loud rule: unknown -> neutral, NEVER green by default.
# --------------------------------------------------------------------------

def _gap_tone(days: Optional[int]) -> str:
    """Pure: gap days -> tone class. None = unknown -> neutral (never green)."""
    if days is None:
        return "none"
    if days > 14:
        return "red"
    if days > 10:
        return "amber"
    return "green"


def last_direct_contact(comms_contact: Optional[dict]) -> Optional[dict]:
    """Ledger query: most recent WA message in the configured chat OR sent email
    matching the configured patterns. Returns {'at': datetime, 'channel': str} or
    None on no-data/failure (caller renders the honest no-data line, never green).

    Uses the module's own DB idiom (kbl.db.get_conn, as count_flight_tickets).
    READ-ONLY: SELECT MAX(...) only, no writes (D-23)."""
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                best = None
                wa_chat = (comms_contact or {}).get("wa_chat_id")
                if wa_chat:
                    cur.execute(
                        "SELECT MAX(timestamp) FROM whatsapp_messages WHERE chat_id = %s",
                        (wa_chat,),
                    )
                    r = cur.fetchone()
                    if r and r[0]:
                        best = {"at": r[0], "channel": "WhatsApp"}
                pats = (comms_contact or {}).get("email_patterns") or []
                if pats:
                    cur.execute(
                        "SELECT MAX(created_at) FROM sent_emails WHERE to_address ILIKE ANY(%s)",
                        (list(pats),),
                    )
                    r = cur.fetchone()
                    if r and r[0] and (best is None or r[0] > best["at"]):
                        best = {"at": r[0], "channel": "email"}
                return best
    except Exception:
        logger.exception("last_direct_contact failed")
        return None


def _contact_gap_days(at: datetime, now: Optional[datetime] = None) -> int:
    """Whole-days gap between a contact timestamp and now. Guards naive datetimes
    the same way _apply_staleness / staleness_flag do."""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return max(0, (_now(now) - at).days)


# --------------------------------------------------------------------------
# Desk snapshot (static, read-only) + staleness
# --------------------------------------------------------------------------

def load_snapshot(project_code: str) -> Optional[dict]:
    """Read the committed per-flight desk snapshot JSON. Returns None for an unknown
    code (caller ⇒ 404) or an unreadable/invalid file. Pure read — no writes."""
    if not project_code:
        return None
    safe = project_code.strip().upper()
    # Guard against path traversal — only a bare code maps to a file.
    if not safe.replace("-", "").replace("_", "").isalnum():
        return None
    path = _SNAPSHOT_DIR / f"{safe}.json"
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("flight_dashboard snapshot unreadable for %s: %s", safe, e)
        return None


def staleness_flag(updated_at: Any, now: Optional[datetime] = None) -> Optional[str]:
    """Return 'red' (>96h), 'amber' (>48h), or None (fresh / unparseable).
    Design rule 4. Unparseable stamps degrade to None (no false staleness alarm)."""
    if not updated_at:
        return None
    try:
        stamp = updated_at
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    hours = (_now(now) - stamp).total_seconds() / 3600.0
    if hours > _STALE_RED_H:
        return "red"
    if hours > _STALE_AMBER_H:
        return "amber"
    return None


def _days_until(deadline_date: Any, now: Optional[datetime] = None) -> Optional[int]:
    if not deadline_date:
        return None
    try:
        d = deadline_date
        if isinstance(d, str):
            d = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
        elif d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return (d.date() - _now(now).date()).days


# --------------------------------------------------------------------------
# Assemble
# --------------------------------------------------------------------------

def build_flight_dashboard(project_code: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Combine the desk snapshot (static) with the live §4 ledger counts (machine) and
    computed staleness flags. Returns None for an unknown flight (⇒ 404)."""
    snap = load_snapshot(project_code)
    if snap is None:
        return None
    tickets = count_flight_tickets(
        snap.get("suspected_flight"),
        legacy_suspected_flights=snap.get("legacy_suspected_flights"),
        legacy_matter_slugs=snap.get("legacy_matter_slugs"),
    )
    header = snap.get("header", {})
    data = {
        "project_code": snap.get("project_code", project_code),
        "header": header,
        "days_until": _days_until(header.get("deadline_date"), now),
        "decide_now": snap.get("decide_now", {}),
        "money_kpis": snap.get("money_kpis", {}),
        "ball_in_court": snap.get("ball_in_court", {}),
        "top_risks": snap.get("top_risks", {}),
        "what_changed": snap.get("what_changed", {}),
        "communications": snap.get("communications", {}),
        # AO_FLIGHT_RELATIONSHIP_1 Fix 2 — optional desk-curated relationship card.
        # Absent/empty in the snapshot (BB-AUK-001 and every other flight) -> renderer
        # omits the card entirely -> zero behavior change.
        "relationship": snap.get("relationship", {}),
        "tickets": tickets,
        "assembled_at": _now(now).isoformat(),
        # Per-card staleness (design rule 4).
        "stale": {
            "decide_now": staleness_flag(snap.get("decide_now", {}).get("updated_at"), now),
            "ball_in_court": staleness_flag(snap.get("ball_in_court", {}).get("updated_at"), now),
            "top_risks": staleness_flag(snap.get("top_risks", {}).get("updated_at"), now),
            "what_changed": staleness_flag(snap.get("what_changed", {}).get("updated_at"), now),
            "communications": staleness_flag(snap.get("communications", {}).get("updated_at"), now),
            "relationship": staleness_flag(snap.get("relationship", {}).get("updated_at"), now),
        },
    }
    # AO_FLIGHT_RELATIONSHIP_1 Fix 1 — machine comms-gap element. Only computed when the
    # snapshot opts in with a `comms_contact` block; absent key (BB-AUK-001) -> no
    # last_contact -> renderer emits no line. Fail-loud: a query miss/failure yields
    # {"days": None} which renders "no data", never a default-green status.
    comms_contact = snap.get("comms_contact")
    if comms_contact:
        hit = last_direct_contact(comms_contact)
        if hit:
            days = _contact_gap_days(hit["at"], now)
            data["last_contact"] = {
                "days": days,
                "channel": hit["channel"],
                "date": str(hit["at"])[:10],
                "tone": _gap_tone(days),
                "label": comms_contact.get("label", "DIRECT"),
            }
        else:
            data["last_contact"] = {
                "days": None,
                "tone": _gap_tone(None),
                "label": comms_contact.get("label", "DIRECT"),
            }
    return data


# --------------------------------------------------------------------------
# Render (server-side HTML, v4 CEO layout; all desk values escaped)
# --------------------------------------------------------------------------

_CSS = """
:root{--bg:#0b1220;--panel:#0f1830;--card:#111c36;--line:#1d2b4d;--txt:#e8edf7;
--dim:#8494b3;--mono:'SF Mono',ui-monospace,Menlo,monospace;--amber:#f5b942;
--red:#f0616d;--green:#4fc38a;--blue:#5c9bff;}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:15px/1.55 -apple-system,'Helvetica Neue',sans-serif;padding:0}
.banner{background:#5a4a2a;color:#fff;font:12px var(--mono);padding:8px 34px;letter-spacing:.04em}
main{padding:26px 34px 40px;max-width:1180px;margin:0 auto}
.topbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:6px}
.topbar h2{font-size:22px}
.kicker{font:11px var(--mono);letter-spacing:.14em;color:var(--dim)}
.code{font:12px var(--mono);color:var(--blue)}
.chip{font:11px var(--mono);padding:3px 9px;border-radius:20px}
.atrisk{background:#3a2a12;color:var(--amber);border:1px solid #6b4c1b}
.ontrack{background:#122a1d;color:var(--green);border:1px solid #24503a}
.blocked{background:#3a1518;color:var(--red);border:1px solid #6b2b2f}
.countdown{font:12.5px var(--mono);color:var(--amber)}
.serves{font:12.5px var(--mono);color:var(--green)}
.stamp{font:11.5px var(--mono);color:var(--dim);margin-bottom:22px}
.soon{font:10px var(--mono);color:var(--amber);margin-left:6px}
section{margin-bottom:18px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px}
.card.amber{border-color:#6b4c1b}.card.red{border-color:#6b2b2f}
.card h3{font:12px var(--mono);letter-spacing:.12em;color:var(--dim);margin-bottom:12px}
.cardstamp{font:10.5px var(--mono);color:var(--dim);margin-top:12px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:980px){.cols{grid-template-columns:1fr}}
.decide{border-left:3px solid var(--amber)}
.decq{font-size:17px;font-weight:600;margin-bottom:12px}
.opt{display:flex;gap:12px;padding:9px 12px;border-radius:8px;margin-bottom:6px;font-size:14px}
.opt.rec{background:#182a1f;border:1px solid #24503a}
.opt .tag{font:11px var(--mono);color:var(--green);white-space:nowrap;padding-top:2px;min-width:84px}
.opt:not(.rec) .tag{color:var(--dim)}
.decmeta{font:12px var(--mono);color:var(--amber);margin-top:8px}
.kpis{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi .n{font:600 22px var(--mono)}.kpi .l{font:10.5px var(--mono);color:var(--dim);letter-spacing:.08em;margin-top:3px}
.kpi .n.red{color:var(--red)}.kpi .n.green{color:var(--green)}
.kpi .r{font:9.5px var(--mono);color:var(--dim);margin-top:6px}
@media(max-width:980px){.kpis{grid-template-columns:repeat(2,1fr)}}
.strip{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.strip .kpi .n{font:600 20px var(--mono)}
.unavail{background:#3a1518;color:var(--red);font:12px var(--mono);padding:12px 16px;border:1px solid #6b2b2f;border-radius:12px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{font:10.5px var(--mono);color:var(--dim);text-align:left;letter-spacing:.08em;padding:0 10px 8px 0}
td{padding:7px 10px 7px 0;border-top:1px solid var(--line);vertical-align:top}
.mono{font:12px var(--mono)}
.st{font:11px var(--mono);padding:2px 8px;border-radius:20px;white-space:nowrap}
.wait{background:#2a2410;color:var(--amber)}.over{background:#3a1518;color:var(--red)}
.done{background:#122a1d;color:var(--green)}.urgent{background:#3a1518;color:var(--red)}
.rcpt{font:10.5px var(--mono);color:var(--dim)}
.nodata{font:13px italic;color:var(--dim);padding:4px 0}
footer{font:11px var(--mono);color:var(--dim);margin-top:26px;line-height:1.8}
"""

_PAGE = (
    "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
    "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
    "<title>__TITLE__</title><style>__CSS__</style></head><body>"
    "<div class=\"banner\">READ-ONLY snapshot · no flight-state writes (D-23) · "
    "assembled __ASSEMBLED__</div><main>__BODY__</main></body></html>"
)

_STATE_CLASS = {"AT-RISK": "atrisk", "ON-TRACK": "ontrack", "BLOCKED": "blocked"}
_ROW_STATE_CLASS = {"WAITING": "wait", "OVERDUE": "over", "IN REVIEW": "done", "DONE": "done"}


def _row_state_class(state: str) -> str:
    up = (state or "").upper()
    for key, cls in _ROW_STATE_CLASS.items():
        if up.startswith(key):
            return cls
    return "wait"


def _nodata(msg: str = "none this week") -> str:
    return f'<div class="nodata">{_esc(msg)}</div>'


def _header_html(data: dict) -> str:
    h = data.get("header", {})
    state = h.get("state", "")
    scls = _STATE_CLASS.get(str(state).upper(), "atrisk")
    days = data.get("days_until")
    if days is None:
        countdown = "deadline: proof-pending"
    elif days < 0:
        countdown = f"{h.get('deadline_label', 'Deadline')} overdue by {abs(days)} days"
    else:
        countdown = f"{h.get('deadline_label', 'Deadline')} in {days} days"
    serves = h.get("serves")
    serves_html = f'<span class="serves">serves: {_esc(serves)}</span>' if serves else ""
    return (
        f'<div class="kicker">{_esc(h.get("kicker", ""))}</div>'
        f'<div class="topbar"><h2>{_esc(h.get("flight_name", data.get("project_code")))}</h2>'
        f'<span class="code">{_esc(data.get("project_code"))} · CEO view</span>'
        f'<span class="chip {scls}">{_esc(state)}</span>'
        f'<span class="countdown">⏱ {_esc(countdown)}</span>{serves_html}'
        f'<a href="/flights/{_esc(data.get("project_code"))}" style="margin-left:auto;color:var(--blue);font:12px var(--mono);text-decoration:none">⚙ engine room ›</a>'
        "</div>"
        f'<div class="stamp">Goal: {_esc(h.get("goal", ""))} · Updated <b>'
        f'{_esc(str(h.get("updated_at", ""))[:10])}</b> by {_esc(h.get("updated_by", ""))}</div>'
    )


def _decide_html(data: dict) -> str:
    block = data.get("decide_now", {})
    decisions = block.get("decisions", [])
    stale = data.get("stale", {}).get("decide_now")
    cls = f"card decide {stale}" if stale else "card decide"
    if not decisions:
        return f'<section><div class="{cls}"><h3>1 · DECIDE NOW</h3>{_nodata("no open decisions")}</div></section>'
    out = []
    for d in decisions:
        opts = "".join(
            f'<div class="opt{" rec" if o.get("recommended") else ""}">'
            f'<span class="tag">{_esc(o.get("tag"))}{" ✓" if o.get("recommended") else ""}</span>'
            f'<span>{_esc(o.get("text"))}</span></div>'
            for o in d.get("options", [])
        )
        receipts = " ".join(_esc(r) for r in d.get("receipts", []))
        meta = f'TRIGGER: {_esc(d.get("trigger", ""))} · decide by {_esc(d.get("decide_by", ""))} · receipts: {receipts}'
        out.append(
            f'<h3>1 · DECIDE NOW — {_esc(d.get("status", "OPEN"))}, DECIDE BY {_esc(d.get("decide_by", ""))}</h3>'
            f'<div class="decq">{_esc(d.get("question"))}</div>{opts}'
            f'<div class="decmeta">{meta}</div>'
        )
    return f'<section><div class="{cls}">{"".join(out)}</div></section>'


def _money_html(data: dict) -> str:
    items = data.get("money_kpis", {}).get("items", [])
    if not items:
        return f'<section><div class="card"><h3>2 · MONEY AT STAKE</h3>{_nodata()}</div></section>'
    kpis = "".join(
        f'<div class="kpi"><div class="n {_esc(i.get("tone")) if i.get("tone") in ("red", "green") else ""}">'
        f'{_esc(i.get("n"))}</div><div class="l">{_esc(i.get("label"))}</div>'
        f'<div class="r">{_esc(i.get("receipt", ""))}</div></div>'
        for i in items
    )
    return f'<section><div class="kpis">{kpis}</div></section>'


def _contact_line_html(data: dict) -> str:
    """AO_FLIGHT_RELATIONSHIP_1 Fix 1 — one machine line for the §4 card:
    'LAST DIRECT <LABEL> CONTACT — <n> days (<channel>, <date>)'.
    Rendered only when the snapshot opted in (data['last_contact'] present).
    Unknown/failure -> neutral 'no data' line, NEVER green by default."""
    lc = data.get("last_contact")
    if not lc:
        return ""
    label = _esc(lc.get("label", "DIRECT"))
    _TONE_COLOR = {"green": "var(--green)", "amber": "var(--amber)", "red": "var(--red)"}
    if lc.get("days") is None:
        return (
            '<div class="cardstamp"><b style="color:var(--dim)">'
            f'LAST DIRECT {label} CONTACT — no data (wiring check needed)</b></div>'
        )
    color = _TONE_COLOR.get(lc.get("tone"), "var(--dim)")
    return (
        f'<div class="cardstamp"><b style="color:{color}">'
        f'LAST DIRECT {label} CONTACT — {int(lc["days"])} days</b> '
        f'({_esc(lc.get("channel"))}, {_esc(lc.get("date"))})</div>'
    )


def _tickets_html(data: dict) -> str:
    """§4 LIVE SIGNAL TICKETS — restored (G0 fix 1). Machine-queried; on ledger failure
    renders a visible unavailable state, never fabricated zeros. Carries the optional
    machine comms-gap line (AO_FLIGHT_RELATIONSHIP_1 Fix 1) when configured."""
    contact = _contact_line_html(data)
    t = data.get("tickets", {})
    if not t.get("available"):
        return (
            '<section><div class="unavail">4 · LIVE SIGNAL TICKETS — ledger unavailable '
            '(query failed; counts not shown rather than fabricated). Machine-only per '
            f'design rule 5.</div>{contact}</section>'
        )
    cells = [
        ("checked_in", "CHECKED-IN", ""),
        ("urgent", "URGENT", "red"),
        ("awaiting", "AWAITING CHECK-IN", ""),
        ("rejected", "REJECTED", ""),
    ]
    kpis = "".join(
        f'<div class="kpi"><div class="n {tone}">{int(t.get(key, 0))}</div>'
        f'<div class="l">{label}</div></div>'
        for key, label, tone in cells
    )
    # Honest boarding/outbound counter — step-2 not built (rule 6).
    kpis += ('<div class="kpi"><div class="n">0</div>'
             '<div class="l">BOARDING/OUTBOUND — NOT BUILT (STEP-2)</div></div>')
    return (
        '<section><div class="card"><h3>4 · LIVE SIGNAL TICKETS — MACHINE-QUERIED</h3>'
        f'<div class="strip">{kpis}</div>'
        f'<div class="cardstamp">counts from airport_tickets ledger · {int(t.get("total", 0))} total rows · never hand-typed</div>'
        f'{contact}'
        '</div></section>'
    )


def _table_card(title: str, headers: list[str], rows_html: str, stamp: str,
                stale: Optional[str], section_id: str = "") -> str:
    cls = f"card {stale}" if stale else "card"
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    if not rows_html:
        rows_html = f'<tr><td colspan="{len(headers)}">{_nodata()}</td></tr>'
    stale_note = f' · <b style="color:var(--amber)">STALE ({stale})</b>' if stale else ""
    return (
        f'<div class="{cls}"><h3>{_esc(title)}</h3>'
        f'<table><tr>{head}</tr>{rows_html}</table>'
        f'<div class="cardstamp">{_esc(stamp)}{stale_note}</div></div>'
    )


def _ball_html(data: dict) -> str:
    block = data.get("ball_in_court", {})
    rows = "".join(
        f'<tr><td>{_esc(r.get("waiting_on"))}</td><td>{_esc(r.get("for_what"))}</td>'
        f'<td class="mono">{_esc(r.get("since_due"))}</td>'
        f'<td><span class="st {_row_state_class(r.get("state"))}">{_esc(r.get("state"))}</span></td>'
        f'<td class="rcpt">{_esc(r.get("receipt", ""))}</td></tr>'
        for r in block.get("rows", [])
    )
    card = _table_card(
        "3 · BALL IN WHOSE COURT", ["WAITING ON", "FOR WHAT", "SINCE / DUE", "STATE", "RECEIPT"],
        rows, f'desk-written · updated {str(block.get("updated_at", ""))[:10]}',
        data.get("stale", {}).get("ball_in_court"),
    )
    return f'<section>{card}</section>'


def _risks_changed_html(data: dict) -> str:
    risks = data.get("top_risks", {})
    rrows = "".join(
        f'<tr><td>{_esc(r.get("risk"))}</td><td>{_esc(r.get("owner"))}</td>'
        f'<td><span class="st {"over" if str(r.get("move","")).startswith("chase") else "wait"}">{_esc(r.get("move"))}</span></td></tr>'
        for r in risks.get("rows", [])
    )
    rcard = _table_card(
        "4b · TOP RISKS", ["RISK", "OWNER", "MOVE"], rrows,
        f'desk-written · updated {str(risks.get("updated_at", ""))[:10]}',
        data.get("stale", {}).get("top_risks"),
    )
    changed = data.get("what_changed", {})
    crows = "".join(
        f'<tr><td class="mono">{_esc(r.get("date"))}</td><td>{_esc(r.get("event"))}</td>'
        f'<td class="rcpt">{_esc(r.get("receipt", ""))}</td></tr>'
        for r in changed.get("rows", [])
    )
    ccard = _table_card(
        "5 · WHAT CHANGED — LAST 5", ["WHEN", "EVENT", "RECEIPT"], crows,
        f'machine + desk · updated {str(changed.get("updated_at", ""))[:10]}',
        data.get("stale", {}).get("what_changed"),
    )
    return f'<section><div class="cols">{rcard}{ccard}</div></section>'


def _relationship_html(data: dict) -> str:
    """AO_FLIGHT_RELATIONSHIP_1 Fix 2 — optional desk-curated 'RELATIONSHIP —
    COUNTERPARTY READ' card. Rendered between risks/changed and communications.
    Absent/empty section (no read + no red_flags + no orbit) -> card omitted
    entirely, so BB-AUK-001 and every flight without the key are byte-identical.
    All desk values escaped; machine renders, never generates."""
    block = data.get("relationship", {}) or {}
    read = block.get("read", []) or []
    red_flags = block.get("red_flags", []) or []
    orbit = block.get("orbit", []) or []
    if not read and not red_flags and not orbit:
        return ""
    parts = []
    if read:
        items = "".join(
            f'<tr><td>{_esc(r.get("point"))}</td>'
            f'<td class="rcpt">{_esc(r.get("receipt", ""))}</td></tr>'
            for r in read
        )
        parts.append(
            '<table><tr><th>READ</th><th>RECEIPT</th></tr>' + items + '</table>'
        )
    if red_flags:
        items = "".join(
            f'<tr><td><span class="st over">{_esc(r.get("flag"))}</span></td>'
            f'<td class="rcpt">{_esc(r.get("receipt", ""))}</td></tr>'
            for r in red_flags
        )
        parts.append(
            '<table style="margin-top:12px"><tr><th>RED FLAG</th><th>RECEIPT</th></tr>'
            + items + '</table>'
        )
    if orbit:
        items = "".join(
            f'<tr><td>{_esc(o.get("name"))}</td><td>{_esc(o.get("role"))}</td>'
            f'<td>{_esc(o.get("note", ""))}</td></tr>'
            for o in orbit
        )
        parts.append(
            '<table style="margin-top:12px"><tr><th>ORBIT</th><th>ROLE</th><th>NOTE</th></tr>'
            + items + '</table>'
        )
    stale = data.get("stale", {}).get("relationship")
    cls = f"card {stale}" if stale else "card"
    stale_note = f' · <b style="color:var(--amber)">STALE ({stale})</b>' if stale else ""
    stamp = f'desk · updated {str(block.get("updated_at", ""))[:10]}'
    return (
        f'<section><div class="{cls}"><h3>RELATIONSHIP — COUNTERPARTY READ</h3>'
        f'{"".join(parts)}'
        f'<div class="cardstamp">{_esc(stamp)}{stale_note}</div></div></section>'
    )


def _comms_html(data: dict) -> str:
    block = data.get("communications", {})
    humans = block.get("humans", [])

    def _urgent_cell(h: dict) -> str:
        u = int(h.get("urgent", 0) or 0)
        return f'<span class="st urgent">{u}</span>' if u else "—"

    rows = "".join(
        f'<tr><td>{_esc(h.get("name"))}</td><td>{_esc(h.get("role"))}</td>'
        f'<td>{_urgent_cell(h)}</td>'
        f'<td>{_esc(h.get("gist"))}</td><td class="mono">{_esc(h.get("last"))}</td></tr>'
        for h in humans
    )
    research = block.get("research_received", [])
    research_note = "research received this week: none filed (honest empty)" if not research \
        else f"research received: {len(research)} item(s)"
    basis = block.get("counts_basis", "")
    card = _table_card(
        "6 · COMMUNICATIONS RECEIVED — URGENT FIRST",
        ["FROM", "ROLE", "URGENT", "LATEST GIST", "LAST"], rows,
        f'{basis} · {research_note}', data.get("stale", {}).get("communications"),
    )
    return f'<section>{card}</section>'


def render_dashboard_html(data: dict) -> str:
    """Render the full CEO view. All desk-authored values are HTML-escaped."""
    body = (
        _header_html(data)
        + _decide_html(data)
        + _money_html(data)
        + _tickets_html(data)
        + _ball_html(data)
        + _risks_changed_html(data)
        + _relationship_html(data)
        + _comms_html(data)
        + f"<footer><b>{_esc(FOOTER_TEXT)}</b></footer>"
    )
    title = f'{data.get("project_code")} · Flight Dashboard · CEO view'
    return (
        _PAGE.replace("__TITLE__", _esc(title))
        .replace("__CSS__", _CSS)
        .replace("__ASSEMBLED__", _esc(data.get("assembled_at", "")))
        .replace("__BODY__", body)
    )
