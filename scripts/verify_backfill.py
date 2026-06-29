#!/usr/bin/env python3
"""BACKFILL_VERIFY_1: independent verification harness for the EMAIL_HISTORY_BACKFILL arc.

Read-only everywhere: IMAP folders opened with EXAMINE (readonly), Graph reads via
GraphClient.get, DB session forced read-only (SET default_transaction_read_only=on).
The ONLY write this script can perform is the optional --post bus verdict (shells out
to scripts/bus_post.py, recipients lead,deputy per post-deploy-ac-bus-gate SKILL).

Independence rule (brief, locked): this harness shares NO code with the b1/b2
backfill scripts. It compares mailbox-side truth (IMAP EXAMINE counts, Graph
totalItemCount) against store-side truth (email_messages / email_attachments)
and deep-checks random samples.

Per-folder caveat (surfaced, not hidden): email_messages has no folder column
(store_back.py bootstrap DDL), so the 98% tolerance is applied per SOURCE
(store total vs mailbox all-folder total). Per-folder mailbox counts are still
listed explicitly in the output so lead can attribute any gap to a folder.

Usage:
    python scripts/verify_backfill.py                  # both email sources, print verdict
    python scripts/verify_backfill.py --source bluewin # one source
    python scripts/verify_backfill.py --post           # also bus-post verdict to lead,deputy
    python scripts/verify_backfill.py --seed myseed    # reproducible spot-check sample

INGESTION_COMPLETENESS_P0_MEASURE_1 — baseline mode (additive; email verdict
path above is unchanged). Reuses the parametric core (compare_counts /
deterministic_order_key) to measure completeness + per-source lag across all 4
ingest sources (bluewin, graph, plaud, whatsapp). READ-ONLY: no fix, no
backfill, no migration, no deploy. The only write is the optional --post-baseline
bus report to lead.

    python scripts/verify_backfill.py --baseline                 # all 4 sources
    python scripts/verify_backfill.py --baseline-source plaud    # one source
    python scripts/verify_backfill.py --baseline --post-baseline # report -> lead bus
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TOLERANCE = 0.98          # store >= 98% of mailbox count (brief, locked)
MSG_SAMPLE_N = 10         # random historical messages per source (brief, locked)
ATT_SAMPLE_N = 5          # random attachments per source (brief, locked)
DEFAULT_SEED = "backfill-verify-1"
SOURCES = ("bluewin", "graph")

# Lead review (bus #2756): tolerance runs against an ALLOWLISTED folder subset —
# b1/b2 lanes cover INBOX + sent only; all-folder totals would false-FAIL on
# Drafts/Spam/archive noise. All-folder numbers stay printed as info lines.
DEFAULT_GRAPH_FOLDERS = ("Inbox", "SentItems")   # matched space/case-insensitively
SENT_NAME_CANDIDATES = ("sent", "sentitems", "sentmessages",
                        "inbox.sent", "inbox.sentitems", "inbox.sentmessages")

BLUEWIN_IMAP_HOST = os.getenv("BLUEWIN_IMAP_HOST", "imaps.bluewin.ch")

# --------------------------------------------------------------------------
# INGESTION_COMPLETENESS_P0_MEASURE_1 — baseline across all 4 ingest sources
# (additive; the email verdict path above is unchanged). Plaud + WhatsApp
# reuse the parametric core (compare_counts / deterministic_order_key); a
# per-source lag metric is added for all four. READ-ONLY everywhere.
# --------------------------------------------------------------------------

# The full source set the baseline measures. NOT folded into SOURCES (which
# drives the email-only verdict path); a non-email source there would be fed to
# the IMAP/Graph collectors and break. Each baseline source routes by kind.
BASELINE_SOURCES = ("bluewin", "graph", "plaud", "whatsapp")
SOURCE_KIND = {"bluewin": "email", "graph": "email",
               "plaud": "plaud", "whatsapp": "whatsapp"}

# Store-side table + timestamp columns per source (grounded in store_back.py
# bootstrap DDL: email_messages:1715, meeting_transcripts:1491, whatsapp_messages:1790).
STORE_TABLES = {
    "bluewin":  {"table": "email_messages",     "content_ts": "received_date", "ingest_ts": "ingested_at", "source_col": "source"},
    "graph":    {"table": "email_messages",     "content_ts": "received_date", "ingest_ts": "ingested_at", "source_col": "source"},
    "plaud":    {"table": "meeting_transcripts", "content_ts": "meeting_date",  "ingest_ts": "ingested_at", "source_col": "source"},
    # whatsapp_messages has NO source column (flagged, not migrated — see ship report).
    "whatsapp": {"table": "whatsapp_messages",  "content_ts": "timestamp",     "ingest_ts": "ingested_at", "source_col": None},
}

# Fallback poll intervals (seconds) if config.triggers is unreadable at RUN time.
# Live values are read from config.triggers.* in _poll_intervals(). whatsapp is
# webhook-driven (WAHA push) — no poll interval, so the Nirodha "lag < poll
# interval" clause is N/A for it (reported as webhook latency, not poll lag).
FALLBACK_POLL_INTERVALS = {"bluewin": 300, "graph": 300, "plaud": 900, "whatsapp": None}

# WhatsApp truth is a SUM over chats (WAHA exposes no aggregate count). Both
# bounds are parametric + surfaced: the WAHA-side count is a lower bound capped
# by per-chat fetch depth, over a NoWeb in-memory window. Forward-from-enrollment
# only; all-time completeness is OUT OF SCOPE (source-limited, see brief).
DEFAULT_WA_CHAT_LIMIT = 500    # chats to iterate
DEFAULT_WA_MSG_LIMIT = 1000    # messages fetched per chat (bounds the per-chat count)

PLAUD_SAMPLE_N = 10            # random recordings checked present + body non-empty
WA_SAMPLE_N = 10              # random stored WA rows checked for body + chat_id


# --------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_verify_backfill.py)
# --------------------------------------------------------------------------

def _norm_folder(name: str) -> str:
    """Space/case-insensitive folder matching: 'SentItems' == 'Sent Items'."""
    return name.replace(" ", "").lower()


def pick_imap_allowlist(folder_counts: dict, flags_map: dict) -> list:
    """Default IMAP allowlist: INBOX + detected sent folder (lead, bus #2756).

    Sent detection: SPECIAL-USE \\Sent flag first, common-name fallback second.
    If no sent folder is detectable, INBOX alone — visible in the verdict's
    allowlist line, never silent."""
    allow = [f for f in folder_counts if f.upper() == "INBOX"] or ["INBOX"]
    for name in folder_counts:
        if "\\sent" in (flags_map.get(name) or "").lower():
            allow.append(name)
            return allow
    for name in folder_counts:
        if _norm_folder(name) in SENT_NAME_CANDIDATES:
            allow.append(name)
            return allow
    return allow


def compare_counts(folder_counts: dict, store_count: int,
                   tolerance: float = TOLERANCE, allowlist: list | None = None) -> dict:
    """Compare mailbox-side per-folder counts vs store-side total for one source.

    Tolerance runs against the ALLOWLISTED folders' total (all folders when
    allowlist is None); every folder count is still returned for info printing.
    Returns explicit numbers (AC1). Zero-mailbox is a FAIL (a backfill that
    found nothing to verify is not a pass), as is an allowlist entry that
    matches no mailbox folder (can't verify what we can't count)."""
    if allowlist:
        norm_map = {_norm_folder(k): k for k in folder_counts}
        counted, missing = {}, []
        for entry in allowlist:
            real = norm_map.get(_norm_folder(entry))
            if real is None:
                missing.append(entry)
            else:
                counted[real] = folder_counts[real]
    else:
        counted, missing = dict(folder_counts), []
    mailbox_total = sum(counted.values())
    ratio = (store_count / mailbox_total) if mailbox_total else 0.0
    return {
        "folders": dict(folder_counts),
        "counted_folders": counted,
        "allowlist": list(allowlist) if allowlist else None,
        "allowlist_missing": missing,
        "mailbox_total": mailbox_total,
        "store_count": store_count,
        "ratio": round(ratio, 4),
        "tolerance": tolerance,
        "ok": (mailbox_total > 0 and not missing
               and store_count >= mailbox_total * tolerance),
    }


def deterministic_order_key(identifier: str, seed: str) -> str:
    """md5(identifier || seed) — same ordering the SQL sampler uses, so a sample
    is reproducible from (seed, id set) alone (AC2)."""
    return hashlib.md5(f"{identifier}{seed}".encode()).hexdigest()


def evaluate_message_checks(rows: list) -> dict:
    """Judge message spot-check rows. Each row: dict with message_id,
    body_len (int), searchable (bool|None — None = search check skipped, reason given).

    Failures are listed loud, one line per failed id (AC4)."""
    passes, failures, notes = [], [], []
    for r in rows:
        mid = r["message_id"]
        if r.get("body_len", 0) <= 0:
            failures.append(f"{mid}: empty body")
            continue
        if r.get("searchable") is False:
            failures.append(f"{mid}: present but NOT found via email search path")
            continue
        if r.get("searchable") is None:
            notes.append(f"{mid}: search check skipped ({r.get('skip_reason', 'no token')})")
        passes.append(mid)
    return {"checked": len(rows), "passed": passes, "failures": failures,
            "notes": notes, "ok": len(rows) > 0 and not failures}


def evaluate_attachment_checks(rows: list) -> dict:
    """Judge attachment spot-check rows. Each row: dict with att_id, message_id,
    content_sha256, size_bytes, data (bytes|None), storage."""
    passes, failures = [], []
    for r in rows:
        label = f"att#{r['att_id']} msg={r['message_id']} sha={r['content_sha256'][:12]}…"
        data = r.get("data")
        if r.get("storage") == "metadata_only":
            # >5MB path stores no bytes by design — hash not verifiable, surface it.
            if data is None:
                passes.append(label + " [metadata_only — hash check N/A by design]")
            else:
                failures.append(label + ": metadata_only row carries data bytes")
            continue
        if data is None:
            failures.append(label + ": storage=db but data is NULL")
            continue
        actual_sha = hashlib.sha256(bytes(data)).hexdigest()
        if actual_sha != r["content_sha256"]:
            failures.append(label + f": sha256 mismatch (actual {actual_sha[:12]}…)")
            continue
        if r.get("size_bytes") is not None and len(data) != r["size_bytes"]:
            failures.append(label + f": size mismatch (actual {len(data)}, stored {r['size_bytes']})")
            continue
        passes.append(label)
    return {"checked": len(rows), "passed": passes, "failures": failures,
            "ok": len(rows) > 0 and not failures}


def build_verdict(results: dict, commit: str, brief: str = "BACKFILL_VERIFY_1") -> str:
    """Render the exact POST_DEPLOY_AC_VERDICT v1 block (AC3) preceded by the
    full per-source detail (explicit numbers, named ids, loud failures)."""
    lines = []
    all_ok = True
    evidence_bits = []
    for source, res in sorted(results.items()):
        counts = res["counts"]
        msgs = res["messages"]
        atts = res["attachments"]
        src_ok = source_ok(res)
        all_ok = all_ok and src_ok
        lines.append(f"== source={source} ==")
        for err in res.get("collector_failures", []):
            lines.append(f"  FAIL collector: {err}")
        counted = counts.get("counted_folders", counts["folders"])
        if counts.get("allowlist"):
            lines.append(f"  allowlist: {', '.join(counts['allowlist'])}")
        for folder, n in sorted(counts["folders"].items()):
            tag = "counted" if folder in counted else "info-only"
            lines.append(f"  mailbox folder {folder!r}: {n} [{tag}]")
        for miss in counts.get("allowlist_missing", []):
            lines.append(f"  FAIL allowlist folder {miss!r} not found on mailbox")
        lines.append(
            f"  mailbox_total={counts['mailbox_total']} store_count={counts['store_count']} "
            f"ratio={counts['ratio']} (tolerance {counts['tolerance']}) -> "
            f"{'PASS' if counts['ok'] else 'FAIL'}"
        )
        lines.append(
            f"  message spot-checks: {len(msgs['passed'])}/{msgs['checked']} passed "
            f"-> {'PASS' if msgs['ok'] else 'FAIL'}"
        )
        for mid in msgs["passed"]:
            lines.append(f"    PASS {mid}")
        for f in msgs["failures"]:
            lines.append(f"    FAIL {f}")
        for n in msgs.get("notes", []):
            lines.append(f"    NOTE {n}")
        lines.append(
            f"  attachment spot-checks: {len(atts['passed'])}/{atts['checked']} passed "
            f"-> {'PASS' if atts['ok'] else 'FAIL'}"
        )
        for p in atts["passed"]:
            lines.append(f"    PASS {p}")
        for f in atts["failures"]:
            lines.append(f"    FAIL {f}")
        bit = (
            f"{source}: store {counts['store_count']}/{counts['mailbox_total']} "
            f"(ratio {counts['ratio']}), msgs {len(msgs['passed'])}/{msgs['checked']}, "
            f"atts {len(atts['passed'])}/{atts['checked']}"
        )
        n_collector_fails = len(res.get("collector_failures", []))
        if n_collector_fails:
            bit += f", collector_failures {n_collector_fails}"
        evidence_bits.append(bit)

    ac_result = "PASS" if all_ok else "FAIL"
    done_state = "DONE" if all_ok else "NOT_DONE"
    next_action = "none" if all_ok else "lead review of FAIL lines above; re-run after fix"
    verdict = "\n".join([
        "POST_DEPLOY_AC_VERDICT v1",
        f"brief: {brief}",
        "task_class: other",
        f"commit: {commit}",
        "deploy: N/A",
        "surface_checked: IMAP(bluewin) + Graph(M365) vs email_messages/email_attachments",
        f"ac_result: {ac_result}",
        f"evidence: {' | '.join(evidence_bits) if evidence_bits else 'no sources checked'}",
        f"done_state: {done_state}",
        "writeback: n/a:read-only verification harness",
        f"next_action: {next_action}",
    ])
    return "\n".join(lines) + "\n\n" + verdict


# --------------------------------------------------------------------------
# Baseline pure logic (INGESTION_COMPLETENESS_P0_MEASURE_1) — unit-tested
# --------------------------------------------------------------------------

def _fmt_secs(s) -> str:
    """Human-readable seconds: '900s (15.0m)' / '90061s (1.0d)'. None -> 'n/a'."""
    if s is None:
        return "n/a"
    s = int(s)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s}s ({s/60:.1f}m)"
    if s < 172800:
        return f"{s}s ({s/3600:.1f}h)"
    return f"{s}s ({s/86400:.1f}d)"


def compute_lag(max_ts, now, poll_interval_s, label: str = "ingest") -> dict:
    """Recency lag for one source's newest stored timestamp vs `now`.

    `max_ts` / `now` are tz-aware datetimes (or None). `poll_interval_s` is the
    source's poll interval in seconds, or None for event-driven sources (WAHA
    webhook) where the 'lag < poll interval' clause does not apply.

    Returns explicit numbers; `within_interval` is the machine-checkable Nirodha
    verdict (True/False/None). Never raises on a None timestamp — a source with
    no rows is a loud `within_interval=None` with a reason, not a crash."""
    if max_ts is None:
        return {"label": label, "max_ts": None, "lag_seconds": None,
                "poll_interval_s": poll_interval_s, "within_interval": None,
                "note": "no rows / null timestamp — lag unmeasurable"}
    lag = (now - max_ts).total_seconds()
    if poll_interval_s is None:
        within, note = None, "event-driven (no poll interval) — webhook latency, not poll lag"
    else:
        within = lag <= poll_interval_s
        note = "lag <= poll interval" if within else "lag EXCEEDS poll interval"
    return {"label": label, "max_ts": max_ts.isoformat(), "lag_seconds": round(lag),
            "poll_interval_s": poll_interval_s, "within_interval": within, "note": note}


def evaluate_presence_checks(rows: list) -> dict:
    """Judge presence/integrity spot-check rows (Plaud + WhatsApp samples).

    Each row: dict with `id`, optional `present` (bool, default True),
    `body_len` (int), optional `extra_fail` (str — e.g. 'chat_id null').
    Failures are listed loud, one line per failed id (mirrors AC4 style)."""
    passes, failures = [], []
    for r in rows:
        rid = r["id"]
        if r.get("present", True) is False:
            failures.append(f"{rid}: sampled from source truth but ABSENT in store")
            continue
        if r.get("body_len", 0) <= 0:
            failures.append(f"{rid}: present but EMPTY body")
            continue
        if r.get("extra_fail"):
            failures.append(f"{rid}: {r['extra_fail']}")
            continue
        passes.append(rid)
    return {"checked": len(rows), "passed": passes, "failures": failures,
            "ok": len(rows) > 0 and not failures}


def build_baseline_report(records: dict, commit: str, seed: str,
                          brief: str = "INGESTION_COMPLETENESS_P0_MEASURE_1") -> str:
    """Render the consolidated 4-source baseline (AC5): per source
    {completeness%, lag, gap_count, sample_result}, explicit numbers, loud
    failures, scope notes preserved. Pure: never touches network/DB."""
    lines = [f"INGESTION COMPLETENESS BASELINE — {brief}",
             f"commit: {commit}   seed: {seed}",
             "read-only measurement: no INSERT/UPDATE, no migration, no deploy",
             ""]
    summary = []
    for source in sorted(records, key=lambda s: BASELINE_SOURCES.index(s)
                         if s in BASELINE_SOURCES else 99):
        rec = records[source]
        kind = rec.get("kind", SOURCE_KIND.get(source, "?"))
        c = rec["completeness"]
        lag = rec["lag"]
        ing = lag.get("ingest", {})
        con = lag.get("content", {})
        smp = rec["sample"]
        store, truth = c["store_count"], c["mailbox_total"]
        gap = truth - store
        lines.append(f"== source={source} (kind={kind}) ==")
        for err in rec.get("collector_failures", []):
            lines.append(f"  FAIL collector: {err}")
        # completeness
        comp_verdict = "PASS" if c["ok"] else "FAIL"
        lines.append(
            f"  completeness: store={store} truth={truth} ratio={c['ratio']} "
            f"gap={gap} (tolerance {c['tolerance']}) -> {comp_verdict}")
        # lag (ingest = liveness; content = newest item we hold)
        lines.append(
            f"  lag[ingest]:  newest={ing.get('max_ts')} lag={_fmt_secs(ing.get('lag_seconds'))} "
            f"vs poll={_fmt_secs(ing.get('poll_interval_s'))} -> "
            f"{_lag_tag(ing.get('within_interval'))} ({ing.get('note','')})")
        lines.append(
            f"  lag[content]: newest={con.get('max_ts')} lag={_fmt_secs(con.get('lag_seconds'))}")
        # sample
        smp_verdict = "PASS" if smp["ok"] else "FAIL"
        lines.append(
            f"  sample: {len(smp['passed'])}/{smp['checked']} present+nonempty -> {smp_verdict}")
        for p in smp["passed"]:
            lines.append(f"    PASS {p}")
        for f in smp["failures"]:
            lines.append(f"    FAIL {f}")
        for note in rec.get("scope_notes", []):
            lines.append(f"  scope: {note}")
        lines.append("")
        summary.append(
            f"{source}: store={store}/{truth} ratio={c['ratio']} gap={gap} "
            f"ingest_lag={_fmt_secs(ing.get('lag_seconds'))} "
            f"sample={len(smp['passed'])}/{smp['checked']} "
            f"[{comp_verdict}/{smp_verdict}]")
    lines.append("SUMMARY (per source):")
    for s in summary:
        lines.append(f"  {s}")
    return "\n".join(lines)


def _lag_tag(within) -> str:
    if within is True:
        return "WITHIN"
    if within is False:
        return "EXCEEDS"
    return "N/A"


# --------------------------------------------------------------------------
# Live collectors (read-only; exercised at RUN time, mocked in tests)
# --------------------------------------------------------------------------

def _db_conn():
    import psycopg2
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(url)
    cur = conn.cursor()
    cur.execute("SET default_transaction_read_only = on")  # hard read-only guard
    conn.commit()
    cur.close()
    return conn


def store_count(conn, source: str) -> int:
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM email_messages WHERE source = %s", (source,))
        n = cur.fetchone()[0]
        cur.close()
        return int(n)
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"store_count({source}) failed: {e}") from e


def imap_folder_counts() -> tuple:
    """EXAMINE (readonly) every folder on the bluewin mailbox.

    Returns ({folder: count}, {folder: LIST-flags-string}) — flags feed the
    default-allowlist sent-folder detection."""
    import imaplib
    user = os.getenv("BLUEWIN_USER", "dvallen@bluewin.ch")
    password = os.getenv("BLUEWIN_PASS", "")
    if not password:
        raise RuntimeError("BLUEWIN_PASS not set")
    counts, flags_map = {}, {}
    imap = imaplib.IMAP4_SSL(BLUEWIN_IMAP_HOST)
    try:
        imap.login(user, password)
        typ, listing = imap.list()
        if typ != "OK":
            raise RuntimeError(f"IMAP LIST failed: {typ}")
        for raw in listing or []:
            if not raw:
                continue
            decoded = raw.decode(errors="replace")
            if "\\Noselect" in decoded:
                continue
            # LIST line: (flags) "delim" folder-name (possibly quoted)
            name = decoded.rsplit(' "', 1)[-1].strip('"') if ' "' in decoded \
                else decoded.split()[-1].strip('"')
            flags_map[name] = decoded.split(")", 1)[0].lstrip("(") if ")" in decoded else ""
            typ, data = imap.select(f'"{name}"', readonly=True)  # EXAMINE
            if typ == "OK":
                counts[name] = int(data[0])
            else:
                counts[name] = -1  # loud: folder exists but EXAMINE failed
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return counts, flags_map


def graph_folder_counts() -> dict:
    """Top-level mailFolders totalItemCount for the configured Graph mailbox."""
    from kbl.graph_client import GraphClient
    client = GraphClient()
    if not client.is_ready():
        raise RuntimeError("GraphClient not ready (creds/toggle missing)")
    counts = {}
    resp = client.get(
        f"/users/{client.cfg.mail_user}/mailFolders",
        params={"$select": "displayName,totalItemCount", "$top": "100"},
        timeout=30,
    )
    while resp is not None:
        for f in resp.get("value", []):
            counts[f.get("displayName", "?")] = int(f.get("totalItemCount", 0))
        nxt = resp.get("@odata.nextLink")
        resp = client.get_url(nxt, timeout=30) if nxt else None
    if not counts:
        raise RuntimeError("Graph returned no mail folders")
    return counts


def spot_check_messages(conn, source: str, n: int, seed: str) -> list:
    """Deterministic sample of n messages; verify body non-empty + findable via
    the live email search path (tools.email._build_email_search_sql)."""
    from tools.email import _build_email_search_sql
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT message_id, subject, sender_email, "
            "COALESCE(LENGTH(full_body), 0) AS body_len "
            "FROM email_messages WHERE source = %s "
            "ORDER BY md5(message_id || %s) LIMIT %s",
            (source, seed, n),
        )
        sampled = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"spot_check_messages({source}) failed: {e}") from e

    rows = []
    for message_id, subject, sender_email, body_len in sampled:
        row = {"message_id": message_id, "body_len": body_len, "searchable": None}
        token = (subject or "").strip() or (sender_email or "").strip()
        if not token:
            row["skip_reason"] = "no subject/sender token to search on"
            rows.append(row)
            continue
        token = token[:60]  # keep the ILIKE term sane
        sql, params = _build_email_search_sql(token, source, 50)
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            found = {r[0] for r in cur.fetchall()}
            cur.close()
            row["searchable"] = message_id in found
        except Exception as e:
            conn.rollback()
            row["searchable"] = False
            row["skip_reason"] = f"search query errored: {e}"
        rows.append(row)
    return rows


def spot_check_attachments(conn, source: str, n: int, seed: str) -> list:
    """Deterministic sample of n stored attachments; fetch bytes for hash check."""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, message_id, content_sha256, size_bytes, data, storage "
            "FROM email_attachments WHERE source = %s "
            "ORDER BY md5(content_sha256 || %s) LIMIT %s",
            (source, seed, n),
        )
        sampled = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"spot_check_attachments({source}) failed: {e}") from e
    return [
        {"att_id": att_id, "message_id": mid, "content_sha256": sha,
         "size_bytes": size, "data": data, "storage": storage}
        for att_id, mid, sha, size, data, storage in sampled
    ]


# --------------------------------------------------------------------------
# Baseline live collectors (read-only; mocked in tests, run at RUN time)
# --------------------------------------------------------------------------

def _poll_intervals() -> dict:
    """Live poll intervals from config.triggers.* (seconds); fall back to the
    documented constants if config is unreadable. whatsapp stays None (webhook)."""
    try:
        from config.settings import config
        return {
            "bluewin": int(config.triggers.email_check_interval),
            "graph": int(config.triggers.graph_mail_check_interval),
            "plaud": int(config.triggers.plaud_scan_interval),
            "whatsapp": None,
        }
    except Exception:
        return dict(FALLBACK_POLL_INTERVALS)


def _count(conn, sql: str, params: tuple = ()) -> int:
    """Run a COUNT(*) read-only and return the int (rolls back on error)."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        n = cur.fetchone()[0]
        cur.close()
        return int(n)
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"count failed [{sql}]: {e}") from e


