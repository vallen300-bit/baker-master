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
    python scripts/verify_backfill.py                  # both sources, print verdict
    python scripts/verify_backfill.py --source bluewin # one source
    python scripts/verify_backfill.py --post           # also bus-post verdict to lead,deputy
    python scripts/verify_backfill.py --seed myseed    # reproducible spot-check sample
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

TOLERANCE = 0.98          # store >= 98% of mailbox count (brief, locked)
MSG_SAMPLE_N = 10         # random historical messages per source (brief, locked)
ATT_SAMPLE_N = 5          # random attachments per source (brief, locked)
DEFAULT_SEED = "backfill-verify-1"
SOURCES = ("bluewin", "graph")

BLUEWIN_IMAP_HOST = os.getenv("BLUEWIN_IMAP_HOST", "imaps.bluewin.ch")


# --------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_verify_backfill.py)
# --------------------------------------------------------------------------

def compare_counts(folder_counts: dict, store_count: int,
                   tolerance: float = TOLERANCE) -> dict:
    """Compare mailbox-side per-folder counts vs store-side total for one source.

    Returns explicit numbers (AC1): every folder count, mailbox total, store
    count, ratio, threshold, ok flag. Zero-mailbox is a FAIL (a backfill that
    found nothing to verify is not a pass).
    """
    mailbox_total = sum(folder_counts.values())
    ratio = (store_count / mailbox_total) if mailbox_total else 0.0
    return {
        "folders": dict(folder_counts),
        "mailbox_total": mailbox_total,
        "store_count": store_count,
        "ratio": round(ratio, 4),
        "tolerance": tolerance,
        "ok": mailbox_total > 0 and store_count >= mailbox_total * tolerance,
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
        src_ok = counts["ok"] and msgs["ok"] and atts["ok"]
        all_ok = all_ok and src_ok
        lines.append(f"== source={source} ==")
        for folder, n in sorted(counts["folders"].items()):
            lines.append(f"  mailbox folder {folder!r}: {n}")
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
        evidence_bits.append(
            f"{source}: store {counts['store_count']}/{counts['mailbox_total']} "
            f"(ratio {counts['ratio']}), msgs {len(msgs['passed'])}/{msgs['checked']}, "
            f"atts {len(atts['passed'])}/{atts['checked']}"
        )

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


def imap_folder_counts() -> dict:
    """EXAMINE (readonly) every folder on the bluewin mailbox; return {folder: count}."""
    import imaplib
    user = os.getenv("BLUEWIN_USER", "dvallen@bluewin.ch")
    password = os.getenv("BLUEWIN_PASS", "")
    if not password:
        raise RuntimeError("BLUEWIN_PASS not set")
    counts = {}
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
    return counts


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
# Orchestration
# --------------------------------------------------------------------------

def run_verification(sources: tuple, seed: str) -> dict:
    """Collect everything for the requested sources. A collector failure is a
    loud per-source error entry, never a silent skip."""
    conn = _db_conn()
    results = {}
    try:
        for source in sources:
            try:
                folders = imap_folder_counts() if source == "bluewin" else graph_folder_counts()
            except Exception as e:
                folders = {}
                results[source] = {
                    "counts": {"folders": {}, "mailbox_total": 0, "store_count": -1,
                               "ratio": 0.0, "tolerance": TOLERANCE, "ok": False},
                    "messages": {"checked": 0, "passed": [], "notes": [],
                                 "failures": [f"mailbox count collection failed: {e}"],
                                 "ok": False},
                    "attachments": {"checked": 0, "passed": [],
                                    "failures": [], "ok": False},
                }
                continue
            results[source] = {
                "counts": compare_counts(folders, store_count(conn, source)),
                "messages": evaluate_message_checks(
                    spot_check_messages(conn, source, MSG_SAMPLE_N, seed)),
                "attachments": evaluate_attachment_checks(
                    spot_check_attachments(conn, source, ATT_SAMPLE_N, seed)),
            }
    finally:
        conn.close()
    return results


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=SOURCES, help="verify one source only")
    ap.add_argument("--seed", default=DEFAULT_SEED,
                    help="sampling seed (same seed -> same spot-check ids)")
    ap.add_argument("--post", action="store_true",
                    help="bus-post the verdict to lead,deputy (the only write)")
    ap.add_argument("--json", action="store_true", help="also dump raw results JSON")
    args = ap.parse_args()

    sources = (args.source,) if args.source else SOURCES
    results = run_verification(sources, args.seed)
    out = build_verdict(results, _git_head())
    print(f"seed: {args.seed}")
    print(out)
    if args.json:
        printable = json.loads(json.dumps(results, default=lambda o: f"<{len(o)} bytes>"))
        print(json.dumps(printable, indent=2))
    if args.post:
        verdict_block = out.split("POST_DEPLOY_AC_VERDICT v1", 1)
        post_verdict("POST_DEPLOY_AC_VERDICT v1" + verdict_block[1])
    return 0 if all(
        r["counts"]["ok"] and r["messages"]["ok"] and r["attachments"]["ok"]
        for r in results.values()
    ) else 1


if __name__ == "__main__":
    sys.exit(main())
