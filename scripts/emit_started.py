#!/usr/bin/env python3
"""emit_started.py — CLIENT_STARTED_EMISSION_1 best-effort `started` emitter.

A recipient's FIRST NON-ACK reply to a dispatch marks that dispatch `started` (the
first-action seam, G0 #11118 / lead #11121). This helper is the SINGLE control point for
that client emission, shared by `bus_post.sh` and `bus_post.py` so the resolution +
best-effort discipline live in exactly one place.

Target resolution (lead #11216 ruling — PARENT OR THREAD; topic-match REJECTED, our
topics are long-lived + heavily reused so they would false-start unrelated dispatches):
  1. --parent <id>  → the dispatch this reply answers, most direct signal. Primary.
  2. --thread <uuid> → when no --parent, resolve the dispatch addressed to this sender in
     that thread via a bounded, UNREAD-scoped read (minimises the drain blast radius; an
     already-acked thread-only dispatch falls through to the server-side
     detect_delivery_started_sync fallback, which is retained by design).

Contract (lead #11215): the client fires AT-LEAST-ONCE; the server COALESCE is the single
dedupe authority (no client-side dedupe state). A repeat is harmless by design.

TOTAL best-effort (lead #11215 / codex #11216): NOTHING here ever escapes to the caller —
every failure axis (HTTP 4xx/5xx, network/timeout, a generic OSError, a malformed daemon
response, anything) is caught, logged one line to stderr, and swallowed. This helper
ALWAYS exits 0. The outbound post it follows has already committed; its result is
sacrosanct. Kill switch (checked by the callers): BAKER_STARTED_EMISSION_DISABLED=1.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

DAEMON_TIMEOUT_S = 15


def _log(msg: str) -> None:
    print(f"[emit_started] {msg}", file=sys.stderr, flush=True)


def _resolve_thread_dispatch(daemon: str, key: str, sender: str, thread_id: str):
    """Best-effort: return the msg_id of the un-acked kind=dispatch addressed to `sender`
    in `thread_id`, or None. UNREAD-scoped read bounds the drain side-effect (the daemon's
    GET /msg drain stamps delivered_at on returned direct-addressed rows — idempotent,
    honest for rows the recipient is reading now, never touches the started state machine).
    Returns None on ANY problem (the caller then simply does not emit)."""
    url = (f"{daemon}/msg/{urllib.parse.quote(sender)}"
           "?unread=true&kind=dispatch&limit=200")
    req = urllib.request.Request(url, headers={"X-Terminal-Key": key}, method="GET")
    with urllib.request.urlopen(req, timeout=DAEMON_TIMEOUT_S) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    for m in payload.get("messages") or []:
        if str(m.get("thread_id")) != str(thread_id):
            continue
        if m.get("kind") != "dispatch" or not m.get("execute_obligation"):
            continue
        recipients = m.get("to_terminals") or []
        if sender in recipients:
            return m.get("id")
    return None


def _post_started(daemon: str, key: str, target: int) -> None:
    url = f"{daemon}/msg/{int(target)}/started"
    req = urllib.request.Request(url, data=b"", headers={"X-Terminal-Key": key},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=DAEMON_TIMEOUT_S):
            return
    except urllib.error.HTTPError as e:
        note = f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
        note = f"{type(e).__name__}: {e}"
    _log(f"started-emit best-effort miss for target={target} ({note}); "
         "post already landed, continuing")


def resolve_and_emit(daemon: str, key: str, sender: str,
                     parent_id, thread_id) -> None:
    """Resolve the started target (parent primary, thread fallback) and fire it. TOTAL
    guard: catches EVERYTHING (incl. a generic OSError from the resolution read) so no
    failure can alter the caller's exit status."""
    try:
        target = parent_id
        if target is None and thread_id:
            target = _resolve_thread_dispatch(daemon, key, sender, thread_id)
        if target is None:
            return
        _post_started(daemon, key, target)
    except Exception as e:  # noqa: BLE001 — TOTAL best-effort: nothing may escape.
        _log(f"started-emit best-effort aborted ({type(e).__name__}: {e}); "
             "post already landed, continuing")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--daemon", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--sender", required=True)
    ap.add_argument("--parent", type=int, default=None)
    ap.add_argument("--thread", default=None)
    args = ap.parse_args()
    resolve_and_emit(args.daemon, args.key, args.sender, args.parent, args.thread)
    # ALWAYS exit 0 — the caller's post has already committed; this is best-effort.
    sys.exit(0)


if __name__ == "__main__":
    main()