def meeting_store_count(conn, source: str = "plaud") -> int:
    """Stored transcript count for a source (default plaud)."""
    return _count(conn, "SELECT COUNT(*) FROM meeting_transcripts WHERE source = %s",
                  (source,))


def whatsapp_store_count(conn) -> int:
    """Stored WhatsApp message count (no source column on whatsapp_messages)."""
    return _count(conn, "SELECT COUNT(*) FROM whatsapp_messages")


def latest_timestamp(conn, source: str, which: str = "ingest"):
    """MAX(ts) for a source's store table; `which` in {ingest, content}.

    Table + column names come from the code-controlled STORE_TABLES map (never
    user input), so the f-string interpolation is injection-safe. Returns a
    tz-aware datetime or None (empty table / all-null column)."""
    spec = STORE_TABLES[source]
    col = spec["ingest_ts"] if which == "ingest" else spec["content_ts"]
    where, params = "", ()
    if spec["source_col"]:
        where = f"WHERE {spec['source_col']} = %s"
        params = (source,)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT MAX({col}) FROM {spec['table']} {where}", params)
        ts = cur.fetchone()[0]
        cur.close()
        return ts
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"latest_timestamp({source},{which}) failed: {e}") from e


def _plaud_get(path: str, timeout: int = 30) -> dict | None:
    """Minimal read-only GET to the Plaud web API — a self-contained local copy so
    the verifier never imports triggers.plaud_trigger. That import chain
    (triggers.plaud_trigger -> triggers.state, whose module-global TriggerState()
    runs CREATE TABLE / ALTER TABLE / CREATE INDEX + commit at import time) would
    violate the read-only guarantee the moment DATABASE_URL is present (F1, codex
    #4629). This helper imports only config.settings + httpx — neither touches the
    DB. Mirrors triggers.plaud_trigger._plaud_api's auth shape. GET only — no writes."""
    import httpx
    from config.settings import config

    domain = config.plaud.api_domain
    if not domain:
        raise RuntimeError("PLAUD_API_DOMAIN not set")
    token = config.plaud.api_token
    if not token:
        raise RuntimeError("PLAUD_TOKEN not set — Plaud truth-collector disabled")
    # Token from localStorage may already include a "bearer " prefix — use as-is.
    auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    headers = {"Authorization": auth, "Content-Type": "application/json"}
    url = f"{domain}{path}"
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        raise RuntimeError(f"Plaud GET {path} failed: {e}") from e


def plaud_truth() -> tuple:
    """Read-only upstream truth for Plaud: (data_file_total, [recording_ids]).

    Truth = `data_file_total` from GET /file/simple/web (the authoritative count;
    fetch_plaud_recordings() returns only data_file_list and discards the total).
    Falls back to len(list) if the field is absent. GET only — no writes.

    Uses the local _plaud_get (NOT triggers.plaud_trigger) so exercising the Plaud
    truth path never triggers triggers.state's import-time DDL (F1, codex #4629)."""
    data = _plaud_get("/file/simple/web")
    if not data or not isinstance(data, dict):
        raise RuntimeError("Plaud API returned no data (token unset/expired or domain missing)")
    lst = data.get("data_file_list") or []
    total = data.get("data_file_total")
    if total is None:
        total = len(lst)
    ids = [str(r.get("id")) for r in lst if isinstance(r, dict) and r.get("id") is not None]
    return int(total), ids


def plaud_sample(conn, ids: list, n: int, seed: str) -> list:
    """Deterministic sample of n recording ids; check present in store + body
    non-empty. Reuses deterministic_order_key so the sample is reproducible."""
    if not ids:
        return []
    ordered = sorted(set(ids), key=lambda i: deterministic_order_key(i, seed))
    picked = ordered[:n]
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, COALESCE(LENGTH(full_transcript), 0) "
            "FROM meeting_transcripts WHERE source = 'plaud' AND id = ANY(%s)",
            (picked,))
        found = {r[0]: r[1] for r in cur.fetchall()}
        cur.close()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"plaud_sample failed: {e}") from e
    return [{"id": rid, "present": rid in found, "body_len": found.get(rid, 0)}
            for rid in picked]


def whatsapp_truth_count(chat_limit: int = DEFAULT_WA_CHAT_LIMIT,
                         per_chat_msg_limit: int = DEFAULT_WA_MSG_LIMIT) -> tuple:
    """WhatsApp upstream truth = SUM of per-chat message counts (WAHA exposes no
    aggregate). Read-only (GET). Returns (per_chat:{chat_id:count}, failed:[ids]).

    BOUNDED: each chat counts at most `per_chat_msg_limit` messages, over WAHA's
    NoWeb in-memory window — a lower bound, forward-from-enrollment only. Every
    per-chat fetch is individually wrapped; a failing chat lands in `failed`,
    never crashes the sum (never hot-path a full-history fetch)."""
    from triggers.waha_client import list_chats, fetch_messages
    chats = list_chats(limit=chat_limit)
    per_chat, failed = {}, []
    for c in chats:
        cid = c.get("id") if isinstance(c, dict) else None
        if not cid:
            continue
        try:
            msgs = fetch_messages(cid, limit=per_chat_msg_limit)
            per_chat[cid] = len(msgs)
        except Exception:
            failed.append(cid)
    return per_chat, failed


def whatsapp_sample(conn, n: int, seed: str) -> list:
    """Deterministic sample of n stored WA rows; check body non-empty + chat_id
    present. (No clean WAHA<->store id join, so this is a store-integrity check.)"""
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, chat_id, COALESCE(LENGTH(full_text), 0) "
            "FROM whatsapp_messages ORDER BY md5(id || %s) LIMIT %s",
            (seed, n))
        sampled = cur.fetchall()
        cur.close()
    except Exception as e:
        conn.rollback()
        raise RuntimeError(f"whatsapp_sample failed: {e}") from e
    rows = []
    for rid, chat_id, body_len in sampled:
        row = {"id": rid, "present": True, "body_len": body_len}
        if not chat_id:
            row["extra_fail"] = "chat_id null"
        rows.append(row)
    return rows


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

def _empty_counts() -> dict:
    return {"folders": {}, "counted_folders": {}, "allowlist": None,
            "allowlist_missing": [], "mailbox_total": 0, "store_count": -1,
            "ratio": 0.0, "tolerance": TOLERANCE, "ok": False}


def _empty_checks() -> dict:
    return {"checked": 0, "passed": [], "failures": [], "notes": [], "ok": False}


def source_ok(res: dict) -> bool:
    """A source passes only if every section passed AND no collector failed."""
    return (res["counts"]["ok"] and res["messages"]["ok"]
            and res["attachments"]["ok"] and not res.get("collector_failures"))


def run_verification(sources: tuple, seed: str, imap_folders: list | None = None,
                     graph_folders: list | None = None) -> dict:
    """Collect everything for the requested sources. NEVER raises (G3 S1, bus
    #2772): every collector — DB connect, mailbox counts, store count, both
    samplers — is individually wrapped; a failure becomes a loud per-source
    `collector_failures` entry and the verdict is still emitted in full.

    imap_folders None -> auto allowlist (INBOX + detected sent folder);
    graph_folders None -> DEFAULT_GRAPH_FOLDERS."""
    results = {}
    conn = None
    db_error = None
    try:
        conn = _db_conn()
    except Exception as e:
        db_error = f"db connection failed: {e}"
    try:
        for source in sources:
            errors = []
            counts, messages, attachments = _empty_counts(), _empty_checks(), _empty_checks()
            folders, allowlist = None, None
            try:
                if source == "bluewin":
                    folders, flags_map = imap_folder_counts()
                    allowlist = imap_folders or pick_imap_allowlist(folders, flags_map)
                else:
                    folders = graph_folder_counts()
                    allowlist = graph_folders or list(DEFAULT_GRAPH_FOLDERS)
            except Exception as e:
                errors.append(f"mailbox count collection failed: {e}")
            if db_error:
                errors.append(db_error)
            else:
                if folders is not None:
                    try:
                        counts = compare_counts(folders, store_count(conn, source),
                                                allowlist=allowlist)
                    except Exception as e:
                        errors.append(f"store count failed: {e}")
                        # keep the mailbox-side numbers; store_count=-1 marks the gap
                        counts = compare_counts(folders, -1, allowlist=allowlist)
                try:
                    messages = evaluate_message_checks(
                        spot_check_messages(conn, source, MSG_SAMPLE_N, seed))
                except Exception as e:
                    errors.append(f"message spot-check failed: {e}")
                try:
                    attachments = evaluate_attachment_checks(
                        spot_check_attachments(conn, source, ATT_SAMPLE_N, seed))
                except Exception as e:
                    errors.append(f"attachment spot-check failed: {e}")
            results[source] = {"counts": counts, "messages": messages,
                               "attachments": attachments,
                               "collector_failures": errors}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return results


def run_baseline(sources: tuple, seed: str, now=None,
                 wa_chat_limit: int = DEFAULT_WA_CHAT_LIMIT,
                 wa_msg_limit: int = DEFAULT_WA_MSG_LIMIT,
                 plaud_sample_n: int = PLAUD_SAMPLE_N,
                 wa_sample_n: int = WA_SAMPLE_N,
                 imap_folders: list | None = None,
                 graph_folders: list | None = None) -> dict:
    """Collect a completeness + lag baseline for each requested source. Routes
    each source by kind: email -> existing IMAP/Graph collectors; plaud/whatsapp
    -> the new adapters. Reuses compare_counts for completeness on every kind.

    NEVER raises (mirrors run_verification's contract): db connect, every
    truth/store/sample/lag collector is individually wrapped; a failure becomes
    a loud per-source `collector_failures` entry and the baseline still renders
    in full. `now` is injectable for deterministic tests."""
    now = now or datetime.now(timezone.utc)
    intervals = _poll_intervals()
    records = {}
    conn = None
    db_error = None
    try:
        conn = _db_conn()
    except Exception as e:
        db_error = f"db connection failed: {e}"
    try:
        for source in sources:
            kind = SOURCE_KIND.get(source, "?")
            errors = []
            completeness = _empty_counts()
            sample = _empty_checks()
            scope_notes = []
            lag = {"ingest": compute_lag(None, now, intervals.get(source), "ingest"),
                   "content": compute_lag(None, now, None, "content")}

            if kind == "email":
                folders, allowlist = None, None
                try:
                    if source == "bluewin":
                        folders, flags_map = imap_folder_counts()
                        allowlist = imap_folders or pick_imap_allowlist(folders, flags_map)
                    else:
                        folders = graph_folder_counts()
                        allowlist = graph_folders or list(DEFAULT_GRAPH_FOLDERS)
                except Exception as e:
                    errors.append(f"mailbox count collection failed: {e}")
                if db_error:
                    errors.append(db_error)
                else:
                    if folders is not None:
                        try:
                            completeness = compare_counts(
                                folders, store_count(conn, source), allowlist=allowlist)
                        except Exception as e:
                            errors.append(f"store count failed: {e}")
                            completeness = compare_counts(folders, -1, allowlist=allowlist)
                    try:
                        msg_rows = spot_check_messages(conn, source, plaud_sample_n, seed)
                        sample = evaluate_presence_checks(
                            [{"id": r["message_id"], "present": True,
                              "body_len": r.get("body_len", 0)} for r in msg_rows])
                    except Exception as e:
                        errors.append(f"email sample failed: {e}")
                scope_notes.append(
                    "completeness reuses the existing IMAP/Graph email collectors "
                    "(allowlisted INBOX+sent); email verdict path unchanged")

            elif kind == "plaud":
                truth_total, ids = None, []
                try:
                    truth_total, ids = plaud_truth()
                except Exception as e:
                    errors.append(f"plaud truth collection failed: {e}")
                if db_error:
                    errors.append(db_error)
                else:
                    store_n = None
                    try:
                        store_n = meeting_store_count(conn, "plaud")
                    except Exception as e:
                        errors.append(f"plaud store count failed: {e}")
                    if truth_total is not None:
                        completeness = compare_counts(
                            {"plaud:all": truth_total},
                            store_n if store_n is not None else -1)
                    try:
                        sample = evaluate_presence_checks(
                            plaud_sample(conn, ids, plaud_sample_n, seed))
                    except Exception as e:
                        errors.append(f"plaud sample failed: {e}")
                scope_notes.append(
                    "truth = Plaud data_file_total (full-history API) -> >=98% all-time achievable")

            elif kind == "whatsapp":
                per_chat, failed = {}, []
                try:
                    per_chat, failed = whatsapp_truth_count(wa_chat_limit, wa_msg_limit)
                except Exception as e:
                    errors.append(f"whatsapp truth collection failed: {e}")
                if failed:
                    errors.append(
                        f"{len(failed)} chat(s) failed per-chat fetch — excluded from truth sum")
                if db_error:
                    errors.append(db_error)
                else:
                    store_n = None
                    try:
                        store_n = whatsapp_store_count(conn)
                    except Exception as e:
                        errors.append(f"whatsapp store count failed: {e}")
                    if per_chat:
                        completeness = compare_counts(
                            per_chat, store_n if store_n is not None else -1)
                    try:
                        sample = evaluate_presence_checks(
                            whatsapp_sample(conn, wa_sample_n, seed))
                    except Exception as e:
                        errors.append(f"whatsapp sample failed: {e}")
                scope_notes.append(
                    f"WAHA truth bounded by per-chat limit {wa_msg_limit} over NoWeb "
                    "in-memory window -> FORWARD-FROM-ENROLLMENT only (lower bound)")
                scope_notes.append(
                    "ALL-TIME completeness OUT OF SCOPE (source-limited; iPhone export "
                    "is the only all-time path)")
                scope_notes.append(
                    "FLAG: candidate whatsapp_messages.source column for "
                    "waha-vs-iphone-export parity — NOT migrated (measurement-only brief)")

            if not db_error:
                for which in ("ingest", "content"):
                    try:
                        ts = latest_timestamp(conn, source, which)
                        pi = intervals.get(source) if which == "ingest" else None
                        lag[which] = compute_lag(ts, now, pi, which)
                    except Exception as e:
                        errors.append(f"lag[{which}] failed: {e}")

            records[source] = {"kind": kind, "completeness": completeness, "lag": lag,
                               "sample": sample, "collector_failures": errors,
                               "scope_notes": scope_notes}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
    return records


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def post_verdict(body: str) -> None:
    """The single permitted write: bus-post the verdict to lead + cc deputy."""
    env = dict(os.environ, BAKER_ROLE="b4")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bus_post.py"),
         "--to", "lead,deputy", "--body", body,
         "--topic", "post-deploy-ac/backfill-verify-1"],
        env=env, check=True, timeout=60,
    )


def post_baseline(body: str) -> None:
    """The single permitted write in baseline mode: bus-post the consolidated
    completeness baseline to lead (INGESTION_COMPLETENESS_P0_MEASURE_1)."""
    env = dict(os.environ, BAKER_ROLE="b3")
    subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bus_post.py"),
         "--to", "lead", "--body", body,
         "--topic", "baseline/ingestion-completeness-p0-measure-1"],
        env=env, check=True, timeout=120,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=SOURCES, help="verify one source only")
    ap.add_argument("--seed", default=DEFAULT_SEED,
                    help="sampling seed (same seed -> same spot-check ids)")
    ap.add_argument("--imap-folders", default=None,
                    help="comma-separated IMAP folder allowlist for the tolerance "
                         "check (default: INBOX + detected sent folder)")
    ap.add_argument("--graph-folders", default=",".join(DEFAULT_GRAPH_FOLDERS),
                    help="comma-separated Graph folder allowlist "
                         "(space/case-insensitive match on displayName)")
    ap.add_argument("--post", action="store_true",
                    help="bus-post the verdict to lead,deputy (the only write)")
    ap.add_argument("--json", action="store_true", help="also dump raw results JSON")
    # INGESTION_COMPLETENESS_P0_MEASURE_1 — baseline across all 4 ingest sources.
    ap.add_argument("--baseline", action="store_true",
                    help="run the 4-source completeness+lag baseline "
                         "(email + plaud + whatsapp) instead of the email verdict")
    ap.add_argument("--baseline-source", choices=BASELINE_SOURCES, default=None,
                    help="restrict --baseline to one source")
    ap.add_argument("--wa-chat-limit", type=int, default=DEFAULT_WA_CHAT_LIMIT,
                    help="WhatsApp: max chats to iterate for the truth sum")
    ap.add_argument("--wa-msg-limit", type=int, default=DEFAULT_WA_MSG_LIMIT,
                    help="WhatsApp: max messages fetched per chat (bounds the count)")
    ap.add_argument("--post-baseline", action="store_true",
                    help="bus-post the baseline report to lead (the only write in "
                         "baseline mode)")
    args = ap.parse_args()

    if args.baseline or args.baseline_source:
        b_sources = (args.baseline_source,) if args.baseline_source else BASELINE_SOURCES
        records = run_baseline(b_sources, args.seed,
                               wa_chat_limit=args.wa_chat_limit,
                               wa_msg_limit=args.wa_msg_limit)
        report = build_baseline_report(records, _git_head(), args.seed)
        print(report)
        if args.json:
            printable = json.loads(json.dumps(records, default=str))
            print(json.dumps(printable, indent=2))
        if args.post_baseline:
            post_baseline(report)
        return 0

    sources = (args.source,) if args.source else SOURCES
    imap_allow = [f.strip() for f in args.imap_folders.split(",") if f.strip()] \
        if args.imap_folders else None
    graph_allow = [f.strip() for f in args.graph_folders.split(",") if f.strip()] \
        or list(DEFAULT_GRAPH_FOLDERS)
    results = run_verification(sources, args.seed,
                               imap_folders=imap_allow, graph_folders=graph_allow)
    out = build_verdict(results, _git_head())
    print(f"seed: {args.seed}")
    print(out)
    if args.json:
        printable = json.loads(json.dumps(results, default=lambda o: f"<{len(o)} bytes>"))
        print(json.dumps(printable, indent=2))
    if args.post:
        verdict_block = out.split("POST_DEPLOY_AC_VERDICT v1", 1)
        post_verdict("POST_DEPLOY_AC_VERDICT v1" + verdict_block[1])
    return 0 if results and all(source_ok(r) for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
